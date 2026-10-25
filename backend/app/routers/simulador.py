"""Controle do simulador de telemetria para a demonstração."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Equipamento
from scripts.simulador_telemetria import ARQUIVO_PARADOS, parados

router = APIRouter(prefix="/simulador", tags=["simulador"])
DB = Annotated[Session, Depends(get_db)]


def _gravar(codigos: set[str]) -> None:
    ARQUIVO_PARADOS.write_text(json.dumps(sorted(codigos)))


@router.get("/parados")
def listar() -> list[str]:
    return sorted(parados())


@router.post("/parados/{codigo}")
def parar(codigo: str, db: DB) -> list[str]:
    """O simulador deixa de mandar sinal deste equipamento."""
    codigo = codigo.upper()
    if not db.scalar(select(Equipamento.id).where(Equipamento.codigo_interno == codigo)):
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": f"Equipamento {codigo} não existe."})
    atual = parados() | {codigo}
    _gravar(atual)
    return sorted(atual)


@router.delete("/parados/{codigo}")
def retomar(codigo: str) -> list[str]:
    atual = parados() - {codigo.upper()}
    _gravar(atual)
    return sorted(atual)
