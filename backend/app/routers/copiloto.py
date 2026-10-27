"""Copiloto (C3) e briefing diário (C4)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.models import Briefing
from app.preditivo import briefing, copiloto
from app.services import ia

router = APIRouter(tags=["preditivo: copiloto e briefing"])
DB = Annotated[Session, Depends(get_db)]


class MensagemIn(BaseModel):
    papel: str = Field(pattern="^(user|assistant)$")
    texto: str = Field(max_length=4000)


class PerguntaIn(BaseModel):
    pergunta: str = Field("", max_length=600)
    pronta: str | None = Field(None, max_length=40, description="Id de uma pergunta pronta (modo sem IA)")
    historico: list[MensagemIn] = Field(default_factory=list, max_length=20)


@router.get("/copiloto/perguntas-prontas")
def perguntas_prontas():
    return {"ia_disponivel": ia.disponivel(), "perguntas": copiloto.prontas()}


@router.post("/copiloto/perguntar")
def perguntar(body: PerguntaIn, db: DB):
    """Responde com os dados do sistema. Com IA, usa ferramentas sobre as previsões; sem IA, as perguntas prontas."""
    if not body.pergunta.strip() and not body.pronta:
        raise HTTPException(422, {"codigo": "pergunta_vazia", "mensagem": "Escreva uma pergunta ou escolha uma pronta."})
    return copiloto.perguntar(db, body.pergunta.strip(), [h.model_dump() for h in body.historico], body.pronta)


def _briefing_json(b: Briefing) -> dict:
    return {"id": b.id, "data": b.data, "gerado_em": b.gerado_em, "gerado_por": b.gerado_por, **(b.dados or {}),
            "markdown": b.conteudo_md}


@router.get("/briefing/hoje")
def briefing_hoje(db: DB):
    """Briefing de hoje (gerado às 6 h; se ainda não existir, é gerado agora)."""
    return _briefing_json(briefing.hoje(db))


@router.post("/briefing/gerar")
def gerar_briefing(db: DB, ctx: Ctx):
    """Refaz o briefing de hoje com os dados de agora. Só o gestor."""
    ctx.exigir_gestor()
    return _briefing_json(briefing.gerar(db, por=ctx.usuario))


@router.get("/briefing")
def listar_briefings(db: DB, limite: Annotated[int, Query(ge=1, le=90)] = 14):
    return [{"data": b.data, "titulo": (b.dados or {}).get("titulo"), "gerado_em": b.gerado_em}
            for b in db.scalars(select(Briefing).order_by(Briefing.data.desc()).limit(limite))]


@router.get("/briefing/{data}")
def ver_briefing(data: date, db: DB):
    b = db.scalar(select(Briefing).where(Briefing.data == data))
    if b is None:
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Não há briefing desse dia."})
    return _briefing_json(b)
