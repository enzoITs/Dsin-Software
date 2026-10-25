"""API da Parte 3: planejamento de equipes (P4).

GET devolve o plano para as próximas 72 h a partir das últimas previsões de P2 e P3: demanda,
escala atual, alocação recomendada e o risco não coberto antes e depois. POST recalcula com
restrições ajustadas pelo gestor (e grava como recomendações, se pedido).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.models import Recomendacao
from app.models.enums import EstadoRecomendacao
from app.preditivo import planejamento

router = APIRouter(tags=["preditivo: planejamento"])
DB = Annotated[Session, Depends(get_db)]


class RecalcularIn(BaseModel):
    max_deslocamentos: int | None = Field(None, ge=0, le=30, description="Equipes que podem trocar de região por período")
    min_por_regiao: int | None = Field(None, ge=0, le=10, description="Mínimo de equipes em cada região")
    regioes_fixas: list[str] = Field(default_factory=list, description="Regiões que não cedem equipes")
    salvar: bool = Field(False, description="Grava o plano como recomendações pendentes (só o gestor)")


def _pendentes(db: Session) -> list[dict]:
    return [{"id": r.id, "texto": r.texto, "estado": r.estado.value, "parametros": r.parametros,
             "impacto_estimado": r.impacto_estimado, "previsao_id": r.previsao_id}
            for r in db.scalars(select(Recomendacao).where(Recomendacao.tipo == "REFORCAR_EQUIPES",
                                                           Recomendacao.estado == EstadoRecomendacao.pendente)
                                .order_by(Recomendacao.id))]


def _sem_previsao():
    raise HTTPException(409, {"codigo": "sem_previsao",
                              "mensagem": "Ainda não há previsões de ocorrências. Rode o treino (python -m app.preditivo.treinar --todos)."})


@router.get("/planejamento/equipes")
def plano(db: DB):
    origem = planejamento.ultima_origem(db)
    if not origem:
        _sem_previsao()
    return {"origem": origem, **planejamento.resumo_json(planejamento.planejar(db, origem)), "recomendacoes": _pendentes(db)}


@router.post("/planejamento/equipes/recalcular")
def recalcular(body: RecalcularIn, db: DB, ctx: Ctx):
    origem = planejamento.ultima_origem(db)
    if not origem:
        _sem_previsao()
    planos = planejamento.planejar(db, origem, body.max_deslocamentos, body.min_por_regiao, set(body.regioes_fixas) or None)
    gravado = None
    if body.salvar:
        ctx.exigir_gestor()
        gravado = planejamento.gravar(db, planos, origem)
    return {"origem": origem, **planejamento.resumo_json(planos), "gravado": gravado,
            "recomendacoes": _pendentes(db) if body.salvar else []}
