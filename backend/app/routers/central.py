"""API da Central de Operações (Parte 2).

A tela carrega o estado inicial por aqui e, a partir daí, só recebe mudanças pelo
WebSocket /ws/eventos. Indicadores e regiões são recalculados a cada 5 s pela tela.
"""

import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.domain import limites
from app.domain.estados import RegraViolada
from app.models import ConfigMotor
from app.routers.equipamentos import filtros_da_query
from app.schemas.api import IncidenteIn
from app.services import central, resumo, simulacao
from app.services import equipamentos as svc
from app.services.barramento import barramento

router = APIRouter(tags=["central"])
DB = Annotated[Session, Depends(get_db)]
F = Annotated[svc.Filtros, Depends(filtros_da_query)]


def _restrito(ctx) -> int | None:
    return ctx.orgao_id if ctx.restrito else None


@router.get("/central/estado")
def estado(db: DB, ctx: Ctx, f: F):
    """Estado inicial do mapa em GeoJSON: equipamentos (com a cor da pior situação) e agentes em atividade."""
    agora = datetime.now(timezone.utc)
    r = _restrito(ctx)
    eq = central.feicoes_equipamentos(db, f, r, agora=agora)
    ag = central.feicoes_agentes(db, f, r, agora=agora)
    return {
        "em": agora.isoformat(),
        "equipamentos": {"type": "FeatureCollection", "features": eq},
        "agentes": {"type": "FeatureCollection", "features": ag},
        "filtros": f.como_dict(),
    }


@router.get("/central/regioes.geojson")
def regioes_geojson(db: DB):
    return central.regioes_geojson(db)


@router.get("/central/calor")
def calor(db: DB, ctx: Ctx, f: F):
    """Alertas das últimas 24 h como pontos com peso, para a camada de mapa de calor."""
    return central.calor_alertas(db, f, _restrito(ctx))


@router.get("/indicadores")
def indicadores(db: DB, ctx: Ctx, f: F):
    """Indicadores do topo, com a variação na última hora. Mesmo cálculo em todas as telas."""
    return central.indicadores(db, f, _restrito(ctx))


@router.get("/regioes/saude")
def regioes_saude(db: DB, ctx: Ctx, f: F):
    """Índice de saúde de cada região, da pior para a melhor, com o motivo principal."""
    return central.saude_regioes(db, f, _restrito(ctx))


@router.get("/manutencao/fila")
def fila(db: DB, ctx: Ctx, f: F, limite: int = Query(300, ge=1, le=2000)):
    """Imediata, vencida (mais atrasada primeiro) e próxima em 7 dias (mais próxima primeiro)."""
    return central.fila_manutencao(db, f, _restrito(ctx), limite=limite)


@router.get("/linha-do-tempo")
def linha_do_tempo(
    db: DB, ctx: Ctx, f: F,
    em: datetime | None = None,
    minutos_atras: int | None = Query(None, ge=0, le=60),
):
    """Estado da cidade num momento da última hora."""
    agora = datetime.now(timezone.utc)
    if em is None:
        em = agora - timedelta(minutes=minutos_atras or 0)
    if em.tzinfo is None:
        em = em.replace(tzinfo=timezone.utc)
    em = max(min(em, agora), agora - timedelta(hours=1))
    return central.linha_do_tempo(db, em, f, _restrito(ctx), agora)


@router.get("/resumo-turno")
def resumo_turno(db: DB, ia: bool = True):
    """O que mudou na última hora. Texto da IA quando disponível; senão, modelo de texto."""
    return resumo.resumo_turno(db, usar_ia=ia)


@router.get("/central/perguntar")
def perguntar(db: DB, q: str = Query(..., min_length=2, max_length=300)):
    """'O que está acontecendo no Centro?' responde com alertas, índice e agentes da região."""
    return resumo.perguntar(db, q)


@router.get("/central/configuracao")
def ver_configuracao(db: DB):
    return {"valores": limites.carregar(db, forcar=True), "padrao": limites.PADRAO}


@router.put("/central/configuracao")
def mudar_configuracao(db: DB, ctx: Ctx, valores: Annotated[dict[str, Any], Body()]):
    """Ajusta limites do motor (50 m, 3 vezes, 15 min, 15%...) sem mexer no código. Só o gestor."""
    ctx.exigir_gestor()
    desconhecidas = sorted(set(valores) - set(limites.PADRAO))
    if desconhecidas:
        raise RegraViolada("chave_desconhecida", f"Limites desconhecidos: {', '.join(desconhecidas)}.")
    for k, v in valores.items():
        if type(v) is not type(limites.PADRAO[k]) and not (isinstance(v, (int, float)) and isinstance(limites.PADRAO[k], (int, float))):
            raise RegraViolada("valor_invalido", f"{k} precisa ser do mesmo tipo do padrão ({limites.PADRAO[k]!r}).")
        reg = db.get(ConfigMotor, k)
        if reg is None:
            db.add(ConfigMotor(chave=k, valor=v))
        else:
            reg.valor = v
    db.commit()
    limites.limpar_cache()
    return {"valores": limites.carregar(db, forcar=True)}


# ---------- Simulação ----------


@router.post("/simulacao/incidente", tags=["simulação"])
def simular(body: IncidenteIn, db: DB, ctx: Ctx):
    """Provoca furto, falha, silêncio, queda de energia, sinal degradado ou região sem agentes. Funciona sem internet."""
    if ctx.perfil == "prometheus":
        raise RegraViolada("sem_permissao", "O PROMETHEUS não simula incidentes.", status=403)
    res = simulacao.simular(db, body.tipo, body.regiao, body.quantidade)
    db.commit()
    return res


@router.post("/simulacao/restaurar", tags=["simulação"])
def restaurar(db: DB):
    """Desfaz tudo o que foi simulado; o motor resolve os alertas."""
    res = simulacao.restaurar(db)
    db.commit()
    return res


@router.get("/simulacao/estado", tags=["simulação"])
def estado_simulacao():
    return simulacao.ler_estado()


# ---------- Tempo real ----------


@router.get("/central/status")
def status():
    return {"canal": barramento.modo, "paineis_conectados": barramento.conectados}


@router.websocket("/ws/eventos")
async def eventos(ws: WebSocket):
    """Cada mensagem é uma lista de eventos: alerta (novo, atualizado, resolvido, tocar),
    equipamentos (feições atualizadas), posicoes (móveis e agentes), agentes e recarregar."""
    await ws.accept()
    fila = barramento.assinar()
    await ws.send_text(json.dumps([{"tipo": "ola", "canal": barramento.modo, "em": datetime.now(timezone.utc).isoformat()}]))

    async def ouvir_cliente():
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            while True:
                await ws.receive_text()

    leitor = asyncio.create_task(ouvir_cliente())
    try:
        while not leitor.done():
            try:
                msg = await asyncio.wait_for(fila.get(), timeout=20)
            except asyncio.TimeoutError:
                msg = '[{"tipo": "pulso"}]'
            await ws.send_text(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        leitor.cancel()
        barramento.cancelar(fila)
