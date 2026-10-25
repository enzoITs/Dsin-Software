"""Canal de eventos em tempo real: motor -> painéis abertos (WebSocket) e PROMETHEUS (webhook).

O código de negócio só chama `emitir(db, evento)` ou `tocar(db, equipamento_id)` dentro da
transação. Os eventos saem depois do commit (nada é publicado se a transação falhar).

Com REDIS_URL definido, os eventos passam pelo Redis (pub/sub) e qualquer processo da API
entrega aos seus WebSockets. Sem Redis, a entrega é direta no próprio processo.
"""

import asyncio
import json
import logging
from datetime import date, datetime

from sqlalchemy import event
from sqlalchemy.orm import Session

log = logging.getLogger("atalaia.barramento")
CANAL = "atalaia:eventos"
LIMITE_FILA = 200


def _json(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "value"):
        return obj.value
    raise TypeError(type(obj))


class Barramento:
    def __init__(self) -> None:
        self._filas: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._redis = None
        self._tarefa: asyncio.Task | None = None
        self.modo = "memoria"

    async def iniciar(self, redis_url: str = "") -> None:
        self._loop = asyncio.get_running_loop()
        if not redis_url:
            return
        try:
            import redis
            import redis.asyncio as aredis

            self._redis = redis.Redis.from_url(redis_url, socket_timeout=2)
            self._redis.ping()
            assinante = aredis.Redis.from_url(redis_url)
            self._tarefa = asyncio.create_task(self._ouvir_redis(assinante))
            self.modo = "redis"
            log.info("canal de eventos via Redis em %s", redis_url)
        except Exception as exc:  # Redis fora do ar: segue em memória
            log.warning("Redis indisponível (%s); eventos entregues só neste processo", exc)
            self._redis = None

    async def parar(self) -> None:
        if self._tarefa:
            self._tarefa.cancel()
        self._loop = None

    async def _ouvir_redis(self, cliente) -> None:
        while True:
            try:
                pubsub = cliente.pubsub()
                await pubsub.subscribe(CANAL)
                async for msg in pubsub.listen():
                    if msg.get("type") == "message":
                        dado = msg["data"]
                        self._distribuir(dado.decode() if isinstance(dado, bytes) else dado)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("assinatura do Redis caiu (%s); reconectando", exc)
                await asyncio.sleep(2)

    # Pode ser chamado de qualquer thread (rotas síncronas, verificador).
    def publicar(self, eventos: list[dict]) -> None:
        if not eventos:
            return
        msg = json.dumps(eventos, default=_json, ensure_ascii=False)
        if self._redis is not None:
            try:
                self._redis.publish(CANAL, msg)
                return
            except Exception as exc:
                log.warning("falha ao publicar no Redis (%s); entregando localmente", exc)
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._distribuir, msg)

    def _distribuir(self, msg: str) -> None:
        for fila in list(self._filas):
            if fila.qsize() >= LIMITE_FILA:  # painel lento: descarta o mais antigo
                try:
                    fila.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            fila.put_nowait(msg)

    def assinar(self) -> asyncio.Queue:
        fila: asyncio.Queue = asyncio.Queue()
        self._filas.add(fila)
        return fila

    def cancelar(self, fila: asyncio.Queue) -> None:
        self._filas.discard(fila)

    @property
    def conectados(self) -> int:
        return len(self._filas)


barramento = Barramento()


def emitir(db: Session, evento: dict) -> None:
    db.info.setdefault("eventos", []).append(evento)


def tocar(db: Session, equipamento_id: int | None) -> None:
    """Marca o equipamento para o mapa receber a feição atualizada depois do commit."""
    if equipamento_id is not None:
        db.info.setdefault("equip_tocados", set()).add(equipamento_id)


@event.listens_for(Session, "before_commit")
def _antes_do_commit(session: Session) -> None:
    ids = session.info.pop("equip_tocados", None)
    if not ids:
        return
    from app.services import central

    try:
        session.flush()
        feicoes = central.feicoes_equipamentos(session, ids=sorted(ids))
        removidos = sorted(set(ids) - {f["properties"]["i"] for f in feicoes})
        emitir(session, {"tipo": "equipamentos", "feicoes": feicoes, "removidos": removidos})
    except Exception as exc:  # nunca derruba a transação por causa do mapa
        log.warning("não foi possível montar feições: %s", exc)


@event.listens_for(Session, "after_commit")
def _depois_do_commit(session: Session) -> None:
    eventos = session.info.pop("eventos", None)
    if not eventos:
        return
    barramento.publicar(eventos)
    from app.services import eventos as webhook

    webhook.publicar([e for e in eventos if e.get("tipo") == "alerta" and e.get("acao") in ("novo", "atualizado", "resolvido")])


@event.listens_for(Session, "after_rollback")
def _depois_do_rollback(session: Session) -> None:
    session.info.pop("eventos", None)
    session.info.pop("equip_tocados", None)
