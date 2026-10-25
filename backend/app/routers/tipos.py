from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.domain import schemas_tipo
from app.domain.estados import RegraViolada
from app.models import Equipamento, TipoEquipamento
from app.schemas.api import TipoIn, TipoOut

router = APIRouter(prefix="/tipos-equipamento", tags=["tipos"])
DB = Annotated[Session, Depends(get_db)]


def _out(t: TipoEquipamento, total: int) -> TipoOut:
    o = TipoOut.model_validate(t)
    o.total_equipamentos = total
    return o


@router.get("", response_model=list[TipoOut])
def listar(db: DB):
    totais = dict(db.execute(select(Equipamento.tipo_id, func.count()).group_by(Equipamento.tipo_id)).all())
    tipos = db.scalars(select(TipoEquipamento).order_by(TipoEquipamento.nome)).all()
    return [_out(t, totais.get(t.id, 0)) for t in tipos]


@router.get("/{tipo_id}", response_model=TipoOut)
def ver(tipo_id: int, db: DB):
    t = db.get(TipoEquipamento, tipo_id)
    if t is None:
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Tipo não encontrado."})
    total = db.scalar(select(func.count()).where(Equipamento.tipo_id == tipo_id))
    return _out(t, total)


def _salvar(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        campo = "prefixo" if "prefixo" in str(exc.orig) else "nome"
        raise RegraViolada(f"{campo}_duplicado", f"Já existe um tipo com este {campo}.", status=409)


@router.post("", response_model=TipoOut, status_code=201)
def criar(body: TipoIn, db: DB, ctx: Ctx):
    """Cria um tipo novo pela interface: o formulário passa a existir na hora, sem código nem migração."""
    ctx.exigir_gestor()
    schemas_tipo.validar_schema(body.schema_atributos)
    t = TipoEquipamento(**{**body.model_dump(), "schema_atributos": schemas_tipo.com_ordem(body.schema_atributos)})
    db.add(t)
    _salvar(db)
    db.commit()
    return _out(t, 0)


@router.put("/{tipo_id}", response_model=TipoOut)
def editar(tipo_id: int, body: TipoIn, db: DB, ctx: Ctx):
    """Edita o tipo. Recusa mudanças de schema que deixariam equipamentos existentes inválidos."""
    ctx.exigir_gestor()
    t = db.get(TipoEquipamento, tipo_id)
    if t is None:
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Tipo não encontrado."})
    schemas_tipo.validar_schema(body.schema_atributos)
    if schemas_tipo.com_ordem(body.schema_atributos) != t.schema_atributos:
        incompat = []
        for codigo, attrs in db.execute(
            select(Equipamento.codigo_interno, Equipamento.atributos).where(Equipamento.tipo_id == tipo_id)
        ):
            if schemas_tipo.validar_atributos(body.schema_atributos, attrs or {}):
                incompat.append(codigo)
        if incompat:
            raise RegraViolada(
                "schema_incompativel",
                f"{len(incompat)} equipamento(s) ficariam inválidos com o novo schema "
                f"(ex.: {', '.join(incompat[:5])}). Torne o campo opcional ou corrija os cadastros antes.",
                [{"codigo_interno": c} for c in incompat[:50]],
            )
    if body.mobilidade != t.mobilidade and db.scalar(select(func.count()).where(Equipamento.tipo_id == tipo_id)):
        raise RegraViolada("mobilidade_travada", "Não é possível mudar fixo/móvel de um tipo que já tem equipamentos.")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    t.schema_atributos = schemas_tipo.com_ordem(body.schema_atributos)
    _salvar(db)
    db.commit()
    total = db.scalar(select(func.count()).where(Equipamento.tipo_id == tipo_id))
    return _out(t, total)
