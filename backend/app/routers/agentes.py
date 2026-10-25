from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.domain.estados import RegraViolada
from app.models import Agente, BaseOperacional, Equipamento, Orgao
from app.models.enums import CategoriaAgente, Mobilidade, SituacaoAgente
from app.schemas.api import AgenteIn, AgenteOut, AgentePatch, Pagina, VeiculoResumo

router = APIRouter(prefix="/agentes", tags=["agentes"])
DB = Annotated[Session, Depends(get_db)]


def _out(a: Agente) -> AgenteOut:
    v = a.veiculo
    return AgenteOut(
        id=a.id, nome=a.nome, matricula=a.matricula, categoria=a.categoria, orgao_id=a.orgao_id,
        orgao=a.orgao.sigla, equipe=a.equipe, situacao=a.situacao, contato=a.contato,
        veiculo=VeiculoResumo(id=v.id, codigo_interno=v.codigo_interno, tipo=v.tipo.nome,
                              placa=(v.atributos or {}).get("placa")) if v else None,
        base_id=a.base_id, base=a.base.nome if a.base else None,
    )


def _validar_vinculos(db: Session, orgao_id: int, veiculo_id: int | None, base_id: int | None, agente_id: int | None = None):
    if veiculo_id is not None:
        v = db.get(Equipamento, veiculo_id)
        if v is None or v.tipo.mobilidade != Mobilidade.movel:
            raise RegraViolada("veiculo_invalido", "O veículo precisa ser um equipamento móvel cadastrado.")
        if v.orgao_id != orgao_id:
            raise RegraViolada("veiculo_de_outro_orgao", f"O veículo {v.codigo_interno} pertence a outro órgão.")
        stmt = select(Agente.nome).where(Agente.veiculo_id == veiculo_id)
        if agente_id:
            stmt = stmt.where(Agente.id != agente_id)
        dono = db.scalar(stmt)
        if dono:
            raise RegraViolada("veiculo_em_uso", f"O veículo {v.codigo_interno} já está vinculado a {dono}.", status=409)
    if base_id is not None:
        b = db.get(BaseOperacional, base_id)
        if b is None or b.orgao_id != orgao_id:
            raise RegraViolada("base_invalida", "A base precisa existir e ser do mesmo órgão do agente.")


@router.get("", response_model=Pagina[AgenteOut])
def listar(
    db: DB,
    ctx: Ctx,
    q: str | None = None,
    categoria: Annotated[list[CategoriaAgente], Query()] = [],
    situacao: Annotated[list[SituacaoAgente], Query()] = [],
    orgao_id: Annotated[list[int], Query()] = [],
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(25, ge=1, le=200),
):
    stmt = select(Agente.id)
    if ctx.restrito:
        stmt = stmt.where(Agente.orgao_id == ctx.orgao_id)
    if q:
        stmt = stmt.where(or_(Agente.nome.ilike(f"%{q}%"), Agente.matricula.ilike(f"%{q}%"), Agente.equipe.ilike(f"%{q}%")))
    if categoria:
        stmt = stmt.where(Agente.categoria.in_(categoria))
    if situacao:
        stmt = stmt.where(Agente.situacao.in_(situacao))
    if orgao_id:
        stmt = stmt.where(Agente.orgao_id.in_(orgao_id))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    ids = db.scalars(stmt.order_by(Agente.nome).offset((pagina - 1) * por_pagina).limit(por_pagina)).all()
    por_id = {a.id: a for a in db.scalars(select(Agente).where(Agente.id.in_(ids))).unique()}
    return Pagina(itens=[_out(por_id[i]) for i in ids], total=total, pagina=pagina, por_pagina=por_pagina)


@router.post("", response_model=AgenteOut, status_code=201)
def criar(body: AgenteIn, db: DB, ctx: Ctx):
    ctx.exigir_alterar(body.orgao_id)
    if db.get(Orgao, body.orgao_id) is None:
        raise RegraViolada("orgao_invalido", "Órgão não encontrado.")
    _validar_vinculos(db, body.orgao_id, body.veiculo_id, body.base_id)
    a = Agente(**body.model_dump())
    a.matricula = a.matricula.strip().upper()
    db.add(a)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise RegraViolada("matricula_duplicada", "Já existe agente com esta matrícula.", status=409)
    db.commit()
    db.refresh(a)
    return _out(a)


@router.get("/{agente_id}", response_model=AgenteOut)
def ver(agente_id: int, db: DB, ctx: Ctx):
    a = db.get(Agente, agente_id)
    if a is None or (ctx.restrito and a.orgao_id != ctx.orgao_id):
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Agente não encontrado."})
    return _out(a)


@router.patch("/{agente_id}", response_model=AgenteOut)
def editar(agente_id: int, body: AgentePatch, db: DB, ctx: Ctx):
    a = db.get(Agente, agente_id)
    if a is None or (ctx.restrito and a.orgao_id != ctx.orgao_id):
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Agente não encontrado."})
    ctx.exigir_alterar(a.orgao_id)
    dados = body.model_dump(exclude_unset=True)
    _validar_vinculos(db, a.orgao_id, dados.get("veiculo_id", None), dados.get("base_id", None), a.id)
    for k, v in dados.items():
        setattr(a, k, v)
    db.commit()
    db.refresh(a)
    return _out(a)
