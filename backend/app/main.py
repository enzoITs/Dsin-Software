import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app import jobs
from app.config import settings
from app.domain.estados import RegraViolada
from app.services import ia as ia_servico
from app.routers import (agentes, alertas, anomalias, central, equipamentos, ia, modelos, operacao, planejamento, preditivo, previsoes,
                         simulador, tipos)
from app.services.barramento import barramento

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await barramento.iniciar(settings.redis_url)
    if settings.scheduler_enabled:
        jobs.iniciar()
    yield
    jobs.parar()
    await barramento.parar()


app = FastAPI(
    title="Atalaia — Inventário, Central de Operações e Cidade Preditiva",
    version="0.3.0",
    description=(
        "API única do Atalaia. Parte 1: inventário (painel web, modo campo). Parte 2: central de operações "
        "(motor de interpretação, alertas priorizados, regiões, tempo real em /ws/eventos). "
        "Parte 3: cidade preditiva (ocorrências, calendário, clima, eventos, previsões explicadas). "
        "O PROMETHEUS consome os mesmos endpoints."
    ),
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=2000)


@app.exception_handler(RegraViolada)
async def regra_violada(_: Request, exc: RegraViolada):
    return JSONResponse(
        status_code=exc.status,
        content={"detail": {"codigo": exc.codigo, "mensagem": exc.mensagem, "detalhes": exc.detalhes}},
    )


@app.exception_handler(RequestValidationError)
async def validacao(_: Request, exc: RequestValidationError):
    detalhes = [
        {"campo": ".".join(str(p) for p in e["loc"][1:]) or None, "mensagem": e["msg"]} for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": {"codigo": "dados_invalidos", "mensagem": "Confira os campos destacados.", "detalhes": detalhes}},
    )


# previsoes antes de equipamentos: /equipamentos/risco não pode cair em /equipamentos/{id}
for r in (previsoes.router, equipamentos.router, tipos.router, agentes.router, operacao.router, alertas.router, central.router,
          simulador.router, ia.router, preditivo.router, planejamento.router, anomalias.router, modelos.router):
    app.include_router(r)


Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.uploads_dir), name="uploads")


@app.get("/saude-api", tags=["apoio"])
def saude_api() -> dict:
    return {"ok": True, "ia_disponivel": ia_servico.disponivel()}


@app.post("/admin/recalcular", tags=["apoio"])
def recalcular() -> dict:
    """Força o recálculo de score, manutenção e alertas (o job roda a cada minuto)."""
    return jobs.recalcular_tudo()
