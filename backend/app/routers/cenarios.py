"""Cenários "e se" (C1): simular mudanças nas próximas 72 h, salvar com nome e rever depois."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.models import Cenario
from app.preditivo import cenarios

router = APIRouter(tags=["preditivo: cenários"])
DB = Annotated[Session, Depends(get_db)]


class EventoIn(BaseModel):
    nome: str | None = Field(None, max_length=160)
    bairro_id: int | None = None
    lat: float | None = None
    lon: float | None = None
    publico: int = Field(ge=0, le=500_000)
    inicio: datetime | None = None
    fim: datetime | None = None
    raio_m: int = Field(2000, ge=100, le=10_000)


class ClimaIn(BaseModel):
    inicio: datetime | None = None
    fim: datetime | None = None
    chuva_mm: float | None = Field(None, ge=0, le=150)
    temperatura_c: float | None = Field(None, ge=-5, le=50)
    tempestade: bool | None = None


class EquipesIn(BaseModel):
    regiao: str
    delta: int = Field(ge=-20, le=20)
    inicio: datetime | None = None
    fim: datetime | None = None
    orgao: str | None = None


class SelecaoEquipamentosIn(BaseModel):
    codigos: list[str] | None = Field(None, max_length=200)
    regiao: str | None = None
    prefixo: str | None = None
    quantidade: int = Field(5, ge=1, le=200)


class CenarioIn(BaseModel):
    eventos: list[EventoIn] = Field(default_factory=list, max_length=10)
    cancelar_eventos: list[int] = Field(default_factory=list, max_length=50)
    clima: list[ClimaIn] = Field(default_factory=list, max_length=10)
    equipes: list[EquipesIn] = Field(default_factory=list, max_length=20)
    equipamentos_fora: SelecaoEquipamentosIn | None = None
    manutencoes: SelecaoEquipamentosIn | None = None


class SalvarIn(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    descricao: str | None = Field(None, max_length=1000)
    parametros: CenarioIn


def _simular(db: Session, params: CenarioIn) -> dict:
    try:
        return cenarios.simular(db, params.model_dump(mode="json", exclude_none=True))
    except cenarios.CenarioInvalido as exc:
        raise HTTPException(422, {"codigo": "cenario_invalido", "mensagem": str(exc)})


def _json(c: Cenario, completo: bool = False) -> dict:
    r = c.resultado or {}
    base = {"id": c.id, "nome": c.nome, "descricao": c.descricao, "criado_por": c.criado_por, "criado_em": c.criado_em,
            "frases": r.get("frases", []), "origem": r.get("origem")}
    return {**base, "parametros": c.parametros, "resultado": r} if completo else base


@router.post("/cenarios/simular")
def simular(body: CenarioIn, db: DB):
    """Roda P2, P3 e P4 sem e com as mudanças, a partir da hora atual, e compara. Não grava nada."""
    return _simular(db, body)


@router.get("/cenarios/opcoes")
def opcoes(db: DB):
    """O que a tela de cenários oferece: regiões, bairros, eventos das próximas 72 h e tipos de equipamento fixo."""
    agora = datetime.now(timezone.utc)
    return {
        "regioes": [r for (r,) in db.execute(text("SELECT nome FROM regiao ORDER BY nome"))],
        "bairros": [dict(x) for x in db.execute(text("""
            SELECT b.id, b.nome, b.regiao FROM bairro b JOIN cidade c ON c.id = b.cidade_id AND c.tem_lista_bairros
            WHERE b.geom IS NOT NULL ORDER BY b.regiao, b.nome""")).mappings()],
        "eventos": [dict(x) for x in db.execute(text("""
            SELECT id, nome, local_nome, inicio_em, fim_em, publico_estimado FROM evento_cidade
            WHERE fim_em > :a AND inicio_em < :b ORDER BY inicio_em"""), {"a": agora, "b": agora + timedelta(hours=72)}).mappings()],
        "tipos": [dict(x) for x in db.execute(text("""
            SELECT prefixo, nome FROM tipo_equipamento WHERE mobilidade::text = 'fixo' ORDER BY nome""")).mappings()],
    }


@router.get("/cenarios")
def listar(db: DB):
    return [_json(c) for c in db.scalars(select(Cenario).order_by(Cenario.id.desc()).limit(100))]


@router.post("/cenarios", status_code=201)
def salvar(body: SalvarIn, db: DB, ctx: Ctx):
    """Simula e salva com nome (o resultado fica guardado como estava no momento)."""
    if ctx.perfil == "prometheus":
        raise HTTPException(403, {"codigo": "sem_permissao", "mensagem": "Só pessoas salvam cenários."})
    r = _simular(db, body.parametros)
    c = Cenario(nome=body.nome.strip(), descricao=body.descricao, parametros=body.parametros.model_dump(mode="json", exclude_none=True),
                resultado=r, criado_por=ctx.usuario)
    db.add(c)
    db.commit()
    return _json(c, completo=True)


@router.get("/cenarios/{cenario_id}")
def ver(cenario_id: int, db: DB):
    c = db.get(Cenario, cenario_id)
    if c is None:
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Cenário não encontrado."})
    return _json(c, completo=True)


@router.delete("/cenarios/{cenario_id}", status_code=204)
def remover(cenario_id: int, db: DB, ctx: Ctx):
    c = db.get(Cenario, cenario_id)
    if c is None:
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Cenário não encontrado."})
    if ctx.perfil != "gestor" and c.criado_por != ctx.usuario:
        raise HTTPException(403, {"codigo": "sem_permissao", "mensagem": "Só quem criou ou o gestor remove o cenário."})
    db.delete(c)
    db.commit()
