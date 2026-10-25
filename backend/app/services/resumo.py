"""Resumo do turno e "perguntar ao painel".

Os fatos são sempre calculados aqui, a partir dos alertas, indicadores e regiões.
Com IA disponível, o Claude só reescreve esses fatos num texto curto; sem IA (ou se ela
falhar), um modelo de texto monta a frase. Nada é inventado: a IA recebe só os fatos.
"""

import json
import logging
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import limites, regras
from app.domain.estados import RegraViolada
from app.models import Alerta, Bairro, Equipamento, TipoEquipamento
from app.services import central
from app.services import ia as ia_servico
from app.services.equipamentos import Filtros

log = logging.getLogger("atalaia.resumo")
ESTADO_ROTULO = {"normal": "Normal", "atencao": "Atenção", "critica": "Crítica"}


def em_regiao(nome: str | None) -> str:
    if not nome:
        return "sem região"
    return "no Centro" if nome == "Centro" else f"na região {nome}"


def _num(v: float | None, casas: int = 1) -> str:
    return "—" if v is None else f"{v:.{casas}f}".replace(".", ",")


def fatos_turno(db: Session, agora: datetime | None = None, regiao: str | None = None) -> dict:
    agora = agora or central.agora_utc()
    cfg = limites.carregar(db)
    inicio = agora - timedelta(hours=1)
    cond = [Alerta.criado_em >= inicio, Alerta.nivel.in_(central.NIVEIS_VISIVEIS),
            Alerta.reconhecido_por.is_distinct_from(central.LINHA_DE_BASE)]
    if regiao:
        cond.append(Alerta.regiao == regiao)
    grupos = db.execute(
        select(Alerta.tipo, TipoEquipamento.nome, Alerta.regiao, func.count(), func.max(Alerta.nivel))
        .outerjoin(Equipamento, Equipamento.id == Alerta.equipamento_id)
        .outerjoin(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
        .where(*cond)
        .group_by(Alerta.tipo, TipoEquipamento.nome, Alerta.regiao)
    ).all()
    novos = sorted(
        ({"regra": r.value, "tipo": t, "regiao": reg, "quantidade": n, "nivel": niv.value,
          "frase": f"{central.frase_alertas(r, t, n)} {em_regiao(reg)}"} for r, t, reg, n, niv in grupos),
        key=lambda g: (-regras.rank(g["nivel"]), -g["quantidade"]),
    )
    cond_res = [Alerta.resolvido_em >= inicio, Alerta.nivel.in_(central.NIVEIS_VISIVEIS)]
    if regiao:
        cond_res.append(Alerta.regiao == regiao)
    resolvidos = db.scalar(select(func.count()).select_from(Alerta).where(*cond_res)) or 0

    f = Filtros(regiao=[regiao]) if regiao else Filtros()
    ind = central.indicadores(db, f, agora=agora)
    regs = central.saude_regioes(db, f, agora=agora)
    foto = central._instantaneo_perto(db, inicio)
    antes = {r["regiao"]: r["estado"] for r in (foto.regioes if foto else [])}
    return {
        "inicio": central.local(inicio, cfg).strftime("%H:%M"),
        "fim": central.local(agora, cfg).strftime("%H:%M"),
        "regiao": regiao,
        "novos": novos,
        "resolvidos": resolvidos,
        "abertos": ind["valores"]["alertas"],
        "disponibilidade": ind["valores"]["disponibilidade"],
        "variacao_disponibilidade": ind["variacao"].get("disponibilidade"),
        "agentes_ativos": ind["valores"]["agentes_ativos"],
        "sem_sinal": ind["valores"]["sem_sinal"],
        "regioes": [
            {"regiao": r["regiao"], "estado": r["estado"], "nota": r["nota"], "motivo": r["motivo"],
             "antes": antes.get(r["regiao"])}
            for r in regs
        ],
    }


def texto_modelo(f: dict) -> str:
    partes = []
    alvo = f" {em_regiao(f['regiao'])}" if f["regiao"] else ""
    cab = f"Última hora ({f['inicio']}–{f['fim']}){alvo}: "
    if f["novos"]:
        frases = [g["frase"] if not f["regiao"] else g["frase"].replace(f" {em_regiao(f['regiao'])}", "") for g in f["novos"][:4]]
        resto = len(f["novos"]) - 4
        partes.append(cab + "; ".join(frases) + (f"; e mais {resto} grupo(s) de alertas" if resto > 0 else "") + ".")
    else:
        partes.append(cab + "nenhum problema novo.")
    a = f["abertos"]
    partes.append(
        f"{f['resolvidos']} alerta{'s' if f['resolvidos'] != 1 else ''} resolvido{'s' if f['resolvidos'] != 1 else ''}; "
        f"seguem abertos {a.get('critica', 0)} crítico(s), {a.get('alta', 0)} alto(s) e {a.get('media', 0)} médio(s)."
    )
    var = f["variacao_disponibilidade"]
    partes.append(
        f"Disponibilidade {_num(f['disponibilidade'])}%"
        + (f" ({'+' if var >= 0 else '−'}{_num(abs(var))} p.p. na hora)" if isinstance(var, (int, float)) else "")
        + f", {f['agentes_ativos']} agentes em atividade."
    )
    fora = [r for r in f["regioes"] if r["estado"] != "normal"]
    mudaram = [r for r in f["regioes"] if r["antes"] and r["antes"] != r["estado"]]
    if fora:
        partes.append("Fora do normal: " + "; ".join(
            f"{r['regiao']} ({ESTADO_ROTULO[r['estado']]}, {r['motivo']})" for r in fora[:3]) + ".")
    elif not f["regiao"]:
        partes.append("Todas as regiões em Normal.")
    if mudaram:
        partes.append("Mudaram de estado: " + "; ".join(
            f"{r['regiao']} {ESTADO_ROTULO.get(r['antes'], r['antes'])} → {ESTADO_ROTULO[r['estado']]}" for r in mudaram) + ".")
    return " ".join(partes)


SCHEMA_TEXTO = {
    "type": "object",
    "additionalProperties": False,
    "required": ["texto"],
    "properties": {"texto": {"type": "string"}},
}

SYSTEM_RESUMO = """Você escreve o resumo de turno da central de operações de trânsito e segurança de uma cidade.
Recebe fatos em JSON (alertas novos na última hora, resolvidos, abertos, disponibilidade, regiões) e um texto-base.
Escreva em português do Brasil, no máximo 3 frases curtas, para o gestor que acabou de chegar:
primeiro o que mudou e onde, depois o que exige atenção agora. Use só números e nomes presentes nos fatos;
não invente causas nem recomendações. Sem saudação, sem markdown."""

SYSTEM_PERGUNTA = """Você responde perguntas do gestor sobre a situação atual da cidade, na central de operações.
Use só os fatos em JSON (alertas, índice da região, disponibilidade, agentes). Responda em português do Brasil,
em até 3 frases curtas, começando pela resposta direta. Se os fatos não respondem, diga isso. Sem markdown."""


def _com_ia(system: str, fatos: dict, base: str, pergunta: str | None = None) -> str | None:
    if not ia_servico.disponivel():
        return None
    try:
        conteudo = [{"type": "text", "text": (
            (f"Pergunta: {pergunta}\n\n" if pergunta else "")
            + f"Fatos:\n{json.dumps(fatos, ensure_ascii=False, default=str)}\n\nTexto-base:\n{base}"
        )}]
        texto = ia_servico._chamar(system, conteudo, SCHEMA_TEXTO, effort="low").get("texto", "").strip()
        return texto or None
    except RegraViolada as exc:
        log.info("resumo sem IA: %s", exc.mensagem)
        return None


def resumo_turno(db: Session, agora: datetime | None = None, usar_ia: bool = True) -> dict:
    fatos = fatos_turno(db, agora)
    base = texto_modelo(fatos)
    texto = _com_ia(SYSTEM_RESUMO, fatos, base) if usar_ia else None
    return {"texto": texto or base, "fonte": "ia" if texto else "modelo", "texto_modelo": base, "fatos": fatos}


# ---------- Perguntar ao painel ----------


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def achar_regiao(db: Session, pergunta: str) -> tuple[str | None, str | None]:
    """Região citada na pergunta (pelo nome da região ou de um bairro dela)."""
    p = f" {_norm(pergunta)} "
    for r in central.regioes(db):
        n = _norm(r.nome)
        if f" {n} " in p or f" {n}?" in p or f"zona {n}" in p or f"regiao {n}" in p:
            return r.nome, None
    for nome, reg in db.execute(select(Bairro.nome, Bairro.regiao).where(Bairro.regiao.is_not(None))):
        if _norm(nome) in p:
            return reg, nome
    return None, None


def perguntar(db: Session, pergunta: str, agora: datetime | None = None) -> dict:
    agora = agora or central.agora_utc()
    regiao, bairro = achar_regiao(db, pergunta)
    f = Filtros(regiao=[regiao]) if regiao else Filtros()
    ind = central.indicadores(db, f, agora=agora, variacao=False)["valores"]
    saude = central.saude_regioes(db, f, agora=agora)
    item = saude[0] if regiao and saude else None
    alertas = [
        central.alerta_json(a)
        for a in db.scalars(
            select(Alerta).where(Alerta.resolvido_em.is_(None), Alerta.nivel.in_(central.NIVEIS_VISIVEIS),
                                 Alerta.incidente_id.is_(None), *( [Alerta.regiao == regiao] if regiao else [] ))
            .order_by(Alerta.criado_em.desc())
            .limit(40)
        ).unique()
    ]
    alertas.sort(key=lambda a: (-regras.rank(a["nivel"]), a["estado"] != "aberto"))
    alertas = alertas[:5]

    onde = em_regiao(regiao) if regiao else "na cidade"
    partes = []
    if item:
        partes.append(f"{onde[0].upper() + onde[1:]} agora: índice {item['nota']} ({ESTADO_ROTULO[item['estado']]}), {item['motivo']}.")
    else:
        fora = [r for r in saude if r["estado"] != "normal"]
        partes.append(f"Na cidade agora: {len(fora)} região(ões) fora do normal"
                      + (f" ({', '.join(r['regiao'] for r in fora)})" if fora else "") + ".")
    a = ind["alertas"]
    partes.append(f"Alertas abertos: {a.get('critica', 0)} crítico(s), {a.get('alta', 0)} alto(s), {a.get('media', 0)} médio(s). "
                  f"Disponibilidade {_num(ind['disponibilidade'])}%, {ind['agentes_ativos']} agentes em atividade.")
    if alertas:
        partes.append(f"Mais grave: {alertas[0]['mensagem']}.")
    base = " ".join(partes)
    fatos = {"regiao": regiao, "bairro": bairro, "indicadores": ind, "regiao_saude": item,
             "alertas": [{k: x[k] for k in ("nivel", "rotulo_regra", "mensagem", "estado", "regiao")} for x in alertas],
             "agentes_por_orgao": item["agentes_por_orgao"] if item else None}
    texto = _com_ia(SYSTEM_PERGUNTA, fatos, base, pergunta)
    return {"pergunta": pergunta, "regiao": regiao, "bairro": bairro, "texto": texto or base,
            "fonte": "ia" if texto else "modelo", "indicadores": ind, "saude": item, "alertas": alertas}
