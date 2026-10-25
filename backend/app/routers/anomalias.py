"""API da Parte 3: anomalias (P5), com o gráfico esperado × observado de cada uma."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.models import Alerta, Equipamento
from app.models.enums import TipoAlerta
from app.preditivo import anomalias

router = APIRouter(tags=["preditivo: anomalias"])
DB = Annotated[Session, Depends(get_db)]
TIPOS = [TipoAlerta.anomalia_equipamento, TipoAlerta.anomalia_regiao]


@router.get("/anomalias")
def listar(db: DB, abertas: bool = True, limite: Annotated[int, Query(ge=1, le=500)] = 100):
    q = select(Alerta).where(Alerta.tipo.in_(TIPOS))
    if abertas:
        q = q.where(Alerta.resolvido_em.is_(None))
    saida = []
    for a in db.scalars(q.order_by(Alerta.criado_em.desc()).limit(limite)).unique():
        an = (a.dados or {}).get("anomalia", {})
        eq = db.get(Equipamento, a.equipamento_id) if a.equipamento_id else None
        saida.append({
            "id": a.id, "tipo": a.tipo.value, "mensagem": a.mensagem, "nivel": a.nivel.value, "estado": a.estado.value,
            "criado_em": a.criado_em, "resolvido_em": a.resolvido_em, "regiao": a.regiao,
            "equipamento": {"id": eq.id, "codigo": eq.codigo_interno} if eq else None,
            "deteccao": an.get("tipo"), "metrica": an.get("metrica"), "metodo": an.get("metodo"),
            "razao_esperado": an.get("razao"), "escore": an.get("z"), "isolation_forest": an.get("isolation_forest"),
            "grafico": an.get("grafico", []),
        })
    return saida


@router.post("/anomalias/verificar")
def verificar(db: DB, ctx: Ctx):
    ctx.exigir_gestor()
    return anomalias.verificar(db)
