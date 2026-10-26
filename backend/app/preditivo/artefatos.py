"""Artefatos dos modelos treinados (joblib), fora do git e regeneráveis pelo treino."""

import os
from pathlib import Path

import joblib
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModeloVersao

PASTA = Path(os.environ.get("MODELOS_DIR", Path(__file__).resolve().parents[2] / "modelos"))
_cache: dict[str, object] = {}


def salvar(objeto, nome: str, versao: str) -> str:
    PASTA.mkdir(parents=True, exist_ok=True)
    caminho = PASTA / f"{nome}_{versao}.joblib"
    joblib.dump(objeto, caminho, compress=3)
    return str(caminho)


def ativo(db: Session, nome: str) -> tuple[ModeloVersao | None, object | None]:
    """Versão ativa e o objeto carregado (em cache pelo caminho). Sem artefato no disco: (versão, None)."""
    mv = db.scalar(select(ModeloVersao).where(ModeloVersao.nome == nome, ModeloVersao.ativo).order_by(ModeloVersao.id.desc()))
    if mv is None or not mv.caminho_artefato:
        return mv, None
    if mv.caminho_artefato not in _cache:
        caminho = Path(mv.caminho_artefato)
        if not caminho.exists():  # treinado em outra máquina ou contêiner: procura pelo nome na pasta dos modelos
            caminho = PASTA / caminho.name
        if not caminho.exists():
            return mv, None
        _cache[mv.caminho_artefato] = joblib.load(caminho)
    return mv, _cache[mv.caminho_artefato]
