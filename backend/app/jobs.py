"""Tarefas automáticas.

- A cada minuto: score de saúde e status de manutenção (Parte 1).
- A cada 30 s: verificador do motor de interpretação (silêncio, prazos, agentes, regiões,
  escalonamento) e, a cada minuto, um instantâneo dos indicadores para a linha do tempo.
"""

import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.exc import OperationalError

from app.db import SessionLocal
from app.domain import derivados

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


def iniciar() -> None:
    scheduler.add_job(recalcular_tudo, "interval", minutes=1, id="recalcular", max_instances=1, coalesce=True)
    scheduler.add_job(verificar, "interval", seconds=30, id="verificador", max_instances=1, coalesce=True)
    scheduler.start()


def parar() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
