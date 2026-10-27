"""API da Parte 3, fase 13 (extras): fim de vida útil (X3), monitor dos modelos (X4) e relatório semanal (X5)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.preditivo import monitor, relatorio, vida_util

router = APIRouter(tags=["preditivo: extras"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/equipamentos/fim-de-vida")
def fim_de_vida(db: DB, tipo: str | None = None, regiao: str | None = None, limite: Annotated[int, Query(ge=1, le=500)] = 100):
    """X3: equipamentos que vale trocar em vez de continuar consertando, com o motivo."""
    r = vida_util.obter(db, limite=500)
    itens = [x for x in r["itens"] if (not tipo or x["tipo"] == tipo) and (not regiao or x["regiao"] == regiao)][:limite]
    return {**r, "itens": itens}


@router.get("/modelos/monitor")
def monitor_modelos(db: DB):
    """X4: os modelos continuam bons na operação? Idade, desempenho conferido e deriva dos dados."""
    return monitor.avaliar(db)


@router.get("/relatorio/semanal")
def relatorio_semanal(db: DB):
    """X5: relatório da semana que passou e das próximas, no formato do briefing."""
    return relatorio.montar(db)


@router.get("/relatorio/semanal.md", response_class=PlainTextResponse)
def relatorio_semanal_md(db: DB):
    return PlainTextResponse(relatorio.montar(db)["markdown"], media_type="text/markdown; charset=utf-8")
