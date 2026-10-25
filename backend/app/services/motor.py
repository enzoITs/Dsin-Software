"""Motor de interpretação: todo sinal passa pelas mesmas etapas antes de chegar à tela.

1. Recebe o sinal (presença, posição, erro, métrica).
2. Liga ao cadastro pelo dispositivo_iot_id. Desconhecido vira alerta de "dispositivo não cadastrado".
3. Atualiza o estado atual: último sinal, posição dos móveis, últimas métricas.
4. Aplica as regras de detecção.
5. Calcula a criticidade com o contexto do equipamento e da região.
6. Cria ou atualiza o alerta, juntando repetições do mesmo problema num só.
7. Publica o evento para os painéis abertos e para o PROMETHEUS (depois do commit).

O verificador (a cada 30 s) cuida do que não chega como sinal: silêncio, prazos de
manutenção, agentes sem posição, regiões sem agentes e escalonamento.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from geoalchemy2 import WKTElement
from sqlalchemy import and_, func, or_, select, text, true, update
from sqlalchemy.orm import Session

from app.domain import limites, regras
from app.domain.regras import Contexto
from app.models import Agente, Alerta, Equipamento, Localizacao, PlanoManutencao, Regiao, TipoEquipamento
from app.models.enums import (
    EstadoAlerta,
    Mobilidade,
    NivelAlerta,
    Severidade,
    Situacao,
    SituacaoAgente,
    StatusManutencao,
    TipoAlerta,
    TipoPlano,
)
from app.services import central
from app.services.barramento import emitir, tocar
from app.services.equipamentos import condicao_sem_sinal

log = logging.getLogger("atalaia.motor")
R = TipoAlerta
N = NivelAlerta
E = EstadoAlerta


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def chave(regra: TipoAlerta, alvo: str, ident: Any) -> str:
    return f"{regra.value}:{alvo}:{ident}"


def chave_eq(regra: TipoAlerta, equipamento_id: int) -> str:
    return chave(regra, "eq", equipamento_id)


def _publicar_alerta(db: Session, a: Alerta, acao: str) -> None:
    emitir(db, {"tipo": "alerta", "acao": acao, "alerta": central.alerta_json(a)})
    tocar(db, a.equipamento_id)


# ---------- Contexto ----------


def manutencao_em_andamento(db: Session, e: Equipamento, hoje) -> bool:
    if e.situacao == Situacao.em_manutencao:
        return True
    return bool(db.scalar(
        select(PlanoManutencao.id).where(
            PlanoManutencao.equipamento_id == e.id, PlanoManutencao.ativo.is_(True),
            PlanoManutencao.tipo.in_([TipoPlano.agendada, TipoPlano.periodica]), PlanoManutencao.proxima_data == hoje,
        ).limit(1)
    ))


def sem_cobertura(db: Session, e: Equipamento, raio_m: int) -> bool:
    """Nenhum outro do mesmo tipo, operacional e sem problema aberto, no raio."""
    if e.tipo.mobilidade == Mobilidade.movel or e.localizacao is None or e.localizacao.geom is None:
        return False
    ponto = select(Localizacao.geom).where(Localizacao.equipamento_id == e.id).scalar_subquery()
    com_problema = select(Alerta.equipamento_id).where(
        Alerta.resolvido_em.is_(None), Alerta.equipamento_id.is_not(None),
        Alerta.tipo.in_([R.furto, R.mau_funcionamento, R.falha_silenciosa, R.sinal_degradado]),
    )
    outro = db.scalar(
        select(Equipamento.id)
        .join(Localizacao, Localizacao.equipamento_id == Equipamento.id)
        .where(
            Equipamento.tipo_id == e.tipo_id, Equipamento.id != e.id, Equipamento.situacao == Situacao.operacional,
            Equipamento.id.not_in(com_problema),
            Localizacao.geom.op("&&")(func.ST_Expand(ponto, raio_m / 90000)),
            func.ST_DWithin(func.Geography(Localizacao.geom), func.Geography(ponto), raio_m),
        )
        .limit(1)
    )
    return outro is None


def _regiao_info(db: Session, nome: str | None, cache: dict) -> Regiao | None:
    if not nome:
        return None
    regs = cache.get("regioes_obj")
    if regs is None:
        regs = cache["regioes_obj"] = {r.nome: r for r in db.scalars(select(Regiao))}
    return regs.get(nome)


def regiao_em_atencao(db: Session, nome: str | None, cache: dict, agora: datetime) -> bool:
    if not nome:
        return False
    estados = cache.get("estados_regiao")
    if estados is None:
        estados = cache["estados_regiao"] = {r["regiao"]: r["estado"] for r in central.saude_regioes(db, agora=agora)}
    return estados.get(nome, "normal") != "normal"


def contexto_equipamento(db: Session, e: Equipamento, agora: datetime, cfg: dict, cache: dict) -> Contexto:
    reg_nome = e.localizacao.regiao if e.localizacao else None
    reg = _regiao_info(db, reg_nome, cache)
    hoje = central.local(agora, cfg).date()
    return Contexto(
        situacao=e.situacao,
        manutencao_em_andamento=manutencao_em_andamento(db, e, hoje),
        sem_cobertura=sem_cobertura(db, e, cfg["cobertura_raio_m"]),
        nome_tipo=e.tipo.nome,
        regiao=reg_nome,
        regiao_em_atencao=regiao_em_atencao(db, reg_nome, cache, agora),
        horario_pico=regras.em_pico(reg.picos if reg else None, central.local(agora, cfg)),
        raio_m=cfg["cobertura_raio_m"],
    )


# ---------- Abrir, atualizar e resolver ----------


def _aberto(db: Session, k: str) -> Alerta | None:
    return db.scalar(select(Alerta).where(Alerta.chave == k, Alerta.resolvido_em.is_(None)))


def _posicao_equip(db: Session, e: Equipamento) -> tuple[float | None, float | None]:
    x, y = db.execute(
        select(func.ST_X(func.coalesce(Equipamento.posicao, Localizacao.geom)), func.ST_Y(func.coalesce(Equipamento.posicao, Localizacao.geom)))
        .select_from(Equipamento).outerjoin(Localizacao, Localizacao.equipamento_id == Equipamento.id)
        .where(Equipamento.id == e.id)
    ).one()
    return x, y


def abrir(
    db: Session,
    regra: TipoAlerta,
    k: str,
    mensagem: str,
    *,
    equipamento: Equipamento | None = None,
    regiao: str | None = None,
    lon: float | None = None,
    lat: float | None = None,
    agente_alvo_id: int | None = None,
    dispositivo: str | None = None,
    dados: dict | None = None,
    agora: datetime | None = None,
    cache: dict | None = None,
    correlacionar: bool = True,
) -> Alerta | None:
    """Cria o alerta, ou soma uma ocorrência ao que já está aberto com a mesma chave."""
    agora = agora or agora_utc()
    cache = cache if cache is not None else {}
    if cache.get("simulado"):
        dados = {**(dados or {}), "simulado": True}
    # Serializa a criação da mesma chave entre a API e o verificador.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": k})
    existente = _aberto(db, k)
    if existente is not None:
        existente.contador += 1
        existente.ultima_ocorrencia_em = agora
        existente.mensagem = mensagem
        if dados:
            existente.dados = {**(existente.dados or {}), **dados}
        db.flush()
        if cache.get("publicar_repeticoes", True):
            _publicar_alerta(db, existente, "atualizado")
        return existente

    cfg = limites.carregar(db)
    ctx = contexto_equipamento(db, equipamento, agora, cfg, cache) if equipamento is not None and regra in regras.REGRAS_COM_CONTEXTO else None
    if equipamento is not None and ctx is None and equipamento.situacao in regras.SEM_ALERTA:
        return None
    nivel, motivos = regras.decidir_nivel(regra, ctx)
    if nivel is None:
        log.info("alerta %s suprimido: %s", k, "; ".join(motivos))
        return None

    if equipamento is not None:
        if regiao is None and equipamento.localizacao is not None:
            regiao = equipamento.localizacao.regiao
        if lon is None or lat is None:
            lon, lat = _posicao_equip(db, equipamento)
    linha_de_base = bool(cache.get("linha_de_base"))
    a = Alerta(
        equipamento_id=equipamento.id if equipamento is not None else None,
        tipo=regra,
        severidade=Severidade.critico if nivel == N.critica else Severidade.atencao,
        mensagem=mensagem,
        criado_em=agora,
        chave=k,
        nivel=nivel,
        nivel_inicial=regras.NIVEL_INICIAL[regra],
        motivos_nivel=motivos,
        estado=E.reconhecido if linha_de_base else E.aberto,
        reconhecido_em=agora if linha_de_base else None,
        reconhecido_por=central.LINHA_DE_BASE if linha_de_base else None,
        contador=1,
        ultima_ocorrencia_em=agora,
        regiao=regiao,
        geom=WKTElement(f"POINT({lon} {lat})", srid=4326) if lon is not None and lat is not None else None,
        dispositivo_iot_id=dispositivo,
        agente_alvo_id=agente_alvo_id,
        dados=dados or {},
    )
    db.add(a)
    db.flush()
    _publicar_alerta(db, a, "novo")
    if not linha_de_base and a.nivel != N.baixa:
        cache.pop("estados_regiao", None)  # a região pode ter mudado de estado com este alerta
    if correlacionar and not linha_de_base and regra in regras.REGRAS_CORRELACIONAVEIS and regiao:
        _correlacionar(db, a, agora, cfg, cache)
    return a


def _correlacionar(db: Session, novo: Alerta, agora: datetime, cfg: dict, cache: dict) -> None:
    """3 ou mais equipamentos com problema na mesma região em 15 min viram um incidente."""
    janela = agora - timedelta(minutes=cfg["incidente_janela_min"])
    membros = list(db.scalars(
        select(Alerta).where(
            Alerta.regiao == novo.regiao, Alerta.tipo.in_(regras.REGRAS_CORRELACIONAVEIS),
            Alerta.resolvido_em.is_(None), Alerta.criado_em >= janela, Alerta.equipamento_id.is_not(None),
            Alerta.reconhecido_por.is_distinct_from(central.LINHA_DE_BASE),
        )
    ).unique())
    equipamentos = {m.equipamento_id for m in membros}
    if len(equipamentos) < cfg["incidente_minimo"]:
        return
    k = chave(R.incidente_correlacionado, "reg", novo.regiao)
    codigos = sorted({m.equipamento.codigo_interno for m in membros if m.equipamento})
    xs = [central.coordenadas(m) for m in membros]
    xs = [p for p in xs if p[0] is not None]
    lon = sum(p[0] for p in xs) / len(xs) if xs else None
    lat = sum(p[1] for p in xs) / len(xs) if xs else None
    msg = (f"Possível queda de energia ou de rede na região {novo.regiao}: {len(equipamentos)} equipamentos "
           f"com problema em {cfg['incidente_janela_min']} min ({', '.join(codigos[:6])}{'…' if len(codigos) > 6 else ''})")
    inc = _aberto(db, k)
    if inc is None:
        inc = abrir(db, R.incidente_correlacionado, k, msg, regiao=novo.regiao, lon=lon, lat=lat, agora=agora,
                    cache=cache, correlacionar=False, dados={"equipamentos": codigos, "membros": len(membros)})
    if inc is None:
        return
    mudaram = []
    for m in membros:
        if m.incidente_id != inc.id:
            m.incidente_id = inc.id
            if inc.estado != E.aberto and m.estado == E.aberto:
                m.estado = inc.estado
            mudaram.append(m)
    inc.mensagem = msg
    inc.contador = len(membros)
    inc.ultima_ocorrencia_em = agora
    inc.dados = {**(inc.dados or {}), "equipamentos": codigos, "membros": len(membros)}
    db.flush()
    _publicar_alerta(db, inc, "atualizado")
    for m in mudaram:
        _publicar_alerta(db, m, "atualizado")


def resolver(db: Session, a: Alerta, por: str, motivo: str, agora: datetime | None = None) -> None:
    if a.resolvido_em is not None:
        return
    agora = agora or agora_utc()
    a.resolvido_em = agora
    a.estado = E.resolvido
    a.resolvido_por = por
    a.resolucao = motivo
    db.flush()
    _publicar_alerta(db, a, "resolvido")
    if a.tipo == R.incidente_correlacionado:
        for m in db.scalars(select(Alerta).where(Alerta.incidente_id == a.id, Alerta.resolvido_em.is_(None))).unique():
            resolver(db, m, por, f"Incidente encerrado: {motivo}", agora)
    elif a.incidente_id:
        restantes = db.scalar(
            select(func.count()).select_from(Alerta).where(Alerta.incidente_id == a.incidente_id, Alerta.resolvido_em.is_(None))
        )
        if not restantes:
            inc = db.get(Alerta, a.incidente_id)
            if inc is not None:
                resolver(db, inc, "motor", "Todos os equipamentos do incidente voltaram", agora)


def resolver_chaves(db: Session, chaves: list[str], motivo: str, agora: datetime | None = None, por: str = "motor") -> int:
    if not chaves:
        return 0
    n = 0
    for a in db.scalars(select(Alerta).where(Alerta.chave.in_(chaves), Alerta.resolvido_em.is_(None))).unique():
        resolver(db, a, por, motivo, agora)
        n += 1
    return n


# ---------- Mudança de situação (Parte 1) ----------

PROBLEMAS_EQUIP = [R.furto, R.mau_funcionamento, R.falha_silenciosa, R.sinal_degradado]


def ao_mudar_situacao(db: Session, e: Equipamento, anterior: Situacao, nova: Situacao, motivo: str, usuario: str,
                      agora: datetime) -> list[str]:
    """Regras disparadas por mudança de situação. Devolve as ações para a resposta da API."""
    acoes: list[str] = []
    tocar(db, e.id)
    if nova == Situacao.furtado:
        a = abrir(db, R.furto, chave_eq(R.furto, e.id), f"{e.codigo_interno} furtado: {motivo}", equipamento=e,
                  agora=agora, dados={"origem": "situacao", "usuario": usuario})
        if a is not None:
            acoes += ["alerta_critico_gerado", "orgao_notificado"]
    if nova == Situacao.mau_funcionamento:
        a = abrir(db, R.mau_funcionamento, chave_eq(R.mau_funcionamento, e.id),
                  f"{e.codigo_interno}: mau funcionamento informado por {usuario}: {motivo}", equipamento=e, agora=agora,
                  dados={"origem": "situacao", "usuario": usuario})
        if a is not None:
            acoes.append(f"alerta_{a.nivel.value}_gerado")
    if anterior == Situacao.furtado:
        resolver_chaves(db, [chave_eq(R.furto, e.id)], f"Situação mudou para {nova.value}", agora, usuario)
    if nova == Situacao.operacional:
        resolver_chaves(db, [chave_eq(r, e.id) for r in PROBLEMAS_EQUIP], "Situação voltou a operacional", agora, usuario)
    if nova in (Situacao.desativado, Situacao.nao_instalado):
        abertos = list(db.scalars(select(Alerta.chave).where(Alerta.equipamento_id == e.id, Alerta.resolvido_em.is_(None))))
        resolver_chaves(db, abertos, "Equipamento desativado", agora, usuario)
    return acoes


# ---------- Ingestão de sinais ----------

METRICAS = {
    # métrica: (limite em limites.py, descrição)
    "qualidade": ("camera_qualidade_min_pct", "queda de qualidade de imagem"),
    "bateria": ("bateria_min_pct", "bateria baixa"),
}


@dataclass
class Sinal:
    dispositivo_iot_id: str
    em: datetime | None = None
    tipo: str = "presenca"   # presenca, posicao, erro, metrica
    lon: float | None = None
    lat: float | None = None
    valores: dict[str, Any] = field(default_factory=dict)


def distancia_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def processar_sinais(db: Session, sinais: list[Sinal], agora: datetime | None = None, cache: dict | None = None) -> dict:
    agora = agora or agora_utc()
    cache = cache if cache is not None else {}
    cfg = limites.carregar(db)
    if not sinais:
        return {"recebidos": 0, "desconhecidos": 0, "alertas_resolvidos": 0, "alertas": []}

    # 2. Liga ao cadastro
    disp = list({s.dispositivo_iot_id for s in sinais})
    linhas = {
        r.dispositivo_iot_id: r
        for r in db.execute(
            select(Equipamento.id, Equipamento.dispositivo_iot_id, Equipamento.codigo_interno, Equipamento.situacao,
                   TipoEquipamento.mobilidade, func.ST_X(Localizacao.geom).label("x"), func.ST_Y(Localizacao.geom).label("y"))
            .join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
            .outerjoin(Localizacao, Localizacao.equipamento_id == Equipamento.id)
            .where(Equipamento.dispositivo_iot_id.in_(disp))
        )
    }
    alertas: list[Alerta] = []
    desconhecidos = [s for s in sinais if s.dispositivo_iot_id not in linhas]
    for s in {d.dispositivo_iot_id: d for d in desconhecidos}.values():
        a = abrir(db, R.dispositivo_nao_cadastrado, chave(R.dispositivo_nao_cadastrado, "dev", s.dispositivo_iot_id),
                  f"Sinal do dispositivo {s.dispositivo_iot_id}, que não existe no inventário", lon=s.lon, lat=s.lat,
                  dispositivo=s.dispositivo_iot_id, agora=agora, cache={**cache, "publicar_repeticoes": False},
                  dados={"ultimo_tipo": s.tipo})
        if a is not None:
            alertas.append(a)
    conhecidos = [s for s in sinais if s.dispositivo_iot_id in linhas]

    # 3. Estado atual
    ultimo: dict[int, datetime] = {}
    posicoes: dict[int, tuple[float, float, datetime]] = {}
    metricas: dict[int, dict] = {}
    for s in conhecidos:
        eid = linhas[s.dispositivo_iot_id].id
        em = s.em or agora
        ultimo[eid] = max(em, ultimo.get(eid, em))
        if s.lon is not None and s.lat is not None:
            posicoes[eid] = (s.lon, s.lat, em)
        if s.valores:
            metricas.setdefault(eid, {}).update({k: v for k, v in s.valores.items() if isinstance(v, (int, float, str, bool))})
    conn = db.connection()
    if ultimo:
        conn.execute(text("""
            UPDATE equipamento e SET ultimo_sinal_em = v.em
            FROM unnest(CAST(:ids AS int[]), CAST(:ems AS timestamptz[])) AS v(id, em)
            WHERE e.id = v.id AND (e.ultimo_sinal_em IS NULL OR e.ultimo_sinal_em < v.em)
        """), {"ids": sorted(ultimo), "ems": [ultimo[i] for i in sorted(ultimo)]})
    if posicoes:
        posicoes = dict(sorted(posicoes.items()))
        conn.execute(text("""
            UPDATE equipamento e SET posicao = ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326), posicao_em = v.em
            FROM unnest(CAST(:ids AS int[]), CAST(:lons AS float8[]), CAST(:lats AS float8[]), CAST(:ems AS timestamptz[]))
                 AS v(id, lon, lat, em)
            WHERE e.id = v.id
        """), {"ids": list(posicoes), "lons": [p[0] for p in posicoes.values()],
               "lats": [p[1] for p in posicoes.values()], "ems": [p[2] for p in posicoes.values()]})
    if metricas:
        import json

        metricas = dict(sorted(metricas.items()))
        conn.execute(text("""
            UPDATE equipamento e SET metricas = COALESCE(e.metricas, '{}'::jsonb) || v.m::jsonb, metricas_em = :agora
            FROM unnest(CAST(:ids AS int[]), CAST(:ms AS text[])) AS v(id, m)
            WHERE e.id = v.id
        """), {"ids": list(metricas), "ms": [json.dumps(m) for m in metricas.values()], "agora": agora})

    # 4-6. Regras
    resolvidos = 0
    # Presença: o sinal voltou
    resolvidos += resolver_chaves(
        db, _abertos_entre(db, [chave_eq(R.falha_silenciosa, eid) for eid in ultimo]), "Sinal voltou", agora)

    def equip(eid: int) -> Equipamento:
        return db.get(Equipamento, eid)

    for s in conhecidos:
        ln = linhas[s.dispositivo_iot_id]
        if s.tipo == "erro":
            detalhe = s.valores.get("codigo") or s.valores.get("erro") or s.valores.get("mensagem") or "sem código"
            a = abrir(db, R.mau_funcionamento, chave_eq(R.mau_funcionamento, ln.id),
                      f"{ln.codigo_interno}: erro informado pelo dispositivo ({detalhe})", equipamento=equip(ln.id),
                      agora=agora, cache=cache, dados={"origem": "sinal", "erro": str(detalhe), **_sim(s)})
            if a is not None:
                alertas.append(a)
        if s.lon is not None and s.lat is not None and Mobilidade(ln.mobilidade) == Mobilidade.fixo and ln.x is not None:
            dist = distancia_m(ln.x, ln.y, s.lon, s.lat)
            k = chave_eq(R.furto, ln.id)
            if dist > cfg["furto_distancia_m"]:
                a = abrir(db, R.furto, k, f"{ln.codigo_interno}: possível furto, deslocado {dist:.0f} m do ponto de instalação",
                          equipamento=equip(ln.id), lon=s.lon, lat=s.lat, agora=agora, cache=cache,
                          dados={"origem": "posicao", "distancia_m": round(dist), **_sim(s)})
                if a is not None:
                    alertas.append(a)
            else:
                aberto = _aberto(db, k)
                if aberto is not None and (aberto.dados or {}).get("origem") == "posicao":
                    resolver(db, aberto, "motor", "Equipamento de volta ao ponto de instalação", agora)
                    resolvidos += 1
        for metrica, valor in s.valores.items():
            if metrica not in METRICAS or not isinstance(valor, (int, float)):
                continue
            limite_cfg, descricao = METRICAS[metrica]
            k = chave_eq(R.sinal_degradado, ln.id)
            if valor < cfg[limite_cfg]:
                a = abrir(db, R.sinal_degradado, k, f"{ln.codigo_interno}: {descricao} ({valor:g}%, mínimo {cfg[limite_cfg]}%)",
                          equipamento=equip(ln.id), agora=agora, cache={**cache, "publicar_repeticoes": False},
                          dados={"metrica": metrica, "valor": valor, **_sim(s)})
                if a is not None:
                    alertas.append(a)
            else:
                aberto = _aberto_cache(db, k, cache)
                if aberto is not None and (aberto.dados or {}).get("metrica") == metrica:
                    resolver(db, aberto, "motor", f"{descricao.capitalize()} normalizada ({valor:g}%)", agora)
                    resolvidos += 1

    # 7. Posições dos móveis vão direto para o mapa
    mob = {l.id: Mobilidade(l.mobilidade) for l in linhas.values()}
    moveis = [[eid, round(p[0], 6), round(p[1], 6)] for eid, p in posicoes.items() if mob[eid] == Mobilidade.movel]
    if moveis:
        emitir(db, {"tipo": "posicoes", "equipamentos": moveis})
    return {
        "recebidos": len(conhecidos),
        "desconhecidos": len(desconhecidos),
        "alertas_resolvidos": resolvidos,
        "alertas": [a.id for a in alertas],
    }


def _sim(s: Sinal) -> dict:
    return {"simulado": True} if s.valores.get("simulado") else {}


def _abertos_entre(db: Session, chaves: list[str]) -> list[str]:
    if not chaves:
        return []
    return list(db.scalars(select(Alerta.chave).where(Alerta.chave.in_(chaves), Alerta.resolvido_em.is_(None))))


def _aberto_cache(db: Session, k: str, cache: dict) -> Alerta | None:
    """Evita uma consulta por sinal de métrica normal: carrega as chaves abertas de sinal degradado uma vez."""
    if "degradados" not in cache:
        cache["degradados"] = set(db.scalars(select(Alerta.chave).where(
            Alerta.tipo == R.sinal_degradado, Alerta.resolvido_em.is_(None))))
    if k not in cache["degradados"]:
        return None
    return _aberto(db, k)


# ---------- Posição dos agentes ----------


def processar_posicoes_agentes(db: Session, itens: list[dict], agora: datetime | None = None) -> dict:
    agora = agora or agora_utc()
    if not itens:
        return {"recebidos": 0}
    ids, lons, lats, ems = [], [], [], []
    por_matricula = {m: i for m, i in db.execute(select(Agente.matricula, Agente.id).where(
        Agente.matricula.in_([x["matricula"] for x in itens if x.get("matricula")])))}
    for x in itens:
        aid = x.get("agente_id") or por_matricula.get(x.get("matricula"))
        if aid is None or x.get("lon") is None or x.get("lat") is None:
            continue
        ids.append(aid)
        lons.append(float(x["lon"]))
        lats.append(float(x["lat"]))
        ems.append(x.get("em") or agora)
    if not ids:
        return {"recebidos": 0}
    db.connection().execute(text("""
        UPDATE agente a SET posicao = v.p, posicao_em = v.em,
            regiao = COALESCE((SELECT r.nome FROM regiao r WHERE ST_Contains(r.geom, v.p) LIMIT 1), a.regiao)
        FROM (SELECT id, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS p, em
              FROM unnest(CAST(:ids AS int[]), CAST(:lons AS float8[]), CAST(:lats AS float8[]), CAST(:ems AS timestamptz[]))
                   AS t(id, lon, lat, em)) v
        WHERE a.id = v.id
    """), {"ids": ids, "lons": lons, "lats": lats, "ems": ems})
    resolvidos = resolver_chaves(
        db, _abertos_entre(db, [chave(R.agente_sem_posicao, "ag", i) for i in ids]), "Posição atualizada", agora)
    emitir(db, {"tipo": "posicoes", "agentes": [[i, round(x, 6), round(y, 6)] for i, x, y in zip(ids, lons, lats)]})
    return {"recebidos": len(ids), "alertas_resolvidos": resolvidos}


# ---------- Verificador periódico ----------


def verificar_equipamentos(db: Session, ids: list[int] | None, agora: datetime | None = None, cache: dict | None = None) -> dict:
    """Falha silenciosa e prazos de manutenção, para alguns equipamentos ou para todos."""
    agora = agora or agora_utc()
    cache = cache if cache is not None else {}
    cfg = limites.carregar(db)
    stats = {"silencio_novos": 0, "silencio_resolvidos": 0, "manutencao_novos": 0, "manutencao_resolvidos": 0}

    def alvo(col):
        return col.in_(ids) if ids is not None else true()

    # Falha silenciosa
    silenciosos = set(db.scalars(
        select(Equipamento.id).join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
        .where(condicao_sem_sinal(cfg["silencio_fator"]), alvo(Equipamento.id))
    ))
    abertos = dict(db.execute(
        select(Alerta.equipamento_id, Alerta.id).where(
            Alerta.tipo == R.falha_silenciosa, Alerta.resolvido_em.is_(None), alvo(Alerta.equipamento_id))
    ).all())
    for eid in sorted(silenciosos - set(abertos)):
        e = db.get(Equipamento, eid)
        a = abrir(db, R.falha_silenciosa, chave_eq(R.falha_silenciosa, eid),
                  f"{e.codigo_interno}: possível falha silenciosa, operacional mas sem sinal há mais de "
                  f"{e.tipo.intervalo_sinal_esperado_min * cfg['silencio_fator']} min", equipamento=e, agora=agora, cache=cache)
        stats["silencio_novos"] += a is not None
    for eid, aid in abertos.items():
        if eid not in silenciosos:
            a = db.get(Alerta, aid)
            e = a.equipamento
            motivo = "Sinal voltou" if e and e.situacao == Situacao.operacional else "Equipamento deixou de estar operacional"
            resolver(db, a, "motor", motivo, agora)
            stats["silencio_resolvidos"] += 1

    # Manutenção vencida (média) e próxima (baixa): em lote, sem contexto.
    for regra, status, nivel in (
        (R.manutencao_vencida, StatusManutencao.vencida, N.media),
        (R.manutencao_proxima, StatusManutencao.proxima, N.baixa),
    ):
        quer = dict(db.execute(
            select(Equipamento.id, Equipamento.codigo_interno).where(
                Equipamento.status_manutencao == status,
                Equipamento.situacao.not_in([Situacao.desativado, Situacao.nao_instalado]), alvo(Equipamento.id))
        ).all())
        tem = dict(db.execute(
            select(Alerta.equipamento_id, Alerta.id).where(
                Alerta.tipo == regra, Alerta.resolvido_em.is_(None), alvo(Alerta.equipamento_id))
        ).all())
        novos = [eid for eid in quer if eid not in tem]
        if novos:
            stats["manutencao_novos"] += _inserir_manutencao(db, regra, nivel, novos, quer, agora, cache)
        sair = [aid for eid, aid in tem.items() if eid not in quer]
        if sair:
            stats["manutencao_resolvidos"] += len(sair)
            db.execute(update(Alerta).where(Alerta.id.in_(sair)).values(
                resolvido_em=agora, estado=E.resolvido, resolvido_por="motor", resolucao="Manutenção em dia"))
            if len(sair) <= 50:
                for eid in [eid for eid, aid in tem.items() if aid in set(sair)]:
                    tocar(db, eid)
    return stats


def _inserir_manutencao(db: Session, regra: TipoAlerta, nivel: NivelAlerta, ids: list[int], codigos: dict,
                        agora: datetime, cache: dict) -> int:
    cfg = limites.carregar(db)
    hoje = central.local(agora, cfg).date()
    datas = dict(db.execute(
        select(PlanoManutencao.equipamento_id, func.min(PlanoManutencao.proxima_data))
        .where(PlanoManutencao.equipamento_id.in_(ids), PlanoManutencao.ativo.is_(True)).group_by(PlanoManutencao.equipamento_id)
    ).all())
    locs = {eid: (reg, g) for eid, reg, g in db.execute(
        select(Localizacao.equipamento_id, Localizacao.regiao, Localizacao.geom).where(Localizacao.equipamento_id.in_(ids)))}
    linha_de_base = bool(cache.get("linha_de_base"))
    linhas = []
    for eid in ids:
        d = datas.get(eid)
        if regra == R.manutencao_vencida:
            msg = f"{codigos[eid]}: manutenção vencida há {(hoje - d).days if d else '?'} dia(s)"
        else:
            msg = f"{codigos[eid]}: manutenção em {(d - hoje).days if d else '?'} dia(s)"
        reg, g = locs.get(eid, (None, None))
        linhas.append({
            "equipamento_id": eid, "tipo": regra, "severidade": Severidade.atencao, "mensagem": msg, "criado_em": agora,
            "chave": chave_eq(regra, eid), "nivel": nivel, "nivel_inicial": nivel, "motivos_nivel": [],
            "estado": E.reconhecido if linha_de_base else E.aberto, "contador": 1, "ultima_ocorrencia_em": agora,
            "regiao": reg, "geom": g, "dados": {"data_plano": d.isoformat() if d else None},
            "reconhecido_em": agora if linha_de_base else None,
            "reconhecido_por": central.LINHA_DE_BASE if linha_de_base else None,
        })
    db.execute(Alerta.__table__.insert(), linhas)
    if len(ids) <= 50:
        for eid in ids:
            tocar(db, eid)
        if regra == R.manutencao_vencida and not linha_de_base:
            for a in db.scalars(select(Alerta).where(Alerta.chave.in_([l["chave"] for l in linhas]), Alerta.resolvido_em.is_(None))).unique():
                _publicar_alerta(db, a, "novo")
    else:
        emitir(db, {"tipo": "recarregar", "motivo": f"{len(ids)} alertas de {regra.value}"})
    return len(ids)


def verificar_agentes(db: Session, agora: datetime, cache: dict) -> dict:
    cfg = limites.carregar(db)
    limite = agora - timedelta(minutes=cfg["agente_sem_posicao_min"])
    stats = {"agentes_sem_posicao": 0, "regioes_descobertas": 0}

    # Agente sem posição
    sem_pos = dict(db.execute(
        select(Agente.id, Agente.nome).where(
            Agente.situacao == SituacaoAgente.em_atividade,
            or_(Agente.posicao_em.is_(None), Agente.posicao_em < limite))
    ).all())
    abertos = dict(db.execute(select(Alerta.agente_alvo_id, Alerta.chave).where(
        Alerta.tipo == R.agente_sem_posicao, Alerta.resolvido_em.is_(None))).all())
    for aid, nome in sem_pos.items():
        if aid not in abertos:
            ag = db.get(Agente, aid)
            x = y = None
            if ag.posicao is not None:
                from geoalchemy2.shape import to_shape

                p = to_shape(ag.posicao)
                x, y = p.x, p.y
            abrir(db, R.agente_sem_posicao, chave(R.agente_sem_posicao, "ag", aid),
                  f"{nome} ({ag.orgao.sigla}) em atividade sem atualizar posição há mais de {cfg['agente_sem_posicao_min']} min",
                  regiao=ag.regiao, lon=x, lat=y, agente_alvo_id=aid, agora=agora, cache=cache)
            stats["agentes_sem_posicao"] += 1
    sair = [k for aid, k in abertos.items() if aid not in sem_pos]
    resolver_chaves(db, sair, "Agente voltou a enviar posição ou saiu de atividade", agora)

    # Região descoberta
    com_agente = set(db.scalars(select(Agente.regiao).where(
        Agente.situacao == SituacaoAgente.em_atividade, Agente.posicao_em >= limite, Agente.regiao.is_not(None)).distinct()))
    for reg in db.scalars(select(Regiao)):
        k = chave(R.regiao_descoberta, "reg", reg.nome)
        if reg.nome not in com_agente:
            c = db.execute(select(func.ST_X(func.ST_PointOnSurface(Regiao.geom)), func.ST_Y(func.ST_PointOnSurface(Regiao.geom)))
                           .where(Regiao.id == reg.id)).one()
            if _aberto(db, k) is None:
                abrir(db, R.regiao_descoberta, k, f"Região {reg.nome} sem nenhum agente em atividade",
                      regiao=reg.nome, lon=c[0], lat=c[1], agora=agora, cache=cache)
                stats["regioes_descobertas"] += 1
        else:
            resolver_chaves(db, [k], "Agente em atividade na região", agora)
    return stats


def escalonar(db: Session, agora: datetime) -> dict:
    """Crítico não reconhecido em 2 min volta a tocar; alto não reconhecido em 10 min vira crítico."""
    cfg = limites.carregar(db)
    stats = {"tocados": 0, "escalonados": 0}
    base = and_(Alerta.resolvido_em.is_(None), Alerta.estado == E.aberto, Alerta.incidente_id.is_(None),
                or_(Alerta.silenciado_ate.is_(None), Alerta.silenciado_ate < agora))
    for a in db.scalars(select(Alerta).where(base, Alerta.nivel == N.alta,
                                             Alerta.criado_em <= agora - timedelta(minutes=cfg["escalonar_alto_min"]))).unique():
        a.motivos_nivel = [*(a.motivos_nivel or []), f"Alta → Crítica: não reconhecido em {cfg['escalonar_alto_min']} min"]
        a.nivel = N.critica
        a.severidade = Severidade.critico
        a.tocado_em = agora
        db.flush()
        _publicar_alerta(db, a, "atualizado")
        emitir(db, {"tipo": "alerta", "acao": "tocar", "alerta": central.alerta_json(a)})
        stats["escalonados"] += 1
    limite = agora - timedelta(minutes=cfg["escalonar_critico_min"])
    for a in db.scalars(select(Alerta).where(base, Alerta.nivel == N.critica,
                                             func.coalesce(Alerta.tocado_em, Alerta.criado_em) <= limite)).unique():
        a.tocado_em = agora
        emitir(db, {"tipo": "alerta", "acao": "tocar", "alerta": central.alerta_json(a)})
        stats["tocados"] += 1
    return stats


def verificar(db: Session, agora: datetime | None = None, linha_de_base: bool = False) -> dict:
    agora = agora or agora_utc()
    cache: dict = {"linha_de_base": linha_de_base}
    stats = verificar_equipamentos(db, None, agora, cache)
    stats.update(verificar_agentes(db, agora, cache))
    if not linha_de_base:
        stats.update(escalonar(db, agora))
    return stats
