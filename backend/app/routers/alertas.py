"""Alertas: lista priorizada e as ações leves da central (reconhecer, silenciar, atribuir agente,
abrir ordem de serviço, resolver)."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Contexto, Ctx
from app.domain import limites
from app.domain.estados import RegraViolada
from app.models import Agente, Alerta, OrdemServico
from app.models.enums import EstadoAlerta, NivelAlerta, PrioridadeOS, Severidade, SituacaoAgente, TipoAlerta
from app.routers.equipamentos import filtros_da_query
from app.schemas.api import AcaoAlertaIn, AtribuirIn, OrdemAlertaIn
from app.services import central, motor
from app.services import equipamentos as svc
from app.services.barramento import emitir, tocar

router = APIRouter(tags=["alertas"])
DB = Annotated[Session, Depends(get_db)]
E = EstadoAlerta

ORDEM_NIVEL = case(
    (Alerta.nivel == NivelAlerta.critica, 0), (Alerta.nivel == NivelAlerta.alta, 1),
    (Alerta.nivel == NivelAlerta.media, 2), else_=3,
)
ORDEM_ESTADO = case((Alerta.estado == E.aberto, 0), (Alerta.estado == E.reconhecido, 1), else_=2)


@router.get("/alertas")
def listar(
    db: DB,
    ctx: Ctx,
    f: Annotated[svc.Filtros, Depends(filtros_da_query)],
    abertos: bool = True,
    tipo: Annotated[list[TipoAlerta], Query(description="regra de detecção")] = [],
    severidade: Annotated[list[Severidade], Query()] = [],
    nivel_alerta: Annotated[list[NivelAlerta], Query(alias="nivel_alerta")] = [],
    estado: Annotated[list[EstadoAlerta], Query()] = [],
    equipamento_id: int | None = None,
    incidente_id: int | None = None,
    agente_id: int | None = Query(None, description="alertas atribuídos a este agente"),
    agrupar: bool = Query(False, description="esconde alertas que estão dentro de um incidente"),
    incluir_baixa: bool = False,
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(50, ge=1, le=500),
):
    """Ordenados por nível (críticos no topo), depois os ainda não reconhecidos, depois os mais novos.
    Silenciados vão para o fim. Os filtros da central valem aqui também."""
    agora = datetime.now(timezone.utc)
    restrito = ctx.orgao_id if ctx.restrito else None
    stmt = select(Alerta.id).where(central._alerta_casa_filtros(f, restrito))
    if abertos:
        stmt = stmt.where(Alerta.resolvido_em.is_(None))
    if tipo:
        stmt = stmt.where(Alerta.tipo.in_(tipo))
    if severidade:
        stmt = stmt.where(Alerta.severidade.in_(severidade))
    if nivel_alerta:
        stmt = stmt.where(Alerta.nivel.in_(nivel_alerta))
    elif not incluir_baixa and equipamento_id is None:
        stmt = stmt.where(Alerta.nivel != NivelAlerta.baixa)
    if estado:
        stmt = stmt.where(Alerta.estado.in_(estado))
    if equipamento_id:
        stmt = stmt.where(Alerta.equipamento_id == equipamento_id)
    if agente_id:
        stmt = stmt.where(Alerta.agente_id == agente_id)
    if f.nivel:
        stmt = stmt.where(Alerta.nivel.in_(f.nivel))
    if incidente_id:
        stmt = stmt.where(Alerta.incidente_id == incidente_id)
    elif agrupar:
        stmt = stmt.where(Alerta.incidente_id.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    silenciado = case((Alerta.silenciado_ate > agora, 1), else_=0)
    ids = db.scalars(
        stmt.order_by(silenciado, ORDEM_NIVEL, ORDEM_ESTADO, Alerta.criado_em.desc(), Alerta.id.desc())
        .offset((pagina - 1) * por_pagina).limit(por_pagina)
    ).all()
    por_id = {a.id: a for a in db.scalars(select(Alerta).where(Alerta.id.in_(ids))).unique()}
    membros = dict(db.execute(
        select(Alerta.incidente_id, func.count()).where(Alerta.incidente_id.in_(ids), Alerta.resolvido_em.is_(None))
        .group_by(Alerta.incidente_id)).all()) if ids else {}
    itens = [central.alerta_json(por_id[i], membros.get(i) if por_id[i].tipo == TipoAlerta.incidente_correlacionado else None)
             for i in ids]
    contagem = dict(db.execute(
        select(Alerta.nivel, func.count()).where(
            Alerta.resolvido_em.is_(None), Alerta.nivel != NivelAlerta.baixa, central._alerta_casa_filtros(f, restrito),
            *( [Alerta.incidente_id.is_(None)] if agrupar else [] ))
        .group_by(Alerta.nivel)).all())
    return {"itens": itens, "total": total, "pagina": pagina, "por_pagina": por_pagina,
            "por_nivel": {n.value: contagem.get(n, 0) for n in NivelAlerta if n != NivelAlerta.baixa}}


def _obter(db: Session, alerta_id: int, ctx: Contexto) -> Alerta:
    a = db.get(Alerta, alerta_id)
    if a is None:
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Alerta não encontrado."})
    if ctx.perfil == "prometheus":
        raise HTTPException(403, {"codigo": "sem_permissao", "mensagem": "O PROMETHEUS só lê alertas."})
    if a.equipamento is not None:
        ctx.exigir_alterar(a.equipamento.orgao_id)
    elif a.agente_alvo_id is not None and ctx.restrito:
        ag = db.get(Agente, a.agente_alvo_id)
        if ag is not None:
            ctx.exigir_alterar(ag.orgao_id)
    return a


@router.get("/alertas/{alerta_id}")
def ver(alerta_id: int, db: DB, ctx: Ctx):
    a = db.get(Alerta, alerta_id)
    if a is None or (ctx.restrito and a.equipamento is not None and a.equipamento.orgao_id != ctx.orgao_id):
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Alerta não encontrado."})
    membros = list(db.scalars(select(Alerta).where(Alerta.incidente_id == a.id).order_by(Alerta.criado_em)).unique())
    return {**central.alerta_json(a, len([m for m in membros if m.resolvido_em is None])),
            "lista_membros": [central.alerta_json(m) for m in membros]}


def _cascata_incidente(db: Session, a: Alerta, estado: EstadoAlerta, agora: datetime, usuario: str) -> None:
    """Ações no incidente valem para os equipamentos dentro dele."""
    if a.tipo != TipoAlerta.incidente_correlacionado:
        return
    for m in db.scalars(select(Alerta).where(Alerta.incidente_id == a.id, Alerta.resolvido_em.is_(None))).unique():
        if m.estado == E.aberto or estado == E.em_atendimento:
            m.estado = estado
            m.reconhecido_em = m.reconhecido_em or agora
            m.reconhecido_por = m.reconhecido_por or usuario
            emitir(db, {"tipo": "alerta", "acao": "atualizado", "alerta": central.alerta_json(m)})
            tocar(db, m.equipamento_id)


@router.patch("/alertas/{alerta_id}")
def agir(alerta_id: int, body: AcaoAlertaIn, db: DB, ctx: Ctx):
    """reconhecer ("estou vendo"), silenciar (até 30 min, motivo obrigatório) ou resolver."""
    a = _obter(db, alerta_id, ctx)
    agora = datetime.now(timezone.utc)
    if a.resolvido_em is not None:
        raise RegraViolada("alerta_resolvido", "Este alerta já foi resolvido.")
    if body.acao == "reconhecer":
        if a.estado == E.aberto:
            a.estado = E.reconhecido
        a.reconhecido_em = a.reconhecido_em or agora
        a.reconhecido_por = a.reconhecido_por or ctx.usuario
        _cascata_incidente(db, a, E.reconhecido, agora, ctx.usuario)
    elif body.acao == "silenciar":
        maximo = limites.carregar(db)["silenciar_max_min"]
        if not body.motivo or not body.motivo.strip():
            raise RegraViolada("motivo_obrigatorio", "Para silenciar, informe o motivo.")
        minutos = min(body.minutos or maximo, maximo)
        a.silenciado_ate = agora + timedelta(minutes=minutos)
        a.silenciado_motivo = f"{body.motivo.strip()} ({ctx.usuario})"
    elif body.acao == "reabrir_som":
        a.silenciado_ate = None
        a.silenciado_motivo = None
    else:
        motor.resolver(db, a, ctx.usuario, (body.motivo or "Encerrado pelo operador").strip(), agora)
        db.commit()
        return central.alerta_json(a)
    db.flush()
    emitir(db, {"tipo": "alerta", "acao": "atualizado", "alerta": central.alerta_json(a)})
    tocar(db, a.equipamento_id)
    db.commit()
    return central.alerta_json(a)


@router.post("/alertas/{alerta_id}/resolver")
def resolver(alerta_id: int, db: DB, ctx: Ctx):
    """Compatível com a Parte 1."""
    a = _obter(db, alerta_id, ctx)
    motor.resolver(db, a, ctx.usuario, "Encerrado pelo operador")
    db.commit()
    return {"ok": True}


@router.get("/alertas/{alerta_id}/agentes-proximos")
def agentes_proximos(alerta_id: int, db: DB, ctx: Ctx, n: int = Query(3, ge=1, le=10)):
    a = db.get(Alerta, alerta_id)
    if a is None:
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Alerta não encontrado."})
    lon, lat = central.coordenadas(a)
    if lon is None:
        return []
    return central.agentes_proximos(db, lon, lat, n, ctx.orgao_id if ctx.restrito else None)


@router.post("/alertas/{alerta_id}/atribuir")
def atribuir(alerta_id: int, body: AtribuirIn, db: DB, ctx: Ctx):
    a = _obter(db, alerta_id, ctx)
    if a.resolvido_em is not None:
        raise RegraViolada("alerta_resolvido", "Este alerta já foi resolvido.")
    ag = db.get(Agente, body.agente_id)
    if ag is None:
        raise RegraViolada("agente_invalido", "Agente não encontrado.")
    if ag.situacao != SituacaoAgente.em_atividade:
        raise RegraViolada("agente_indisponivel", f"{ag.nome} não está em atividade.")
    if ctx.restrito and ag.orgao_id != ctx.orgao_id:
        raise HTTPException(403, {"codigo": "sem_permissao", "mensagem": "Seu perfil só atribui agentes do próprio órgão."})
    agora = datetime.now(timezone.utc)
    anterior = a.agente_id
    a.agente_id = ag.id
    a.estado = E.em_atendimento
    a.reconhecido_em = a.reconhecido_em or agora
    a.reconhecido_por = a.reconhecido_por or ctx.usuario
    _cascata_incidente(db, a, E.em_atendimento, agora, ctx.usuario)
    db.flush()
    db.refresh(a)
    emitir(db, {"tipo": "alerta", "acao": "atualizado", "alerta": central.alerta_json(a)})
    emitir(db, {"tipo": "agentes", "ids": [i for i in (ag.id, anterior) if i]})
    tocar(db, a.equipamento_id)
    db.commit()
    return central.alerta_json(a)


@router.post("/alertas/{alerta_id}/ordem-servico")
def abrir_ordem(alerta_id: int, body: OrdemAlertaIn, db: DB, ctx: Ctx):
    a = _obter(db, alerta_id, ctx)
    if a.equipamento_id is None:
        raise RegraViolada("sem_equipamento", "Ordem de serviço só para alerta de equipamento.")
    if a.ordem_servico_id:
        raise RegraViolada("os_existente", f"Já existe a ordem de serviço #{a.ordem_servico_id} para este alerta.", status=409)
    prioridade = {NivelAlerta.critica: PrioridadeOS.critica, NivelAlerta.alta: PrioridadeOS.alta,
                  NivelAlerta.media: PrioridadeOS.media}.get(a.nivel, PrioridadeOS.baixa)
    agora = datetime.now(timezone.utc)
    os_ = OrdemServico(equipamento_id=a.equipamento_id, motivo=(body.motivo or a.mensagem).strip(), prioridade=prioridade,
                       aberta_em=agora)
    db.add(os_)
    db.flush()
    a.ordem_servico_id = os_.id
    a.estado = E.em_atendimento
    a.reconhecido_em = a.reconhecido_em or agora
    a.reconhecido_por = a.reconhecido_por or ctx.usuario
    db.flush()
    emitir(db, {"tipo": "alerta", "acao": "atualizado", "alerta": central.alerta_json(a)})
    tocar(db, a.equipamento_id)
    db.commit()
    return {**central.alerta_json(a), "ordem_servico": {"id": os_.id, "prioridade": prioridade.value}}
