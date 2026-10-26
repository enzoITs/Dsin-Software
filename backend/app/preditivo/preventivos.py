"""Alertas preventivos na central (U3): a previsão vira alerta antes do problema acontecer.

Três regras, sobre o último lote de previsões:

- PREVISAO_RISCO_REGIAO: índice de risco (P3) Alto ou Muito alto em alguma hora das próximas 6 h.
- PREVISAO_FALHA_EQUIPAMENTO: probabilidade de falha em 7 dias (P1) acima do limite e sem OS aberta
  (só os de maior risco, para não inundar a central).
- PREVISAO_FALTA_AGENTES: período das próximas 6 h em que a escala atual não cobre a demanda prevista (P4)
  e o reforço recomendado ainda não foi aceito.

PREVISAO_DISPONIBILIDADE depende da tendência de disponibilidade (P6), que fica para a fase 12.

Cada alerta guarda o id da previsão (a central abre o Cartão de Previsão), para quando está previsto
e a antecedência. Quando a condição some (o período passou, o risco baixou, a OS foi aberta, o reforço
foi aceito), o alerta se resolve sozinho. Roda depois de cada lote de previsões e a cada 5 minutos.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain import limites
from app.models import Alerta, Equipamento
from app.models.enums import NivelAlerta
from app.models.enums import TipoAlerta as R
from app.preditivo.variaveis import FUSO
from app.services import motor

TIPOS = [R.previsao_risco_regiao, R.previsao_falha_equipamento, R.previsao_falta_agentes]
MOTIVO_RESOLVIDO = {
    R.previsao_risco_regiao.value: "O período previsto passou ou o risco previsto baixou",
    R.previsao_falha_equipamento.value: "OS preventiva aberta ou risco de falha previsto baixou",
    R.previsao_falta_agentes.value: "Reforço aceito, período passou ou a falta prevista diminuiu",
}
NOME_NIVEL = {"ALTO": "alto", "MUITO_ALTO": "muito alto"}


def _quando(ts: datetime, agora: datetime) -> str:
    local = pd.Timestamp(ts).tz_convert(FUSO)
    hoje = pd.Timestamp(agora).tz_convert(FUSO).date()
    dia = "hoje" if local.date() == hoje else "amanhã" if local.date() == hoje + timedelta(days=1) else f"{local:%d/%m}"
    return f"{dia}, {local:%H} h"


def _antecedencia(ts: datetime, agora: datetime) -> int:
    return max(0, int((ts - agora).total_seconds() // 60))


def _ponto_regiao(db: Session, regiao_id: int) -> tuple[float, float]:
    return tuple(db.execute(text("SELECT ST_X(ST_PointOnSurface(geom)), ST_Y(ST_PointOnSurface(geom)) FROM regiao WHERE id = :i"),
                            {"i": regiao_id}).one())


def _dados(previsao_id: int, modulo: str, inicio: datetime, fim: datetime, agora: datetime, **extra) -> dict:
    return {"preditivo": {"previsao_id": previsao_id, "modulo": modulo, "previsto_para": inicio.isoformat(),
                          "ate": fim.isoformat(), "antecedencia_min": _antecedencia(inicio, agora), **extra}}


def risco_regioes(db: Session, agora: datetime, horas: int) -> list[dict]:
    """Por região, as horas Alto ou Muito alto das próximas `horas` no último lote de P3."""
    origem = db.scalar(text("SELECT max(detalhe->>'origem') FROM previsao WHERE modulo = 'P3'"))
    if not origem:
        return []
    linhas = db.execute(text("""
        SELECT p.id, p.regiao_id, r.nome regiao, p.horizonte_inicio inicio, p.horizonte_fim fim, p.valor, p.nivel,
               p.detalhe->>'motivo_principal' motivo
        FROM previsao p JOIN regiao r ON r.id = p.regiao_id
        WHERE p.modulo = 'P3' AND p.detalhe->>'origem' = :o AND p.detalhe->>'granularidade' = 'hora'
          AND p.horizonte_fim > :a AND p.horizonte_inicio < :b AND p.nivel IN ('ALTO', 'MUITO_ALTO')
        ORDER BY p.regiao_id, p.horizonte_inicio"""),
        {"o": origem, "a": agora, "b": agora + timedelta(hours=horas)}).mappings().all()
    por_regiao: dict[int, list] = {}
    for x in linhas:
        por_regiao.setdefault(x["regiao_id"], []).append(x)
    saida = []
    for rid, xs in por_regiao.items():
        pico = max(xs, key=lambda x: x["valor"])
        saida.append({"regiao_id": rid, "regiao": xs[0]["regiao"], "primeira": xs[0], "pico": pico, "horas": len(xs),
                      "fim": xs[-1]["fim"]})
    return saida


def falhas(db: Session, prob: float, maximo: int) -> list[dict]:
    """Maiores probabilidades de falha em 7 dias (último lote de P1), sem OS aberta, de equipamentos em operação."""
    return list(db.execute(text("""
        SELECT p.id, p.alvo_id equipamento_id, p.valor, p.nivel, p.horizonte_inicio inicio, p.horizonte_fim fim,
               p.detalhe->'alvo'->>'nome' codigo, p.fatores->0->>'descricao' fator
        FROM previsao p JOIN equipamento e ON e.id = p.alvo_id
        WHERE p.modulo = 'P1' AND p.horizonte_fim - p.horizonte_inicio = interval '7 days'
          AND p.horizonte_inicio = (SELECT max(horizonte_inicio) FROM previsao WHERE modulo = 'P1')
          AND p.valor >= :p AND e.situacao = 'operacional'
          AND NOT EXISTS (SELECT 1 FROM ordem_servico o WHERE o.equipamento_id = e.id AND o.status = 'aberta')
        ORDER BY p.valor DESC LIMIT :n"""), {"p": prob, "n": maximo}).mappings().all())


def falta_agentes(db: Session, agora: datetime, horas: int, minimo: float, fracao: float) -> list[dict]:
    """Períodos das próximas horas (último plano de P4) em que a escala atual não cobre a demanda prevista."""
    origem = db.scalar(text("SELECT max(detalhe->>'origem') FROM previsao WHERE modulo = 'P4'"))
    if not origem:
        return []
    linhas = db.execute(text("""
        SELECT p.id, p.regiao_id, r.nome regiao, p.horizonte_inicio inicio, p.horizonte_fim fim, p.nivel,
               (p.detalhe->>'falta_antes')::float falta, (p.detalhe->>'demanda')::float demanda,
               (p.detalhe->>'capacidade_antes')::float capacidade, p.detalhe->>'rotulo' rotulo,
               jsonb_array_length(coalesce(p.detalhe->'entram', '[]'::jsonb)) entram,
               (SELECT rc.estado::text FROM recomendacao rc WHERE rc.previsao_id = p.id ORDER BY rc.id DESC LIMIT 1) decisao
        FROM previsao p JOIN regiao r ON r.id = p.regiao_id
        WHERE p.modulo = 'P4' AND p.detalhe->>'origem' = :o AND p.horizonte_fim > :a AND p.horizonte_inicio < :b
        ORDER BY p.regiao_id, p.horizonte_inicio"""),
        {"o": origem, "a": agora, "b": agora + timedelta(hours=horas)}).mappings().all()
    saida = []
    for x in linhas:
        if x["decisao"] in ("aceita", "ajustada"):
            continue
        if x["falta"] is None or x["falta"] < minimo or not x["demanda"] or x["falta"] / x["demanda"] < fracao:
            continue
        saida.append(dict(x))
    return saida


def verificar(db: Session, agora: datetime | None = None) -> dict:
    cfg = limites.carregar(db)
    agora = agora or datetime.now(timezone.utc)
    horas = cfg["prev_alerta_horas"]
    vistas: set[str] = set()
    n = {"risco_regiao": 0, "falha_equipamento": 0, "falta_agentes": 0}

    for a in risco_regioes(db, agora, horas):
        k = motor.chave(R.previsao_risco_regiao, "regiao", a["regiao"])
        vistas.add(k)
        p, pico = a["primeira"], a["pico"]
        quando = _quando(p["inicio"], agora)
        msg = (f"Previsto para {quando}: risco {NOME_NIVEL[pico['nivel']]} na região {a['regiao']} "
               f"(índice {pico['valor']:.0f} às {pd.Timestamp(pico['inicio']).tz_convert(FUSO):%H} h). {p['motivo'] or ''}").strip()
        lon, lat = _ponto_regiao(db, a["regiao_id"])
        al = motor.abrir(db, R.previsao_risco_regiao, k, msg, regiao=a["regiao"], lon=lon, lat=lat, agora=agora, correlacionar=False,
                         dados=_dados(pico["id"], "P3", p["inicio"], a["fim"], agora, indice=round(pico["valor"]),
                                      nivel=pico["nivel"], horas=a["horas"]))
        if al is not None and pico["nivel"] == "MUITO_ALTO" and al.nivel == NivelAlerta.media:
            al.nivel = NivelAlerta.alta
            al.motivos_nivel = [*(al.motivos_nivel or []), "Média → Alta: risco previsto muito alto"]
        n["risco_regiao"] += al is not None

    for x in falhas(db, cfg["prev_alerta_falha_prob"], cfg["prev_alerta_falha_max"]):
        e = db.get(Equipamento, x["equipamento_id"])
        if e is None:
            continue
        k = motor.chave_eq(R.previsao_falha_equipamento, e.id)
        vistas.add(k)
        msg = (f"{x['codigo']}: {x['valor'] * 100:.0f}% de chance de falhar nos próximos 7 dias, sem OS aberta"
               + (f". Principal fator: {x['fator'][0].lower()}{x['fator'][1:]}" if x["fator"] else ""))
        al = motor.abrir(db, R.previsao_falha_equipamento, k, msg, equipamento=e, agora=agora, correlacionar=False,
                         dados=_dados(x["id"], "P1", x["inicio"], x["fim"], agora, probabilidade=round(x["valor"], 3),
                                      nivel=x["nivel"]))
        n["falha_equipamento"] += al is not None

    for x in falta_agentes(db, agora, horas, cfg["prev_alerta_falta_min"], cfg["prev_alerta_falta_pct"]):
        k = motor.chave(R.previsao_falta_agentes, "regiao", f"{x['regiao']}:{pd.Timestamp(x['inicio']).isoformat()}")
        vistas.add(k)
        rotulo = x["rotulo"][:1].lower() + x["rotulo"][1:]
        msg = (f"Previsto para {rotulo}: faltam {x['falta']:.0f} agentes-hora na região {x['regiao']} "
               f"(a escala cobre {x['capacidade']:.0f} de {x['demanda']:.0f})"
               + (". Há recomendação de reforço para aceitar" if x["entram"] else ""))
        lon, lat = _ponto_regiao(db, x["regiao_id"])
        al = motor.abrir(db, R.previsao_falta_agentes, k, msg, regiao=x["regiao"], lon=lon, lat=lat, agora=agora,
                         correlacionar=False, dados=_dados(x["id"], "P4", x["inicio"], x["fim"], agora,
                                                           falta=x["falta"], demanda=x["demanda"]))
        n["falta_agentes"] += al is not None

    resolvidas = 0
    for a in db.scalars(select(Alerta).where(Alerta.tipo.in_(TIPOS), Alerta.resolvido_em.is_(None))).unique():
        if a.chave not in vistas:
            motor.resolver(db, a, "motor", MOTIVO_RESOLVIDO[a.tipo.value], agora)
            resolvidas += 1
    db.commit()
    return {**n, "resolvidas": resolvidas}
