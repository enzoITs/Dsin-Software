"""Espera o Postgres aceitar conexões (o podman-compose não respeita healthcheck em depends_on)."""

import sys
import time

from sqlalchemy import text

from app.db import engine

for tentativa in range(60):
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        print("[banco] pronto")
        sys.exit(0)
    except Exception:
        time.sleep(2)
print("[banco] não respondeu em 2 minutos")
sys.exit(1)
