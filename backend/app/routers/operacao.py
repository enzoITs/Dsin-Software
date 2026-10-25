"""Telemetria, alertas, indicadores, eventos e cadastros de apoio (órgãos, cidades, bairros, bases, CEP)."""

import json
import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.domain import disponibilidade
from app.models import (
    Alerta,
    Bairro,
    BaseOperacional,
    Cidade,
    Equipamento,
    HistoricoSituacao,
    Localizacao,
    Orgao,
    TipoEquipamento,
)
from app.models.enums import NivelAlerta, Situacao, StatusManutencao
from app.routers.equipamentos import filtros_da_query
from app.schemas.api import BairroOut, BaseOut, CidadeOut, OrgaoOut, PosicaoAgenteIn, SinalIn, SinalOut
from app.services import equipamentos as svc
from app.services import motor, simulacao, viacep

router = APIRouter(tags=["operação"])
DB = Annotated[Session, Depends(get_db)]


# ---------- Telemetria (passa pelo motor de interpretação) ----------


def _com_retentativa(db: Session, fn):
    """Lotes de telemetria disputam linhas com o recálculo periódico; em deadlock, tenta de novo."""
    for tentativa in range(3):
        try:
            res = fn()
            db.commit()
            return res
        except OperationalError as exc:
            db.rollback()
            if "deadlock" not in str(exc).lower() or tentativa == 2:
                raise
            time.sleep(0.2 * (tentativa + 1))


def _sem_simulados(sinais: list[SinalIn]) -> list[SinalIn]:
    """Enquanto uma simulação de silêncio está ativa, sinais desses equipamentos são descartados:
    o simulador pode ter um lote em trânsito, e o equipamento "parado" não pode voltar sozinho."""
    parados = set(simulacao.ler_estado().get("parados", []))
    if not parados:
        return sinais
    ids = {d for (d,) in _db_parados(parados)}
    return [s for s in sinais if s.dispositivo_iot_id not in ids]


def _db_parados(codigos: set[str]):
    from app.db import SessionLocal

    with SessionLocal() as db:
        return db.execute(select(Equipamento.dispositivo_iot_id).where(Equipamento.codigo_interno.in_(codigos))).all()


def _sinal(b: SinalIn) -> motor.Sinal:
    return motor.Sinal(dispositivo_iot_id=b.dispositivo_iot_id.strip(), em=b.em, tipo=b.tipo, lon=b.lon, lat=b.lat,
                       valores=b.valores)


@router.post("/telemetria/sinal", response_model=SinalOut, tags=["telemetria"])
def receber_sinal(body: SinalIn, db: DB):
    """Um sinal: presença, posição, erro ou métrica. Dispositivo desconhecido abre alerta e responde 404."""
    res = _com_retentativa(db, lambda: motor.processar_sinais(db, [_sinal(s) for s in _sem_simulados([body])]))
    e = db.scalar(select(Equipamento).where(Equipamento.dispositivo_iot_id == body.dispositivo_iot_id.strip()))
    if e is None:
        raise HTTPException(404, {"codigo": "dispositivo_desconhecido",
                                  "mensagem": "Nenhum equipamento usa este módulo IoT. Alerta de dispositivo não cadastrado aberto."})
    return SinalOut(equipamento_id=e.id, codigo_interno=e.codigo_interno, ultimo_sinal_em=e.ultimo_sinal_em,
                    alerta_resolvido=res["alertas_resolvidos"] > 0, alertas=res["alertas"])


@router.post("/telemetria/sinais", tags=["telemetria"])
def receber_sinais(sinais: list[SinalIn], db: DB):
    """Lote de sinais, usado pelo simulador e por gateways IoT."""
    return _com_retentativa(db, lambda: motor.processar_sinais(db, [_sinal(s) for s in _sem_simulados(sinais)]))


@router.post("/telemetria/agentes", tags=["telemetria"])
def receber_posicoes_agentes(posicoes: list[PosicaoAgenteIn], db: DB):
    """Posição dos agentes em campo (por id ou matrícula)."""
    return _com_retentativa(db, lambda: motor.processar_posicoes_agentes(db, [p.model_dump() for p in posicoes]))


# ---------- Indicadores ----------

AGRUPAMENTOS = {
    "orgao": (Orgao.sigla, Orgao.id == Equipamento.orgao_id, Orgao),
    "tipo": (TipoEquipamento.nome, None, None),
    "regiao": (Localizacao.regiao, None, None),
    "bairro": (Bairro.nome, Bairro.id == Localizacao.bairro_id, Bairro),
}


@router.get("/indicadores/disponibilidade", tags=["indicadores"])
def indicador_disponibilidade(
    db: DB,
    ctx: Ctx,
    f: Annotated[svc.Filtros, Depends(filtros_da_query)],
    agrupar: str | None = Query(None, pattern="^(orgao|tipo|regiao|bairro)$"),
):
    """Regra única de disponibilidade. Toda tela e o PROMETHEUS usam este cálculo."""
    restrito = ctx.orgao_id if ctx.restrito else None
    cols = [Equipamento.situacao, func.count()]
    stmt = svc.aplicar_filtros(select(*cols), f, restrito)
    geral = disponibilidade.calcular(dict(db.execute(stmt.group_by(Equipamento.situacao)).all()))
    resp = {"regra": disponibilidade.__doc__.strip(), "geral": geral, "filtros": f.como_dict()}
    if agrupar:
        coluna, join_cond, entidade = AGRUPAMENTOS[agrupar]
        stmt = svc.aplicar_filtros(select(coluna, Equipamento.situacao, func.count()), f, restrito)
        if entidade is not None:
            stmt = stmt.outerjoin(entidade, join_cond)
        grupos: dict[str | None, dict[Situacao, int]] = {}
        for chave, sit, n in db.execute(stmt.group_by(coluna, Equipamento.situacao)).all():
            grupos.setdefault(chave, {})[sit] = n
        resp["grupos"] = sorted(
            ({"grupo": k or "(sem informação)", **disponibilidade.calcular(v)} for k, v in grupos.items()),
            key=lambda g: (g["disponibilidade"] is None, g["disponibilidade"] or 0),
        )
    return resp


@router.get("/indicadores/resumo", tags=["indicadores"])
def indicador_resumo(db: DB, ctx: Ctx):
    """Números da página inicial."""
    restrito = ctx.orgao_id if ctx.restrito else None
    f = svc.Filtros()
    base = svc.aplicar_filtros(select(Equipamento.situacao, func.count()), f, restrito)
    contagem = dict(db.execute(base.group_by(Equipamento.situacao)).all())
    total = sum(contagem.values())
    manut = dict(
        db.execute(svc.aplicar_filtros(select(Equipamento.status_manutencao, func.count()), f, restrito)
                   .group_by(Equipamento.status_manutencao)).all()
    )
    sem_sinal = db.scalar(svc.aplicar_filtros(select(func.count()), svc.Filtros(sem_sinal=True), restrito))
    score_medio = db.scalar(svc.aplicar_filtros(select(func.avg(Equipamento.score_saude)), f, restrito))
    alerta_q = select(Alerta.tipo, func.count()).join(Equipamento).where(
        Alerta.resolvido_em.is_(None), Alerta.nivel != NivelAlerta.baixa)
    if restrito:
        alerta_q = alerta_q.where(Equipamento.orgao_id == restrito)
    alertas_abertos = {k.value: v for k, v in db.execute(alerta_q.group_by(Alerta.tipo)).all()}
    return {
        "total_equipamentos": total,
        "disponibilidade": disponibilidade.calcular(contagem),
        "manutencao": {k.value: manut.get(k, 0) for k in StatusManutencao},
        "sem_sinal": sem_sinal,
        "score_medio": round(float(score_medio or 0), 1),
        "alertas_abertos": alertas_abertos,
    }


# ---------- Eventos (para o PROMETHEUS consultar) ----------


@router.get("/eventos", tags=["eventos"])
def listar_eventos(db: DB, desde: datetime | None = None, limite: int = Query(200, ge=1, le=5000)):
    """Mudanças de situação em ordem cronológica. O mesmo formato é enviado por webhook."""
    stmt = (
        select(HistoricoSituacao, Equipamento.codigo_interno, Equipamento.dispositivo_iot_id, Orgao.sigla)
        .join(Equipamento, Equipamento.id == HistoricoSituacao.equipamento_id)
        .join(Orgao, Orgao.id == Equipamento.orgao_id)
    )
    if desde:
        stmt = stmt.where(HistoricoSituacao.em > desde).order_by(HistoricoSituacao.em.asc())
    else:
        stmt = stmt.order_by(HistoricoSituacao.em.desc())
    linhas = db.execute(stmt.limit(limite)).all()
    return [
        {
            "evento": "situacao_alterada", "id": h.id, "equipamento_id": h.equipamento_id, "codigo_interno": cod,
            "dispositivo_iot_id": disp, "orgao": sigla,
            "situacao_anterior": h.situacao_anterior.value if h.situacao_anterior else None,
            "situacao_nova": h.situacao_nova.value, "motivo": h.motivo, "usuario": h.usuario, "em": h.em.isoformat(),
        }
        for h, cod, disp, sigla in linhas
    ]


# ---------- Cadastros de apoio ----------


@router.get("/orgaos", response_model=list[OrgaoOut], tags=["apoio"])
def orgaos(db: DB):
    return db.scalars(select(Orgao).order_by(Orgao.sigla)).all()


@router.get("/cidades", response_model=list[CidadeOut], tags=["apoio"])
def cidades(db: DB):
    saida = []
    for c in db.scalars(select(Cidade).order_by(Cidade.nome)):
        o = CidadeOut.model_validate(c)
        if c.centro is not None:
            p = to_shape(c.centro)
            o.lon, o.lat = p.x, p.y
        saida.append(o)
    return saida


@router.get("/cidades/{cidade_id}/bairros", response_model=list[BairroOut], tags=["apoio"])
def bairros(cidade_id: int, db: DB):
    return db.scalars(select(Bairro).where(Bairro.cidade_id == cidade_id).order_by(Bairro.nome)).all()


@router.get("/cidades/{cidade_id}/bairros.geojson", tags=["apoio"])
def bairros_geojson(cidade_id: int, db: DB):
    linhas = db.execute(
        select(Bairro.id, Bairro.nome, Bairro.regiao, func.ST_AsGeoJSON(func.ST_Simplify(Bairro.geom, 0.0005)))
        .where(Bairro.cidade_id == cidade_id)
    ).all()
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "id": i, "properties": {"id": i, "nome": n, "regiao": r}, "geometry": json.loads(g)}
            for i, n, r, g in linhas if g
        ],
    }


@router.get("/localizacao/sugerir", tags=["apoio"])
def sugerir_localizacao(cidade_id: int, lon: float, lat: float, db: DB, bairro_id: int | None = None):
    """Bairro e região sugeridos pelo ponto no mapa, com avisos de divergência."""
    cidade = db.get(Cidade, cidade_id)
    if cidade is None:
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Cidade não encontrada."})
    sugerido, regiao, avisos = svc.avaliar_localizacao(db, cidade, bairro_id, lon, lat)
    return {"bairro_id": sugerido, "regiao": regiao, "avisos": avisos}


@router.get("/bases", response_model=list[BaseOut], tags=["apoio"])
def bases(db: DB, orgao_id: int | None = None):
    stmt = select(BaseOperacional).order_by(BaseOperacional.nome)
    if orgao_id:
        stmt = stmt.where(BaseOperacional.orgao_id == orgao_id)
    return db.scalars(stmt).all()


@router.get("/cep/{cep}", tags=["apoio"])
def cep(cep: str, db: DB):
    try:
        dados = viacep.consultar(cep)
    except viacep.CepIndisponivel:
        raise HTTPException(503, {"codigo": "cep_indisponivel", "mensagem": "Consulta de CEP indisponível. Digite o endereço."})
    if dados is None:
        raise HTTPException(404, {"codigo": "cep_nao_encontrado", "mensagem": "CEP não encontrado."})
    cidade = db.scalar(select(Cidade).where(func.lower(Cidade.nome) == (dados["cidade"] or "").lower(), Cidade.uf == dados["uf"]))
    dados["cidade_id"] = cidade.id if cidade else None
    if cidade and dados.get("bairro"):
        b = db.scalar(
            select(Bairro).where(Bairro.cidade_id == cidade.id, func.unaccent(func.lower(Bairro.nome)) == func.unaccent(func.lower(dados["bairro"])))
        )
        dados["bairro_id"] = b.id if b else None
    return dados


# ---------- Qualidade ----------


@router.get("/qualidade", tags=["qualidade"])
def qualidade(db: DB, ctx: Ctx, orgao_id: int | None = None):
    """Completude, problemas encontrados e ranking por órgão."""
    from app.domain import qualidade as q

    return q.avaliar(db, ctx.orgao_id if ctx.restrito else orgao_id)
