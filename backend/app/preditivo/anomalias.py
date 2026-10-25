"""Roda os detectores de P5 sobre o banco e mantém os alertas ANOMALIA_* da central.

Abre (ou atualiza) um alerta por anomalia encontrada, pelo motor da Parte 2, e resolve os que
não aparecem mais. Roda a cada 5 minutos no agendador da API.
"""

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain import limites
from app.models import Alerta, Equipamento
from app.models.enums import TipoAlerta as R
from app.preditivo import p5
from app.services import motor

METODO_EQUIP = "Decomposição sazonal robusta (STL) e escore robusto dos resíduos; perfil diário no Isolation Forest"
METODO_REGIAO = "Ocorrências observadas acima do limite superior do intervalo de 90% da previsão (P2)"


def _series(db: Session, agora: pd.Timestamp) -> dict[tuple[int, str], pd.Series]:
    r = db.execute(text("""SELECT equipamento_id, metrica, em, valor FROM serie_equipamento_hora
                           WHERE em >= :a AND em < :b ORDER BY equipamento_id, metrica, em"""),
                   {"a": agora - pd.Timedelta(days=p5.DIAS_REFERENCIA), "b": agora})
    df = pd.DataFrame(r.fetchall(), columns=["equipamento_id", "metrica", "em", "valor"])
    if df.empty:
        return {}
    df["em"] = pd.to_datetime(df.em, utc=True)
    return {(int(e), m): g.set_index("em").valor.astype(float) for (e, m), g in df.groupby(["equipamento_id", "metrica"])}


def equipamentos(db: Session, agora: pd.Timestamp) -> list[dict]:
    series = _series(db, agora)
    achados = []
    for metrica in sorted({m for _, m in series}):
        da_metrica = {k: s for k, s in series.items() if k[1] == metrica}
        iso = p5.isolation_forest(da_metrica, agora)
        for (eid, m), s in da_metrica.items():
            d = p5.detectar_serie(s, agora, m)
            if d is None:
                continue
            d["isolation_forest"] = iso.get((eid, m), {})
            achados.append({"equipamento_id": eid, "metrica": m, **d})
    return achados


def regioes(db: Session, agora: pd.Timestamp, horas_seguidas: int) -> list[dict]:
    """Para cada hora passada, a previsão de P2 feita na origem mais recente antes dela."""
    prev = pd.DataFrame(db.execute(text("""
        SELECT DISTINCT ON (p.regiao_id, p.horizonte_inicio) p.regiao_id, r.nome regiao, p.horizonte_inicio em,
               p.valor previsto, p.faixa_superior superior
        FROM previsao p JOIN regiao r ON r.id = p.regiao_id
        WHERE p.modulo = 'P2' AND p.horizonte_inicio >= :a AND p.horizonte_fim <= :b
          AND (p.detalhe->>'origem')::timestamptz <= p.horizonte_inicio
        ORDER BY p.regiao_id, p.horizonte_inicio, (p.detalhe->>'origem')::timestamptz DESC"""),
        {"a": agora - pd.Timedelta(hours=24), "b": agora}).mappings().all())
    if prev.empty:
        return []
    obs = pd.DataFrame(db.execute(text("""
        SELECT o.regiao_id, date_trunc('hour', o.inicio_em) em, count(*) n FROM ocorrencia o
        WHERE o.inicio_em >= :a AND o.inicio_em < :b AND o.regiao_id IS NOT NULL GROUP BY 1, 2"""),
        {"a": agora - pd.Timedelta(hours=24), "b": agora}).mappings().all())
    prev["em"] = pd.to_datetime(prev.em, utc=True)
    if not obs.empty:
        obs["em"] = pd.to_datetime(obs.em, utc=True)
    achados = []
    for (rid, nome), x in prev.groupby(["regiao_id", "regiao"]):
        x = x.set_index("em").sort_index()
        o = (obs[obs.regiao_id == rid].set_index("em").n if not obs.empty else pd.Series(dtype=float))
        o = o.reindex(x.index, fill_value=0).astype(float)
        d = p5.detectar_regiao(o, x.previsto, x.superior, horas_seguidas)
        if d:
            achados.append({"regiao_id": int(rid), "regiao": nome, **d})
    return achados


def verificar(db: Session, agora: datetime | None = None) -> dict:
    cfg = limites.carregar(db)
    agora_ts = pd.Timestamp(agora or datetime.now(timezone.utc)).tz_convert("UTC").floor("h")
    quando = agora_ts.to_pydatetime()
    vistas: set[str] = set()
    abertas = novas = 0

    codigos = dict(db.execute(text("SELECT id, codigo_interno FROM equipamento")).all())
    for a in equipamentos(db, agora_ts):
        e = db.get(Equipamento, a["equipamento_id"])
        if e is None:
            continue
        k = motor.chave(R.anomalia_equipamento, "eq", f"{e.id}:{a['metrica']}")
        vistas.add(k)
        msg = p5.descrever(codigos.get(e.id, str(e.id)), a["metrica"], a)
        ja = db.scalar(select(Alerta.id).where(Alerta.chave == k, Alerta.resolvido_em.is_(None)))
        al = motor.abrir(db, R.anomalia_equipamento, k, msg, equipamento=e, agora=quando, correlacionar=False,
                         dados={"anomalia": {**a, "metodo": METODO_EQUIP}})
        abertas += al is not None
        novas += al is not None and ja is None

    for a in regioes(db, agora_ts, cfg["prev_p5_horas_seguidas"]):
        k = motor.chave(R.anomalia_regiao, "regiao", a["regiao"])
        vistas.add(k)
        pt = db.execute(text("SELECT ST_X(ST_PointOnSurface(geom)), ST_Y(ST_PointOnSurface(geom)) FROM regiao WHERE id = :i"),
                        {"i": a["regiao_id"]}).one()
        msg = (f"{a['regiao']}: {a['observado']:.0f} ocorrências nas últimas {a['horas']} h, acima do previsto "
               f"({a['previsto']:.0f}; máximo esperado {a['superior']:.0f})")
        ja = db.scalar(select(Alerta.id).where(Alerta.chave == k, Alerta.resolvido_em.is_(None)))
        al = motor.abrir(db, R.anomalia_regiao, k, msg, regiao=a["regiao"], lon=pt[0], lat=pt[1], agora=quando,
                         correlacionar=False, dados={"anomalia": {**a, "metodo": METODO_REGIAO}})
        abertas += al is not None
        novas += al is not None and ja is None

    sumiram = [k for (k,) in db.execute(select(Alerta.chave).where(
        Alerta.tipo.in_([R.anomalia_equipamento, R.anomalia_regiao]), Alerta.resolvido_em.is_(None))) if k not in vistas]
    resolvidas = motor.resolver_chaves(db, sumiram, "Voltou ao padrão esperado", quando)
    db.commit()
    return {"anomalias": abertas, "novas": novas, "resolvidas": resolvidas}
