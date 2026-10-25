"""Prepara o banco para a Parte 3 (roda na subida, depois de preparar_central).

Uso: python -m scripts.preparar_preditivo

Idempotente: grava o calendário (2 anos para trás e 1 para a frente) e a previsão de clima
das próximas 72 horas onde ainda não houver.
"""

import time
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.preditivo import calendario, clima
from app.routers.preditivo import cidade_principal


def preparar() -> None:
    t0 = time.time()
    agora = datetime.now(timezone.utc)
    hoje = agora.astimezone(clima.FUSO).date()
    with SessionLocal() as db:
        n_cal = calendario.garantir(db, hoje - timedelta(days=730), hoje + timedelta(days=365))
        n_clima = clima.garantir_previsao(db, cidade_principal(db), agora, 72)
        db.commit()
    print(f"[preditivo] calendário: {n_cal} dias; clima previsto: {n_clima} horas novas; {time.time() - t0:.1f}s")


if __name__ == "__main__":
    preparar()
