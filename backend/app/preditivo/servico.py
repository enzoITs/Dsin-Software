"""Serviço preditivo: treino em segundo plano e os lotes do agendador.

- Primeiro start: se ainda não há modelo treinado, a API treina sozinha em segundo plano
  (cerca de 3 minutos) e a interface mostra o progresso (`GET /modelos/treino`).
- De hora em hora: P2, P3 e P4 a partir da hora atual, alertas preventivos e acertômetro.
- Uma vez por dia (5 h): P1 a partir da meia-noite e, em seguida, P6, P7 e P8.
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import EstadoPreditivo

log = logging.getLogger("atalaia.preditivo")
_trava = threading.Lock()
_thread: dict = {"t": None}
PARADO_APOS = timedelta(minutes=10)  # "rodando" sem atualização há mais que isso: o processo morreu no meio


def estado_treino(db: Session) -> dict:
    e = db.get(EstadoPreditivo, "treino")
    v = dict(e.valor) if e else {"situacao": "nunca"}
    tem_modelo = bool(db.scalar(text("SELECT count(*) FROM modelo_versao WHERE ativo AND nome = 'ocorrencias_regiao_hora'")))
    if v.get("situacao") == "rodando" and not rodando():
        atualizado = datetime.fromisoformat(v.get("atualizado_em") or "2000-01-01T00:00:00+00:00")
        morto = v.get("pid") and not _processo_vivo(v["pid"]) and os.path.exists("/proc")
        if morto or datetime.now(timezone.utc) - atualizado > PARADO_APOS:
            v["situacao"] = "interrompido"
    v["tem_modelo"] = tem_modelo
    v["rodando_aqui"] = rodando()
    return v


def _processo_vivo(pid) -> bool:
    return bool(pid) and pid != os.getpid() and os.path.exists(f"/proc/{pid}")


def rodando() -> bool:
    t = _thread["t"]
    return t is not None and t.is_alive()


def _treinar(so_novos: bool = False) -> None:
    from app.preditivo import treinar

    try:
        if so_novos:
            treinar.treinar_novos(log=lambda m: log.info(m))
        else:
            treinar.treinar(todos=True, log=lambda m: log.info(m))
        with SessionLocal() as db:
            pos_lote(db)
            from app.preditivo import descoberta

            descoberta.obter(db, refazer=True)
    except Exception:
        log.exception("treino falhou")


def iniciar_treino(so_novos: bool = False) -> bool:
    """Dispara o treino completo (ou só dos modelos que faltam) numa thread. Falso se já há um em andamento neste processo."""
    with _trava:
        if rodando():
            return False
        _thread["t"] = threading.Thread(target=_treinar, kwargs={"so_novos": so_novos}, name="treino-preditivo", daemon=True)
        _thread["t"].start()
        return True


def treinar_se_preciso() -> bool:
    """No start da API: treina em segundo plano se ainda não há modelo e há histórico para treinar."""
    from app.preditivo import treinar

    with SessionLocal() as db:
        st = estado_treino(db)
        tem_historico = db.get(EstadoPreditivo, "cidade") is not None
        falta = treinar.faltando(db) if st["tem_modelo"] else []
    if not tem_historico:
        return False
    if st["tem_modelo"]:
        if falta and not (st.get("situacao") == "rodando" and _processo_vivo(st.get("pid"))):
            log.info("modelos novos sem treino (%s): treinando em segundo plano", ", ".join(falta))
            return iniciar_treino(so_novos=True)
        return False
    if st.get("situacao") == "rodando" and _processo_vivo(st.get("pid")):
        return False  # o comando de treino está rodando em outro processo
    # "rodando" de um processo que não existe mais: o treino morreu junto com ele (por exemplo, no --reload)
    log.info("sem modelo treinado: treinando em segundo plano")
    return iniciar_treino()


def pos_lote(db: Session) -> dict:
    """Depois de cada lote de previsões: alertas preventivos e conferência do que já aconteceu."""
    from app.preditivo import acertometro, preventivos, retorno

    return {"conferidas": acertometro.conferir(db), "preventivos": preventivos.verificar(db), "retorno": retorno.conferir(db)}


def lote_hora() -> dict:
    from app.preditivo import planejamento, prever

    if rodando():
        return {"pulado": "treino em andamento"}
    t0 = time.time()
    with SessionLocal() as db:
        res = prever.prever_p2_p3(db)
        if res.get("p2"):
            res["p4"] = planejamento.prever_p4(db)["recomendacoes"]
        res.update(pos_lote(db))
    res["segundos"] = round(time.time() - t0, 1)
    log.info("lote de previsões (hora): %s", res)
    return res


def lote_dia() -> dict:
    from app.preditivo import diarias, prever
    from app.preditivo import variaveis as V

    if rodando():
        return {"pulado": "treino em andamento"}
    t0 = time.time()
    with SessionLocal() as db:
        f = V.carregar(db)
        res = {"p1": prever.prever_p1(db, f)}
        res.update(diarias.lote(db, f))
        res.update(pos_lote(db))
    res["segundos"] = round(time.time() - t0, 1)
    log.info("lote de previsões (dia): %s", res)
    return res
