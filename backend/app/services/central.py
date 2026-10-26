"""Consultas da Central de Operações (Parte 2).

Tudo que a tela mostra é calculado aqui, na API, e respeita os mesmos filtros:
feições do mapa, indicadores do topo, índice de saúde das regiões, fila de manutenção,
agentes mais próximos e a linha do tempo.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from geoalchemy2.shape import to_shape
from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.domain import disponibilidade, limites, regras
from app.models import (
    Agente,
    Alerta,
    Equipamento,
    HistoricoSituacao,
    Instantaneo,
    Localizacao,
    OrdemServico,
    Orgao,
    PlanoManutencao,
    Regiao,
    TipoEquipamento,
)
from app.models.enums import (
    EstadoAlerta,
    Mobilidade,
    NivelAlerta,
    Situacao,
    SituacaoAgente,
    StatusManutencao,
    StatusOS,
    TipoAlerta,
    TipoPlano,
)
from app.services import equipamentos as svc
from app.services.equipamentos import Filtros, aplicar_filtros, area_wkt, posicao_atual

S = Situacao
NIVEIS_VISIVEIS = [NivelAlerta.critica, NivelAlerta.alta, NivelAlerta.media]
LINHA_DE_BASE = "Pendência anterior à central"

# Último estado calculado de cada região (sem filtros). O motor usa para "região já em atenção".
ESTADO_REGIOES: dict[str, dict] = {}


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def local(dt: datetime, cfg: dict) -> datetime:
    return dt.astimezone(ZoneInfo(cfg["fuso"]))


def _rank_sql():
    return case(
        (Alerta.nivel == NivelAlerta.critica, 4),
        (Alerta.nivel == NivelAlerta.alta, 3),
        (Alerta.nivel == NivelAlerta.media, 2),
        else_=1,
    )


def forma(categoria: str, mobilidade: Mobilidade | str) -> str:
    """c = círculo (fiscalização), q = quadrado (monitoramento), t = triângulo (veículos)."""
    if Mobilidade(mobilidade) == Mobilidade.movel:
        return "t"
    return "q" if categoria.lower().startswith("monitor") else "c"


def gravidade(situacao: Situacao, nivel: int, status_manut: StatusManutencao) -> int:
    """Cor do ponto: 4 vermelho, 3 laranja, 2 amarelo, 1 verde, 0 cinza. O pior entre situação e alerta."""
    if situacao == S.furtado or nivel >= 4:
        return 4
    if situacao == S.mau_funcionamento or nivel == 3:
        return 3
    if situacao in (S.desativado, S.nao_instalado):
        return 0
    if situacao == S.em_manutencao or nivel == 2 or status_manut in (StatusManutencao.proxima, StatusManutencao.vencida):
        return 2
    return 1


# ---------- Mapa ----------


def feicoes_equipamentos(db: Session, f: Filtros | None = None, restrito: int | None = None,
                         ids: list[int] | None = None, agora: datetime | None = None) -> list[dict]:
    agora = agora or agora_utc()
    cfg = limites.carregar(db)
    niveis = (
        select(Alerta.equipamento_id.label("eid"), func.max(_rank_sql()).label("n"))
        .where(Alerta.resolvido_em.is_(None), Alerta.nivel != NivelAlerta.baixa, Alerta.equipamento_id.is_not(None))
        .group_by(Alerta.equipamento_id)
        .subquery()
    )
    pt = posicao_atual()
    stmt = aplicar_filtros(
        select(
            Equipamento.id, Equipamento.codigo_interno, TipoEquipamento.prefixo, TipoEquipamento.categoria,
            TipoEquipamento.mobilidade, Equipamento.situacao, Equipamento.status_manutencao,
            Equipamento.dispositivo_iot_id.is_not(None), func.coalesce(Equipamento.ultimo_sinal_em, Equipamento.criado_em),
            TipoEquipamento.intervalo_sinal_esperado_min, Orgao.sigla, Localizacao.regiao,
            func.ST_X(pt), func.ST_Y(pt), niveis.c.n,
        ),
        f or Filtros(), restrito,
    ).join(Orgao, Orgao.id == Equipamento.orgao_id).outerjoin(niveis, niveis.c.eid == Equipamento.id).where(pt.is_not(None))
    if ids is not None:
        stmt = stmt.where(Equipamento.id.in_(ids))
    fator = cfg["dado_velho_fator"]
    saida = []
    for (eid, cod, pref, cat, mob, sit, manut, tem_iot, sinal, intervalo, sigla, reg, x, y, n) in db.execute(stmt):
        n = n or 0
        velho = bool(tem_iot and sit == S.operacional and (sinal is None or agora - sinal > timedelta(minutes=intervalo * fator)))
        saida.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(x, 6), round(y, 6)]},
            "properties": {
                "i": eid, "c": cod, "p": pref, "f": forma(cat, mob), "s": sit.value, "n": n,
                "g": gravidade(sit, n, manut), "v": int(velho), "m": int(Mobilidade(mob) == Mobilidade.movel),
                "o": sigla, "r": reg,
            },
        })
    return saida


def _filtro_agentes(stmt, f: Filtros | None, restrito: int | None):
    if restrito is not None:
        stmt = stmt.where(Agente.orgao_id == restrito)
    if f is not None:
        if f.orgao_id:
            stmt = stmt.where(Agente.orgao_id.in_(f.orgao_id))
        if f.regiao:
            stmt = stmt.where(Agente.regiao.in_(f.regiao))
        if f.area:
            stmt = stmt.where(func.ST_Within(Agente.posicao, area_wkt(f.area)))
    return stmt


def feicoes_agentes(db: Session, f: Filtros | None = None, restrito: int | None = None,
                    ids: list[int] | None = None, agora: datetime | None = None) -> list[dict]:
    agora = agora or agora_utc()
    atendendo = (
        select(Alerta.agente_id.label("aid"), func.max(Alerta.id).label("alerta"))
        .where(Alerta.resolvido_em.is_(None), Alerta.agente_id.is_not(None))
        .group_by(Alerta.agente_id)
        .subquery()
    )
    stmt = _filtro_agentes(
        select(Agente.id, Agente.nome, Agente.equipe, Orgao.sigla, Agente.regiao, Agente.posicao_em,
               func.ST_X(Agente.posicao), func.ST_Y(Agente.posicao), atendendo.c.alerta)
        .join(Orgao, Orgao.id == Agente.orgao_id)
        .outerjoin(atendendo, atendendo.c.aid == Agente.id)
        .where(Agente.situacao == SituacaoAgente.em_atividade, Agente.posicao.is_not(None)),
        f, restrito,
    )
    if ids is not None:
        stmt = stmt.where(Agente.id.in_(ids))
    return [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(x, 6), round(y, 6)]},
            "properties": {"i": aid, "nome": nome, "eq": equipe, "o": sigla, "r": reg,
                           "pe": pos_em.isoformat() if pos_em else None, "at": alerta},
        }
        for aid, nome, equipe, sigla, reg, pos_em, x, y, alerta in db.execute(stmt)
    ]


def regioes_geojson(db: Session) -> dict:
    linhas = db.execute(select(Regiao.id, Regiao.nome, func.ST_AsGeoJSON(func.ST_Simplify(Regiao.geom, 0.0003)))).all()
    import json

    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "id": i, "properties": {"nome": n}, "geometry": json.loads(g)} for i, n, g in linhas if g
        ],
    }


# ---------- Alertas ----------


def _alerta_casa_filtros(f: Filtros | None, restrito: int | None):
    """Condição para alertas respeitarem os filtros: os de equipamento seguem o filtro de equipamento;
    os de região, agente ou dispositivo entram quando não há filtro específico de equipamento."""
    f = f or Filtros()
    eq_ids = aplicar_filtros(select(Equipamento.id), f, restrito)
    cond_sem_equip = Alerta.equipamento_id.is_(None)
    if f.por_equipamento:
        cond_sem_equip = literal(False)
    else:
        if f.regiao:
            cond_sem_equip = and_(cond_sem_equip, Alerta.regiao.in_(f.regiao))
        if f.orgao_id or restrito is not None:
            orgaos = f.orgao_id or [restrito]
            cond_sem_equip = and_(cond_sem_equip, or_(
                Alerta.agente_alvo_id.is_(None),
                Alerta.agente_alvo_id.in_(select(Agente.id).where(Agente.orgao_id.in_(orgaos))),
            ))
        if f.area:
            cond_sem_equip = and_(cond_sem_equip, func.ST_Within(Alerta.geom, area_wkt(f.area)))
    if f == Filtros() and restrito is None:
        return literal(True)
    return or_(Alerta.equipamento_id.in_(eq_ids), cond_sem_equip)


def contar_alertas_abertos(db: Session, f: Filtros | None, restrito: int | None) -> dict[str, int]:
    linhas = db.execute(
        select(Alerta.nivel, func.count())
        .where(Alerta.resolvido_em.is_(None), Alerta.nivel.in_(NIVEIS_VISIVEIS), _alerta_casa_filtros(f, restrito))
        .group_by(Alerta.nivel)
    ).all()
    d = {n.value: 0 for n in NIVEIS_VISIVEIS}
    d.update({n.value: c for n, c in linhas})
    return d


def _alertas_abertos_em(db: Session, T: datetime, f: Filtros | None, restrito: int | None) -> dict[str, int]:
    linhas = db.execute(
        select(Alerta.nivel, func.count())
        .where(Alerta.criado_em <= T, or_(Alerta.resolvido_em.is_(None), Alerta.resolvido_em > T),
               Alerta.nivel.in_(NIVEIS_VISIVEIS), _alerta_casa_filtros(f, restrito))
        .group_by(Alerta.nivel)
    ).all()
    d = {n.value: 0 for n in NIVEIS_VISIVEIS}
    d.update({n.value: c for n, c in linhas})
    return d


# ---------- Indicadores ----------


def _situacao_em(T: datetime):
    """Subconsulta: para cada equipamento que mudou depois de T, a situação que ele tinha em T."""
    H = HistoricoSituacao
    return (
        select(H.equipamento_id.label("eid"), H.situacao_anterior.label("antes"))
        .where(H.em > T)
        .ext(distinct_on(H.equipamento_id))
        .order_by(H.equipamento_id, H.em.asc())
        .subquery()
    )


def contagem_situacao(db: Session, f: Filtros | None, restrito: int | None, T: datetime | None = None) -> dict[Situacao, int]:
    if T is None:
        stmt = aplicar_filtros(select(Equipamento.situacao, func.count()), f or Filtros(), restrito).group_by(Equipamento.situacao)
        return dict(db.execute(stmt).all())
    sub = _situacao_em(T)
    sit = case((sub.c.eid.is_not(None), func.coalesce(sub.c.antes, S.nao_instalado)), else_=Equipamento.situacao)
    stmt = (
        aplicar_filtros(select(sit, func.count()), f or Filtros(), restrito)
        .outerjoin(sub, sub.c.eid == Equipamento.id)
        .where(Equipamento.criado_em <= T)
        .group_by(sit)
    )
    return {Situacao(k): v for k, v in db.execute(stmt).all()}


def _agentes_ativos(db: Session, f: Filtros | None, restrito: int | None, agora: datetime, cfg: dict) -> int:
    limite = agora - timedelta(minutes=cfg["agente_sem_posicao_min"])
    stmt = _filtro_agentes(
        select(func.count()).select_from(Agente).where(
            Agente.situacao == SituacaoAgente.em_atividade, Agente.posicao_em >= limite),
        f, restrito,
    )
    return db.scalar(stmt) or 0


def _manutencoes_vencidas(db: Session, f: Filtros | None, restrito: int | None, hoje: date) -> int:
    eq_ids = aplicar_filtros(select(Equipamento.id), f or Filtros(), restrito).where(
        Equipamento.situacao.not_in([S.desativado, S.nao_instalado]))
    return db.scalar(
        select(func.count()).select_from(PlanoManutencao).where(
            PlanoManutencao.ativo.is_(True), PlanoManutencao.proxima_data < hoje,
            PlanoManutencao.equipamento_id.in_(eq_ids))
    ) or 0


def _tempo_reconhecer(db: Session, f: Filtros | None, restrito: int | None, fim: datetime) -> float | None:
    v = db.scalar(
        select(func.avg(func.extract("epoch", Alerta.reconhecido_em - Alerta.criado_em))).where(
            Alerta.reconhecido_em > fim - timedelta(hours=1), Alerta.reconhecido_em <= fim,
            Alerta.reconhecido_por != LINHA_DE_BASE, _alerta_casa_filtros(f, restrito))
    )
    return round(float(v), 1) if v is not None else None


def _base_indicadores(contagem: dict[Situacao, int]) -> dict:
    d = disponibilidade.calcular(contagem)
    return {
        "total": sum(contagem.values()),
        "operacionais": contagem.get(S.operacional, 0),
        "indisponiveis": d["indisponiveis"],
        "disponibilidade": round(d["disponibilidade"] * 100, 2) if d["disponibilidade"] is not None else None,
    }


def _instantaneo_perto(db: Session, T: datetime, tolerancia_min: int = 5) -> Instantaneo | None:
    return db.scalar(
        select(Instantaneo)
        .where(Instantaneo.em.between(T - timedelta(minutes=tolerancia_min), T + timedelta(minutes=tolerancia_min)))
        .order_by(func.abs(func.extract("epoch", Instantaneo.em - T)))
        .limit(1)
    )


def indicadores(db: Session, f: Filtros | None = None, restrito: int | None = None, agora: datetime | None = None,
                variacao: bool = True) -> dict:
    agora = agora or agora_utc()
    cfg = limites.carregar(db)
    f = f or Filtros()
    hoje = local(agora, cfg).date()
    valores = {
        **_base_indicadores(contagem_situacao(db, f, restrito)),
        "agentes_ativos": _agentes_ativos(db, f, restrito, agora, cfg),
        "alertas": contar_alertas_abertos(db, f, restrito),
        "sem_sinal": db.scalar(aplicar_filtros(select(func.count()), Filtros(**{**f.__dict__, "sem_sinal": True}), restrito)) or 0,
        "manutencoes_vencidas": _manutencoes_vencidas(db, f, restrito, hoje),
        "tempo_reconhecer_s": _tempo_reconhecer(db, f, restrito, agora),
    }
    resp = {"em": agora.isoformat(), "valores": valores, "variacao": {}, "filtros": f.como_dict()}
    if not variacao:
        return resp

    T = agora - timedelta(hours=1)
    antes = {
        **_base_indicadores(contagem_situacao(db, f, restrito, T)),
        "alertas": _alertas_abertos_em(db, T, f, restrito),
        "tempo_reconhecer_s": _tempo_reconhecer(db, f, restrito, T),
    }
    sem_filtro = f == Filtros() and restrito is None
    foto = _instantaneo_perto(db, T) if sem_filtro else None
    if foto:
        for k in ("agentes_ativos", "sem_sinal", "manutencoes_vencidas"):
            antes[k] = foto.indicadores.get(k)
    var: dict = {}
    for k, v in valores.items():
        a = antes.get(k)
        if isinstance(v, dict) and isinstance(a, dict):
            var[k] = {n: v[n] - a.get(n, 0) for n in v}
        elif isinstance(v, (int, float)) and isinstance(a, (int, float)):
            var[k] = round(v - a, 2)
        else:
            var[k] = None
    resp["variacao"] = var
    return resp


# ---------- Índice de saúde das regiões ----------

FRASE_REGRA = {
    TipoAlerta.furto: "furtad{o}",
    TipoAlerta.falha_silenciosa: "sem sinal",
    TipoAlerta.mau_funcionamento: "com defeito",
    TipoAlerta.sinal_degradado: "com sinal degradado",
    TipoAlerta.manutencao_vencida: "com manutenção vencida",
}


def plural(palavra: str, n: int) -> str:
    if n == 1:
        return palavra
    if palavra.endswith(("r", "z")):
        return palavra + "es"
    if palavra.endswith("m"):
        return palavra[:-1] + "ns"
    return palavra + "s"


def frase_alertas(regra: TipoAlerta, nome_tipo: str | None, n: int) -> str:
    if regra == TipoAlerta.incidente_correlacionado:
        return "incidente correlacionado" if n == 1 else f"{n} incidentes correlacionados"
    if regra == TipoAlerta.regiao_descoberta:
        return "sem agentes em atividade"
    if regra == TipoAlerta.agente_sem_posicao:
        return f"{n} agente{'s' if n != 1 else ''} sem posição"
    if regra == TipoAlerta.dispositivo_nao_cadastrado:
        return f"{n} dispositivo{'s' if n != 1 else ''} não cadastrado{'s' if n != 1 else ''}"
    palavra, _ = regras.nome_curto(nome_tipo or "equipamento")
    fem = palavra.endswith("a")
    frase = FRASE_REGRA.get(regra, regras.ROTULO_REGRA[regra].lower()).replace("{o}", ("a" if fem else "o") + ("s" if n != 1 else ""))
    return f"{n} {plural(palavra, n)} {frase}"


def regioes(db: Session) -> list[Regiao]:
    return list(db.scalars(select(Regiao).order_by(Regiao.nome)))


def saude_regioes(db: Session, f: Filtros | None = None, restrito: int | None = None,
                  nomes: list[str] | None = None, agora: datetime | None = None) -> list[dict]:
    agora = agora or agora_utc()
    cfg = limites.carregar(db)
    f = f or Filtros()
    lista = [r for r in regioes(db) if nomes is None or r.nome in nomes]
    if f.regiao:
        lista = [r for r in lista if r.nome in f.regiao]
    alvo = [r.nome for r in lista]
    if not alvo:
        return []

    casa = _alerta_casa_filtros(f, restrito)
    ativos = and_(
        Alerta.resolvido_em.is_(None), Alerta.estado == EstadoAlerta.aberto, Alerta.nivel.in_(NIVEIS_VISIVEIS),
        or_(Alerta.silenciado_ate.is_(None), Alerta.silenciado_ate < agora), Alerta.regiao.in_(alvo), casa,
        Alerta.tipo.notin_(regras.PREVENTIVAS),
    )
    por_nivel: dict[str, dict[str, int]] = defaultdict(dict)
    for reg, nivel, n in db.execute(select(Alerta.regiao, Alerta.nivel, func.count()).where(ativos).group_by(Alerta.regiao, Alerta.nivel)):
        por_nivel[reg][nivel.value] = n

    # Para o motivo principal: o que está pesando em cada região.
    pen = cfg["saude_penalidade"]
    detalhes: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for reg, regra, nome_tipo, nivel, n in db.execute(
        select(Alerta.regiao, Alerta.tipo, TipoEquipamento.nome, func.max(Alerta.nivel), func.count())
        .outerjoin(Equipamento, Equipamento.id == Alerta.equipamento_id)
        .outerjoin(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
        .where(ativos)
        .group_by(Alerta.regiao, Alerta.tipo, TipoEquipamento.nome)
    ):
        detalhes[reg].append((n * pen.get(nivel.value, 0), frase_alertas(regra, nome_tipo, n)))

    disp: dict[str, dict[Situacao, int]] = defaultdict(dict)
    for reg, sit, n in db.execute(
        aplicar_filtros(select(Localizacao.regiao, Equipamento.situacao, func.count()), f, restrito)
        .where(Localizacao.regiao.in_(alvo)).group_by(Localizacao.regiao, Equipamento.situacao)
    ):
        disp[reg][sit] = n

    limite = agora - timedelta(minutes=cfg["agente_sem_posicao_min"])
    agentes: dict[str, dict[str, int]] = defaultdict(dict)
    for reg, sigla, n in db.execute(
        _filtro_agentes(
            select(Agente.regiao, Orgao.sigla, func.count()).join(Orgao, Orgao.id == Agente.orgao_id)
            .where(Agente.situacao == SituacaoAgente.em_atividade, Agente.posicao_em >= limite, Agente.regiao.in_(alvo)),
            Filtros(orgao_id=f.orgao_id, area=f.area), restrito,
        ).group_by(Agente.regiao, Orgao.sigla)
    ):
        agentes[reg][sigla] = n

    hora_local = local(agora, cfg)
    saida = []
    for r in lista:
        d = disponibilidade.calcular(disp.get(r.nome, {}))
        n_ag = sum(agentes.get(r.nome, {}).values())
        idx = regras.indice_regiao(por_nivel.get(r.nome, {}), d["disponibilidade"], n_ag, cfg)
        partes = [t for _, t in sorted(detalhes.get(r.nome, []), key=lambda x: -x[0])][:2]
        if n_ag == 0:
            partes.append("sem agentes")
        if not partes and any(x["fator"] == "disponibilidade" for x in idx["fatores"]):
            partes.append(next(x["texto"] for x in idx["fatores"] if x["fator"] == "disponibilidade"))
        item = {
            "regiao": r.nome,
            **idx,
            "motivo": ", ".join(partes) if partes else "sem problemas abertos",
            "alertas": {n.value: por_nivel.get(r.nome, {}).get(n.value, 0) for n in NIVEIS_VISIVEIS},
            "disponibilidade": round(d["disponibilidade"] * 100, 1) if d["disponibilidade"] is not None else None,
            "equipamentos": sum(disp.get(r.nome, {}).values()),
            "agentes_ativos": n_ag,
            "agentes_por_orgao": agentes.get(r.nome, {}),
            "pico": regras.em_pico(r.picos, hora_local),
        }
        saida.append(item)
        if f == Filtros() and restrito is None:
            ESTADO_REGIOES[r.nome] = {"estado": item["estado"], "nota": item["nota"]}
    return sorted(saida, key=lambda x: (x["nota"], x["regiao"]))


# ---------- Fila de manutenção ----------


def fila_manutencao(db: Session, f: Filtros | None = None, restrito: int | None = None,
                    agora: datetime | None = None, limite: int = 300) -> dict:
    agora = agora or agora_utc()
    cfg = limites.carregar(db)
    hoje = local(agora, cfg).date()
    aviso = hoje + timedelta(days=cfg["manutencao_aviso_dias"])
    pt = posicao_atual()
    os_aberta = (
        select(OrdemServico.equipamento_id.label("eid"), func.max(OrdemServico.id).label("os"),
               func.max(OrdemServico.prioridade).label("prio"))
        .where(OrdemServico.status == StatusOS.aberta).group_by(OrdemServico.equipamento_id).subquery()
    )
    stmt = (
        aplicar_filtros(
            select(PlanoManutencao.tipo, PlanoManutencao.proxima_data, PlanoManutencao.descricao, Equipamento.id,
                   Equipamento.codigo_interno, TipoEquipamento.nome, Localizacao.regiao, Equipamento.situacao,
                   os_aberta.c.os, os_aberta.c.prio, func.ST_X(pt), func.ST_Y(pt)),
            f or Filtros(), restrito,
        )
        .join(PlanoManutencao, PlanoManutencao.equipamento_id == Equipamento.id)
        .outerjoin(os_aberta, os_aberta.c.eid == Equipamento.id)
        .where(PlanoManutencao.ativo.is_(True), Equipamento.situacao.not_in([S.desativado, S.nao_instalado]),
               or_(PlanoManutencao.tipo == TipoPlano.imediata, PlanoManutencao.proxima_data <= aviso))
    )
    por_equip: dict[int, dict] = {}
    ordem_cat = {"imediata": 0, "vencida": 1, "proxima": 2}
    for tipo, data_, desc, eid, cod, nome_tipo, reg, sit, os_id, prio, x, y in db.execute(stmt):
        if tipo == TipoPlano.imediata:
            cat = "imediata"
        elif data_ < hoje:
            cat = "vencida"
        else:
            cat = "proxima"
        item = {
            "categoria": cat, "equipamento_id": eid, "codigo_interno": cod, "tipo": nome_tipo, "regiao": reg,
            "situacao": sit.value, "data": data_.isoformat() if data_ else None,
            "dias": (data_ - hoje).days if data_ else None, "motivo": desc or regras.ROTULO_REGRA.get(TipoAlerta.manutencao_vencida),
            "ordem_servico": {"id": os_id, "prioridade": prio.value if prio else None} if os_id else None,
            "lon": x, "lat": y,
        }
        atual = por_equip.get(eid)
        chave = (ordem_cat[cat], item["data"] or "")
        if atual is None or chave < (ordem_cat[atual["categoria"]], atual["data"] or ""):
            por_equip[eid] = item
    itens = sorted(por_equip.values(), key=lambda i: (ordem_cat[i["categoria"]], i["data"] or "", i["codigo_interno"]))
    totais = {c: sum(1 for i in itens if i["categoria"] == c) for c in ordem_cat}
    return {"totais": totais, "total": len(itens), "itens": itens[:limite]}


# ---------- Agentes perto de um ponto ----------


def agentes_proximos(db: Session, lon: float, lat: float, n: int = 3, restrito: int | None = None) -> list[dict]:
    ponto = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    atendendo = select(Alerta.agente_id).where(Alerta.resolvido_em.is_(None), Alerta.agente_id.is_not(None))
    stmt = (
        select(Agente.id, Agente.nome, Agente.equipe, Orgao.sigla, Agente.regiao, Agente.posicao_em,
               func.ST_DistanceSphere(Agente.posicao, ponto), Agente.id.in_(atendendo))
        .join(Orgao, Orgao.id == Agente.orgao_id)
        .where(Agente.situacao == SituacaoAgente.em_atividade, Agente.posicao.is_not(None))
        .order_by(Agente.posicao.op("<->")(ponto))
        .limit(n)
    )
    if restrito is not None:
        stmt = stmt.where(Agente.orgao_id == restrito)
    return [
        {"id": i, "nome": nome, "equipe": eq, "orgao": sigla, "regiao": reg, "posicao_em": pe,
         "distancia_m": round(dist), "em_atendimento": bool(ocupado)}
        for i, nome, eq, sigla, reg, pe, dist, ocupado in db.execute(stmt)
    ]


# ---------- Instantâneos e linha do tempo ----------


def gravar_instantaneo(db: Session, agora: datetime | None = None) -> None:
    agora = agora or agora_utc()
    ind = indicadores(db, agora=agora, variacao=False)["valores"]
    regs = [{k: r[k] for k in ("regiao", "nota", "estado", "motivo")} for r in saude_regioes(db, agora=agora)]
    db.add(Instantaneo(em=agora, indicadores=ind, regioes=regs))
    db.execute(Instantaneo.__table__.delete().where(Instantaneo.em < agora - timedelta(hours=26)))


def linha_do_tempo(db: Session, T: datetime, f: Filtros | None = None, restrito: int | None = None,
                   agora: datetime | None = None) -> dict:
    """Como a cidade estava em T: indicadores, regiões, alertas abertos e equipamentos que mudaram desde então."""
    agora = agora or agora_utc()
    f = f or Filtros()
    sub = _situacao_em(T)
    eq_ids = aplicar_filtros(select(Equipamento.id), f, restrito)
    mudaram = [
        {"i": eid, "s": (antes or S.nao_instalado).value}
        for eid, antes in db.execute(select(sub.c.eid, sub.c.antes).where(sub.c.eid.in_(eq_ids)))
    ]
    criados_depois = list(db.scalars(select(Equipamento.id).where(Equipamento.criado_em > T, Equipamento.id.in_(eq_ids))))

    alertas = []
    for a in db.scalars(
        select(Alerta).where(
            Alerta.criado_em <= T, or_(Alerta.resolvido_em.is_(None), Alerta.resolvido_em > T),
            Alerta.nivel.in_(NIVEIS_VISIVEIS), Alerta.reconhecido_por.is_distinct_from(LINHA_DE_BASE),
            _alerta_casa_filtros(f, restrito),
        ).order_by(Alerta.criado_em.desc()).limit(300)
    ).unique():
        p = to_shape(a.geom) if a.geom is not None else None
        alertas.append({
            "id": a.id, "regra": a.tipo.value, "nivel": a.nivel.value, "mensagem": a.mensagem, "regiao": a.regiao,
            "equipamento_id": a.equipamento_id, "criado_em": a.criado_em.isoformat(),
            "lon": p.x if p else None, "lat": p.y if p else None,
        })

    sem_filtro = f == Filtros() and restrito is None
    foto = _instantaneo_perto(db, T, tolerancia_min=2)
    ind = {
        **_base_indicadores(contagem_situacao(db, f, restrito, T)),
        "alertas": _alertas_abertos_em(db, T, f, restrito),
        "tempo_reconhecer_s": _tempo_reconhecer(db, f, restrito, T),
    }
    if foto and sem_filtro:
        for k in ("agentes_ativos", "sem_sinal", "manutencoes_vencidas"):
            ind[k] = foto.indicadores.get(k)
    serie = [
        {"em": i.em.isoformat(), "disponibilidade": i.indicadores.get("disponibilidade"),
         "critica": (i.indicadores.get("alertas") or {}).get("critica", 0),
         "alta": (i.indicadores.get("alertas") or {}).get("alta", 0)}
        for i in db.scalars(select(Instantaneo).where(Instantaneo.em >= agora - timedelta(hours=1)).order_by(Instantaneo.em))
    ]
    return {
        "em": T.isoformat(),
        "indicadores": ind,
        "regioes": foto.regioes if foto else [],
        "alertas": alertas,
        "equipamentos": mudaram,
        "criados_depois": criados_depois,
        "serie": serie,
    }


def coordenadas(a: Alerta) -> tuple[float | None, float | None]:
    if a.geom is None:
        return None, None
    p = to_shape(a.geom)
    return round(p.x, 6), round(p.y, 6)


def alerta_json(a: Alerta, membros: int | None = None) -> dict:
    lon, lat = coordenadas(a)
    e = a.equipamento
    return {
        "id": a.id,
        "tipo": a.tipo.value,
        "regra": a.tipo.value,
        "rotulo_regra": regras.ROTULO_REGRA[a.tipo],
        "nivel": a.nivel.value,
        "nivel_inicial": a.nivel_inicial.value,
        "motivos_nivel": a.motivos_nivel or [],
        "estado": a.estado.value,
        "mensagem": a.mensagem,
        "contador": a.contador,
        "criado_em": a.criado_em,
        "ultima_ocorrencia_em": a.ultima_ocorrencia_em,
        "regiao": a.regiao,
        "lon": lon,
        "lat": lat,
        "equipamento_id": a.equipamento_id,
        "codigo_interno": e.codigo_interno if e else None,
        "tipo_equipamento": e.tipo.nome if e else None,
        "orgao": e.orgao.sigla if e else None,
        "dispositivo_iot_id": a.dispositivo_iot_id,
        "agente_alvo_id": a.agente_alvo_id,
        "agente": {"id": a.agente.id, "nome": a.agente.nome, "orgao": a.agente.orgao.sigla} if a.agente else None,
        "ordem_servico_id": a.ordem_servico_id,
        "incidente_id": a.incidente_id,
        "membros": membros if membros is not None else (a.dados or {}).get("membros", 0),
        "equipamentos": (a.dados or {}).get("equipamentos", []),
        "silenciado_ate": a.silenciado_ate,
        "silenciado_motivo": a.silenciado_motivo,
        "reconhecido_em": a.reconhecido_em,
        "reconhecido_por": a.reconhecido_por,
        "resolvido_em": a.resolvido_em,
        "resolvido_por": a.resolvido_por,
        "resolucao": a.resolucao,
        "severidade": a.severidade.value,
        "simulado": bool((a.dados or {}).get("simulado")),
        # Parte 3: alerta preventivo (previsão por trás, para quando, antecedência)
        "preditivo": (a.dados or {}).get("preditivo"),
    }


def calor_alertas(db: Session, f: Filtros | None = None, restrito: int | None = None, agora: datetime | None = None) -> dict:
    """Pontos dos alertas das últimas 24 h, com peso pelo nível (camada de mapa de calor)."""
    agora = agora or agora_utc()
    peso = {NivelAlerta.critica: 1.0, NivelAlerta.alta: 0.6, NivelAlerta.media: 0.3}
    linhas = db.execute(
        select(func.ST_X(Alerta.geom), func.ST_Y(Alerta.geom), Alerta.nivel).where(
            Alerta.criado_em >= agora - timedelta(hours=24), Alerta.geom.is_not(None), Alerta.nivel.in_(NIVEIS_VISIVEIS),
            Alerta.reconhecido_por.is_distinct_from(LINHA_DE_BASE), _alerta_casa_filtros(f, restrito))
    ).all()
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(x, 5), round(y, 5)]},
         "properties": {"w": peso.get(n, 0.2)}} for x, y, n in linhas]}
