"""API da Parte 3 (Cidade Preditiva): ocorrências e fatores externos.

Ocorrências, eventos da cidade, clima previsto (editável), calendário e escala de agentes.
São as entradas dos modelos; as previsões em si ganham rotas próprias nas fases seguintes.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import WKTElement
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.domain import catalogo
from app.models import CategoriaOcorrencia, Cidade, EscalaAgente, EventoCidade, Orgao, Regiao
from app.models.enums import OrigemOcorrencia
from app.preditivo import calendario, clima
from app.schemas.preditivo import ClimaEdicaoIn, EventoCidadeIn, OcorrenciaIn
from app.services import ocorrencias

router = APIRouter(tags=["preditivo: dados"])
DB = Annotated[Session, Depends(get_db)]


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _sem_prometheus(ctx) -> None:
    if ctx.perfil == "prometheus":
        raise HTTPException(403, {"codigo": "sem_permissao", "mensagem": "O PROMETHEUS só lê estes dados."})


def cidade_principal(db: Session) -> int:
    cid = db.scalar(select(Cidade.id).where(Cidade.nome == catalogo.CIDADE_PRINCIPAL["nome"]))
    cid = cid or db.scalar(select(Cidade.id).order_by(Cidade.id).limit(1))
    if cid is None:
        raise HTTPException(409, {"codigo": "sem_cidade", "mensagem": "Nenhuma cidade cadastrada."})
    return cid


# ---------- Ocorrências ----------

@router.get("/ocorrencias/categorias")
def categorias(db: DB):
    return [
        {"codigo": c.codigo, "nome": c.nome, "descricao": c.descricao, "gravidade_padrao": c.gravidade_padrao}
        for c in db.scalars(select(CategoriaOcorrencia).where(CategoriaOcorrencia.ativa).order_by(CategoriaOcorrencia.nome))
    ]


@router.get("/ocorrencias")
def listar_ocorrencias(
    db: DB,
    desde: datetime | None = None,
    ate: datetime | None = None,
    horas: Annotated[int | None, Query(ge=1, le=24 * 400, description="Atalho: últimas N horas")] = None,
    regiao: str | None = None,
    categoria: Annotated[list[str] | None, Query()] = None,
    origem: OrigemOcorrencia | None = None,
    limite: Annotated[int, Query(ge=1, le=5000)] = 500,
):
    if horas and not desde:
        desde = _agora() - timedelta(hours=horas)
    return ocorrencias.listar(db, desde=desde, ate=ate, regiao=regiao, categorias=categoria, origem=origem, limite=limite)


@router.post("/ocorrencias", status_code=201)
def registrar_ocorrencia(body: OcorrenciaIn, db: DB, ctx: Ctx):
    """Registra uma ocorrência. Pela central, a origem é "central"; pelo PROMETHEUS, "externa"."""
    origem = OrigemOcorrencia.externa if ctx.perfil == "prometheus" else OrigemOcorrencia.central
    if body.fim_em and body.inicio_em and body.fim_em < body.inicio_em:
        raise HTTPException(422, {"codigo": "periodo_invalido", "mensagem": "O fim precisa ser depois do início."})
    try:
        js = ocorrencias.registrar(
            db, categoria=body.categoria, gravidade=body.gravidade, lon=body.lon, lat=body.lat, origem=origem,
            inicio_em=body.inicio_em, fim_em=body.fim_em, descricao=body.descricao, registrado_por=ctx.usuario,
        )
    except ocorrencias.CategoriaInvalida:
        raise HTTPException(422, {"codigo": "categoria_invalida", "mensagem": f"Categoria desconhecida: {body.categoria}"})
    db.commit()
    return js


# ---------- Eventos da cidade ----------

def _evento_json(ev: EventoCidade, lon: float, lat: float) -> dict:
    return {
        "id": ev.id, "nome": ev.nome, "tipo": ev.tipo.value, "local_nome": ev.local_nome, "lon": lon, "lat": lat,
        "inicio_em": ev.inicio_em, "fim_em": ev.fim_em, "publico_estimado": ev.publico_estimado,
        "raio_influencia_m": ev.raio_influencia_m, "simulado": ev.simulado, "criado_por": ev.criado_por,
    }


@router.get("/eventos-cidade")
def listar_eventos(db: DB, desde: datetime | None = None, ate: datetime | None = None,
                   limite: Annotated[int, Query(ge=1, le=2000)] = 200):
    """Eventos que se sobrepõem ao período. Padrão: de ontem até daqui a 7 dias."""
    agora = _agora()
    desde = desde or agora - timedelta(days=1)
    ate = ate or agora + timedelta(days=7)
    linhas = db.execute(
        select(EventoCidade, func.ST_X(EventoCidade.geom), func.ST_Y(EventoCidade.geom))
        .where(EventoCidade.fim_em >= desde, EventoCidade.inicio_em <= ate)
        .order_by(EventoCidade.inicio_em).limit(limite)
    ).all()
    return [_evento_json(ev, x, y) for ev, x, y in linhas]


@router.post("/eventos-cidade", status_code=201)
def criar_evento(body: EventoCidadeIn, db: DB, ctx: Ctx):
    _sem_prometheus(ctx)
    ev = EventoCidade(
        nome=body.nome, tipo=body.tipo, local_nome=body.local_nome,
        geom=WKTElement(f"POINT({body.lon} {body.lat})", srid=4326), inicio_em=body.inicio_em, fim_em=body.fim_em,
        publico_estimado=body.publico_estimado, raio_influencia_m=body.raio_influencia_m, simulado=False,
        criado_por=ctx.usuario,
    )
    db.add(ev)
    db.commit()
    return _evento_json(ev, body.lon, body.lat)


@router.delete("/eventos-cidade/{evento_id}", status_code=204)
def remover_evento(evento_id: int, db: DB, ctx: Ctx):
    _sem_prometheus(ctx)
    ev = db.get(EventoCidade, evento_id)
    if ev is None:
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Evento não encontrado."})
    db.delete(ev)
    db.commit()


# ---------- Clima ----------

def _clima_json(c) -> dict:
    return {"em": c.em, "temperatura_c": c.temperatura_c, "chuva_mm": c.chuva_mm,
            "alerta_tempestade": c.alerta_tempestade, "editado_por": c.editado_por}


@router.get("/clima/previsao")
def previsao_clima(db: DB, horas: Annotated[int, Query(ge=1, le=168)] = 72):
    """Previsão hora a hora. Horas sem previsão recebem o clima típico da estação (sintético)."""
    linhas = clima.previsao(db, cidade_principal(db), _agora(), horas)
    db.commit()
    return {"fonte": "sintetica", "horas": [_clima_json(c) for c in linhas]}


@router.put("/clima/previsao")
def editar_clima(body: ClimaEdicaoIn, db: DB, ctx: Ctx):
    """Edita a previsão de um período, por exemplo "amanhã: chuva forte à tarde"."""
    _sem_prometheus(ctx)
    n = clima.editar(db, cidade_principal(db), body.inicio, body.fim, ctx.usuario, chuva_mm=body.chuva_mm,
                     temperatura_c=body.temperatura_c, alerta_tempestade=body.alerta_tempestade)
    db.commit()
    return {"horas_alteradas": n}


# ---------- Calendário e escala ----------

@router.get("/calendario")
def ver_calendario(db: DB, inicio: date | None = None, fim: date | None = None):
    hoje = _agora().astimezone(clima.FUSO).date()
    inicio = inicio or hoje
    fim = fim or inicio + timedelta(days=14)
    if fim < inicio or (fim - inicio).days > 800:
        raise HTTPException(422, {"codigo": "periodo_invalido", "mensagem": "Período inválido (máximo de 800 dias)."})
    linhas = calendario.periodo(db, inicio, fim)
    db.commit()
    return [
        {"data": c.data, "dia_semana": c.dia_semana, "feriado": c.feriado, "feriado_nome": c.feriado_nome,
         "feriado_esfera": c.feriado_esfera, "vespera_feriado": c.vespera_feriado,
         "periodo_escolar": c.periodo_escolar, "dia_pagamento": c.dia_pagamento}
        for c in linhas
    ]


@router.get("/escala")
def ver_escala(db: DB, inicio: datetime | None = None, fim: datetime | None = None, regiao: str | None = None):
    """Turnos das equipes que se sobrepõem ao período (padrão: próximas 72 h)."""
    agora = _agora()
    inicio = inicio or agora
    fim = fim or inicio + timedelta(hours=72)
    stmt = (
        select(EscalaAgente, Regiao.nome, Orgao.sigla)
        .join(Regiao, Regiao.id == EscalaAgente.regiao_id).join(Orgao, Orgao.id == EscalaAgente.orgao_id)
        .where(EscalaAgente.fim_em > inicio, EscalaAgente.inicio_em < fim)
    )
    if regiao:
        stmt = stmt.where(Regiao.nome == regiao)
    return [
        {"id": e.id, "equipe": e.equipe, "orgao": sigla, "regiao": nome, "inicio_em": e.inicio_em, "fim_em": e.fim_em,
         "agentes": e.agentes, "origem": e.origem}
        for e, nome, sigla in db.execute(stmt.order_by(EscalaAgente.inicio_em, Regiao.nome)).all()
    ]
