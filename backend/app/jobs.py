"""Tarefas automáticas.

- A cada minuto: score de saúde e status de manutenção (Parte 1).
- A cada 30 s: verificador do motor de interpretação (silêncio, prazos, agentes, regiões,
  escalonamento) e, a cada minuto, um instantâneo dos indicadores para a linha do tempo.
- A cada 5 min: detectores de anomalias da Parte 3 (P5) e alertas preventivos (PREVISAO_*).
- De hora em hora (minuto 3): previsões P2, P3 e P4, alertas preventivos e acertômetro.
- Às 5 h (horário local): previsões P1 de risco de falha.
- No start: treina em segundo plano se ainda não há modelo; refaz lotes atrasados.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.exc import OperationalError

from app.db import SessionLocal
from app.domain import derivados
from app.preditivo import servico

log = logging.getLogger("atalaia.jobs")
scheduler = BackgroundScheduler(timezone="UTC")
_ultimo_instantaneo = {"em": 0.0}


def recalcular_tudo() -> dict:
    t0 = time.time()
    res: dict = {}
    for tentativa in range(3):
        try:
            with SessionLocal() as db:
                res = derivados.recalcular(db)
                db.commit()
            break
        except OperationalError as exc:  # disputa com lotes de telemetria
            if "deadlock" not in str(exc).lower() or tentativa == 2:
                raise
            time.sleep(1)
    res["segundos"] = round(time.time() - t0, 2)
    log.info("recalculo: %s", res)
    return res


def verificar() -> dict:
    from app.services import central, motor

    t0 = time.time()
    with SessionLocal() as db:
        res = motor.verificar(db)
        db.commit()
        if time.time() - _ultimo_instantaneo["em"] >= 55:
            central.gravar_instantaneo(db)
            db.commit()
            _ultimo_instantaneo["em"] = time.time()
    res["segundos"] = round(time.time() - t0, 2)
    if any(v for k, v in res.items() if k != "segundos"):
        log.info("verificador: %s", res)
    return res


def anomalias() -> dict:
    from app.preditivo import anomalias as p5

    t0 = time.time()
    from app.preditivo import preventivos

    with SessionLocal() as db:
        res = p5.verificar(db)
        res["preventivos"] = preventivos.verificar(db)
    res["segundos"] = round(time.time() - t0, 2)
    if res.get("novas") or res.get("resolvidas"):
        log.info("anomalias: %s", res)
    return res


def previsoes_no_start() -> dict:
    """Treina se não há modelo; senão refaz o que ficou atrasado enquanto a API esteve parada."""
    import pandas as pd
    from sqlalchemy import text

    from app.preditivo import prever
    from app.preditivo import variaveis as V

    if servico.treinar_se_preciso():
        return {"treino": "iniciado"}
    with SessionLocal() as db:
        if not servico.estado_treino(db)["tem_modelo"]:
            return {}
        ultima_p1 = db.scalar(text("SELECT max(horizonte_inicio) FROM previsao WHERE modulo = 'P1'"))
        ultima_p2 = db.scalar(text("SELECT max(detalhe->>'origem') FROM previsao WHERE modulo = 'P2'"))
    agora = pd.Timestamp.now(tz="UTC")
    res = {}
    if ultima_p1 is None or pd.Timestamp(ultima_p1) < V.corte_local(prever.hoje_local(agora.to_pydatetime())):
        res["dia"] = servico.lote_dia()
    if ultima_p2 is None or pd.Timestamp(ultima_p2) < agora - pd.Timedelta(hours=1):
        res["hora"] = servico.lote_hora()
    return res


def iniciar() -> None:
    scheduler.add_job(recalcular_tudo, "interval", minutes=1, id="recalcular", max_instances=1, coalesce=True)
    scheduler.add_job(verificar, "interval", seconds=30, id="verificador", max_instances=1, coalesce=True)
    scheduler.add_job(anomalias, "interval", minutes=5, id="anomalias", max_instances=1, coalesce=True)
    scheduler.add_job(servico.lote_hora, "cron", minute=3, id="previsoes_hora", max_instances=1, coalesce=True)
    scheduler.add_job(servico.lote_dia, "cron", hour=5, minute=10, timezone="America/Sao_Paulo", id="previsoes_dia",
                      max_instances=1, coalesce=True)
    scheduler.add_job(previsoes_no_start, "date", run_date=datetime.now(timezone.utc) + timedelta(seconds=20),
                      id="previsoes_no_start")
    scheduler.start()


def parar() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
