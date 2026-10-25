"""Publica eventos de mudança de situação para o PROMETHEUS via webhook.

Envio em segundo plano: se o destino estiver fora do ar, o cadastro não é afetado.
Os mesmos eventos ficam consultáveis em GET /eventos (lidos do histórico).
"""

import logging
import threading

import httpx

from app.config import settings

log = logging.getLogger("atalaia.eventos")


def publicar(eventos: list[dict]) -> None:
    if not eventos or not settings.webhook_url:
        return
    threading.Thread(target=_enviar, args=(eventos,), daemon=True).start()


def _enviar(eventos: list[dict]) -> None:
    for ev in eventos:
        try:
            httpx.post(settings.webhook_url, json=ev, timeout=3)
        except httpx.HTTPError as exc:
            log.warning("webhook falhou para %s: %s", ev.get("codigo_interno"), exc)
