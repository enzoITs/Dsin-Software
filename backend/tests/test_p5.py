"""Parte 3, fase 7: P5, detecção de anomalias."""

import json

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.preditivo import anomalias, p5

AGORA = pd.Timestamp("2026-10-25 15:00", tz="UTC")
HORAS = pd.date_range(AGORA - pd.Timedelta(days=60), AGORA - pd.Timedelta(hours=1), freq="h")
PERFIL = np.array([0.15, 0.1, 0.08, 0.08, 0.12, 0.3, 0.8, 1.5, 1.7, 1.3, 1.1, 1.1, 1.2, 1.2, 1.1, 1.1, 1.3, 1.6, 1.8,
                   1.5, 1.1, 0.8, 0.5, 0.3])


def _radar(semente: int, queda_desde_dias: float | None = None, nivel: float = 10) -> pd.Series:
    r = np.random.default_rng(semente)
    lam = nivel * PERFIL[HORAS.tz_convert(p5.FUSO).hour] / PERFIL.mean()
    if queda_desde_dias is not None:
        lam = np.where(HORAS >= AGORA - pd.Timedelta(days=queda_desde_dias), lam * 0.2, lam)
    return pd.Series(r.poisson(lam).astype(float), index=HORAS)


def _camera(semente: int, noite_desde_dias: float | None = None) -> pd.Series:
    r = np.random.default_rng(semente)
    v = np.full(len(HORAS), 60.0)
    quedas = r.random(len(HORAS)) < 0.004
    v[quedas] = r.integers(0, 50, quedas.sum())
    if noite_desde_dias is not None:
        noite = (HORAS >= AGORA - pd.Timedelta(days=noite_desde_dias)) & (HORAS.tz_convert(p5.FUSO).hour < 5)
        v[noite] = r.integers(0, 6, noite.sum())
    return pd.Series(v, index=HORAS)


def test_serie_normal_nao_gera_anomalia():
    falsos = [s for s in range(40) if p5.detectar_serie(_radar(s, nivel=3 + s % 12), AGORA, "infracoes")]
    falsos += [s for s in range(40) if p5.detectar_serie(_camera(100 + s), AGORA, "online_min")]
    assert falsos == []


def test_queda_de_radar_detectada():
    for dias in (2, 9, 25):
        d = p5.detectar_serie(_radar(7, queda_desde_dias=dias, nivel=4), AGORA, "infracoes")
        assert d and d["tipo"] == "queda" and d["razao"] < 0.4, dias
        assert len(d["grafico"]) == 72 and {"observado", "esperado", "inferior", "superior"} <= set(d["grafico"][0])
    assert "80% menos infrações" in p5.descrever("RAD-0042", "infracoes", {"tipo": "queda", "razao": 0.2})


def test_camera_que_cai_toda_noite():
    d = p5.detectar_serie(_camera(3, noite_desde_dias=12), AGORA, "online_min")
    assert d and d["tipo"] == "queda_recorrente" and d["horas"] == [0, 1, 2, 3, 4] and d["dias"] >= 2
    assert p5.descrever("CAM-0001", "online_min", d) == "CAM-0001: fora do ar todos os dias entre 0 h e 5 h (3 dias seguidos)"


def test_isolation_forest_aponta_o_perfil_estranho():
    series = {(i, "online_min"): _camera(200 + i) for i in range(30)}
    series[(99, "online_min")] = _camera(5, noite_desde_dias=10)
    iso = p5.isolation_forest(series, AGORA)
    assert iso[(99, "online_min")]["dias_atipicos"] >= 2
    normais_marcadas = sum(1 for k, v in iso.items() if k[0] != 99 and v["dias_atipicos"] >= 2)
    assert normais_marcadas <= 3                   # quedas isoladas de uma hora também parecem estranhas


def test_regiao_acima_do_previsto_por_horas_seguidas():
    idx = pd.date_range(AGORA - pd.Timedelta(hours=6), periods=6, freq="h")
    prev, sup = pd.Series(2.0, index=idx), pd.Series(5.0, index=idx)
    alto = pd.Series([1, 2, 3, 8, 9, 7.0], index=idx)
    d = p5.detectar_regiao(alto, prev, sup, 3)
    assert d and d["observado"] == 24 and d["horas"] == 3
    assert p5.detectar_regiao(pd.Series([1, 2, 3, 3, 9, 7.0], index=idx), prev, sup, 3) is None


def test_alerta_de_regiao_abre_e_resolve(client):
    agora = pd.Timestamp.now(tz="UTC").floor("h")
    origem = agora - pd.Timedelta(hours=6)
    with SessionLocal() as db:
        rid = db.execute(text("SELECT id FROM regiao WHERE nome = 'Centro'")).scalar()
        for k in range(1, 5):
            ini = agora - pd.Timedelta(hours=k)
            db.execute(text("""INSERT INTO previsao (modulo, alvo_tipo, alvo_id, regiao_id, horizonte_inicio, horizonte_fim, valor,
                                                     faixa_inferior, faixa_superior, fatores, dados_considerados, detalhe)
                               VALUES ('P2', 'regiao', :r, :r, :a, :b, 1, 0, 2, '[]', '[]', CAST(:d AS jsonb))"""),
                       {"r": rid, "a": ini, "b": ini + pd.Timedelta(hours=1), "d": json.dumps({"origem": origem.isoformat()})})
            for m in range(5):
                db.execute(text("""INSERT INTO ocorrencia (categoria, gravidade, inicio_em, geom, regiao_id, bairro_id, origem)
                                   VALUES ('ACIDENTE', 2, :t, ST_SetSRID(ST_MakePoint(-46.635, -23.55), 4326), :r, 1, 'simulada')"""),
                           {"t": ini + pd.Timedelta(minutes=5 + m), "r": rid})
        db.commit()
        res = anomalias.verificar(db, agora.to_pydatetime())
    assert res["novas"] == 1
    r = client.get("/anomalias").json()
    assert len(r) == 1 and r[0]["tipo"] == "anomalia_regiao" and r[0]["regiao"] == "Centro"
    assert "acima do previsto" in r[0]["mensagem"] and r[0]["grafico"]
    alertas = client.get("/alertas").json()
    lista = alertas.get("itens", alertas.get("alertas", [])) if isinstance(alertas, dict) else alertas
    assert any(a.get("tipo") == "anomalia_regiao" for a in lista), alertas
    with SessionLocal() as db:
        db.execute(text("DELETE FROM ocorrencia"))
        db.commit()
        res = anomalias.verificar(db, agora.to_pydatetime())
    assert res["resolvidas"] == 1
    assert client.get("/anomalias").json() == []


def test_anomalias_plantadas_encontradas(banco_gerado):
    eng, _ = banco_gerado
    with Session(eng) as db:
        plantadas = {a["equipamento_id"] for a in db.execute(text(
            "SELECT valor FROM estado_preditivo WHERE chave = 'anomalias_plantadas'")).scalar()}
        # Na data de referência do gerador: com o passar dos dias, a anomalia plantada mais antiga passa a ocupar mais
        # da metade da janela de referência e vira o "novo normal" (é assim que o detector funciona, por medianas)
        ref = db.execute(text("SELECT valor->>'data_referencia' FROM estado_preditivo WHERE chave = 'cidade'")).scalar()
        anomalias.verificar(db, pd.Timestamp(ref).tz_localize("America/Sao_Paulo").to_pydatetime())
        achadas = {i for (i,) in db.execute(text(
            "SELECT equipamento_id FROM alerta WHERE tipo = 'anomalia_equipamento' AND resolvido_em IS NULL"))}
    assert plantadas <= achadas
    assert len(achadas - plantadas) <= 2            # no máximo 1% de alarmes falsos nas 240 séries
