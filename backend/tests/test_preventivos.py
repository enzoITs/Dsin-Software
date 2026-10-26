"""Parte 3, fase 9: alertas preventivos (U3), acertômetro (Q1) e confiança dos modelos."""

import json

import pandas as pd
from sqlalchemy import text

from app.db import SessionLocal
from app.preditivo import acertometro, preventivos, servico


def _inserir(db, modulo: str, alvo_tipo: str, alvo_id: int, regiao_id: int | None, ini, fim, valor: float, nivel: str,
             detalhe: dict, lo: float | None = None, hi: float | None = None) -> int:
    return db.execute(text("""
        INSERT INTO previsao (modulo, alvo_tipo, alvo_id, regiao_id, horizonte_inicio, horizonte_fim, valor, faixa_inferior,
                              faixa_superior, nivel, fatores, dados_considerados, detalhe)
        VALUES (:m, :t, :a, :r, :i, :f, :v, :lo, :hi, :n, CAST(:fat AS jsonb), '[]', CAST(:d AS jsonb)) RETURNING id"""),
        {"m": modulo, "t": alvo_tipo, "a": alvo_id, "r": regiao_id, "i": ini, "f": fim, "v": valor, "lo": lo, "hi": hi, "n": nivel,
         "fat": json.dumps([{"descricao": "Manutenção preventiva atrasada há 30 dias", "efeito": 0.1}]),
         "d": json.dumps(detalhe)}).scalar()


def _centro(db) -> int:
    return db.execute(text("SELECT id FROM regiao WHERE nome = 'Centro'")).scalar()


def _abertos(db, tipo: str) -> list:
    return db.execute(text("SELECT id, nivel::text, mensagem, dados FROM alerta WHERE tipo::text = :t AND resolvido_em IS NULL"),
                      {"t": tipo}).all()


def test_risco_regiao_dispara_com_antecedencia_e_resolve(client):
    agora = pd.Timestamp.now(tz="UTC").floor("h")
    with SessionLocal() as db:
        rid = _centro(db)
        ini = agora + pd.Timedelta(hours=3)
        pid = _inserir(db, "P3", "regiao", rid, rid, ini, ini + pd.Timedelta(hours=1), 81, "MUITO_ALTO",
                       {"origem": agora.isoformat(), "granularidade": "hora", "motivo_principal": "Show com 40 mil pessoas"})
        _inserir(db, "P3", "regiao", rid, rid, agora + pd.Timedelta(hours=14), agora + pd.Timedelta(hours=15), 90, "MUITO_ALTO",
                 {"origem": agora.isoformat(), "granularidade": "hora"})  # fora das próximas 6 h
        db.commit()
        res = preventivos.verificar(db, agora.to_pydatetime())
        assert res["risco_regiao"] == 1
        (aid, nivel, msg, dados), = _abertos(db, "previsao_risco_regiao")
    assert nivel == "alta"  # muito alto sobe de média para alta
    assert msg.startswith("Previsto para") and "Centro" in msg and "Show" in msg
    p = dados["preditivo"]
    assert p["previsao_id"] == pid and p["antecedencia_min"] == 180 and p["modulo"] == "P3"
    # A API da central entrega o bloco preditivo e o cartão abre pela previsão
    a = client.get(f"/alertas/{aid}").json()
    assert (a.get("preditivo") or a.get("alerta", {}).get("preditivo"))["previsao_id"] == pid
    # Não pesa na saúde atual da região
    saude = {r["regiao"]: r for r in client.get("/regioes/saude").json()}
    assert saude["Centro"]["alertas"]["alta"] == 0
    # Passou o período: resolve sozinho
    with SessionLocal() as db:
        res = preventivos.verificar(db, (agora + pd.Timedelta(hours=5)).to_pydatetime())
        assert res["resolvidas"] == 1 and not _abertos(db, "previsao_risco_regiao")


def test_falha_equipamento_so_sem_os(client, radar):
    eq = radar()
    agora = pd.Timestamp.now(tz="UTC").floor("h")
    corte = agora.floor("D")
    with SessionLocal() as db:
        _inserir(db, "P1", "equipamento", eq["id"], _centro(db), corte, corte + pd.Timedelta(days=7), 0.41, "MUITO_ALTO",
                 {"alvo": {"tipo": "equipamento", "id": eq["id"], "nome": eq["codigo_interno"]}})
        outro = radar(numero_serie="PK-0002", dispositivo_iot_id="IOT-TESTE-2")
        _inserir(db, "P1", "equipamento", outro["id"], None, corte, corte + pd.Timedelta(days=7), 0.03, "BAIXO",
                 {"alvo": {"tipo": "equipamento", "id": outro["id"], "nome": outro["codigo_interno"]}})
        db.commit()
        assert preventivos.verificar(db, agora.to_pydatetime())["falha_equipamento"] == 1
        (_, _, msg, dados), = _abertos(db, "previsao_falha_equipamento")
    assert "41%" in msg and "sem OS aberta" in msg and dados["preditivo"]["probabilidade"] == 0.41
    with SessionLocal() as db:
        db.execute(text("INSERT INTO ordem_servico (equipamento_id, motivo, prioridade, status) VALUES (:e, 'Preventiva', 'alta', 'aberta')"),
                   {"e": eq["id"]})
        db.commit()
        assert preventivos.verificar(db, agora.to_pydatetime())["resolvidas"] == 1


def test_falta_agentes_resolve_quando_reforco_aceito(client):
    agora = pd.Timestamp.now(tz="UTC").floor("h")
    with SessionLocal() as db:
        rid = _centro(db)
        ini = agora + pd.Timedelta(hours=1)
        pid = _inserir(db, "P4", "regiao", rid, rid, ini, ini + pd.Timedelta(hours=6), 3, "ALTO",
                       {"origem": agora.isoformat(), "rotulo": "Sexta (30/10), 18 h às 24 h", "falta_antes": 60.0,
                        "demanda": 100.0, "capacidade_antes": 40.0, "entram": [{"de": "Oeste"}]})
        _inserir(db, "P4", "regiao", rid, rid, ini + pd.Timedelta(hours=6), ini + pd.Timedelta(hours=12), 1, "BAIXO",
                 {"origem": agora.isoformat(), "rotulo": "x", "falta_antes": 5.0, "demanda": 100.0, "capacidade_antes": 95.0})
        db.commit()
        assert preventivos.verificar(db, agora.to_pydatetime())["falta_agentes"] == 1
        (_, _, msg, _), = _abertos(db, "previsao_falta_agentes")
        assert "sexta (30/10)" in msg and "faltam 60 agentes-hora" in msg and "reforço" in msg
        db.execute(text("""INSERT INTO recomendacao (previsao_id, tipo, texto, parametros, impacto_estimado, estado, resultado)
                           VALUES (:p, 'REFORCAR_EQUIPES', 'x', '{}', '{}', 'aceita', '{}')"""), {"p": pid})
        db.commit()
        assert preventivos.verificar(db, agora.to_pydatetime())["resolvidas"] == 1


def test_acertometro_confere_e_compara_com_baseline(client):
    agora = pd.Timestamp.now(tz="UTC").floor("h")
    with SessionLocal() as db:
        rid = _centro(db)
        for k in (1, 2):
            ini = agora - pd.Timedelta(hours=k)
            _inserir(db, "P2", "regiao", rid, rid, ini, ini + pd.Timedelta(hours=1), 2.5, "NORMAL",
                     {"origem": (agora - pd.Timedelta(hours=3)).isoformat(), "normal": 5.0}, lo=1, hi=4)
            for m in range(3):
                db.execute(text("""INSERT INTO ocorrencia (categoria, gravidade, inicio_em, geom, regiao_id, bairro_id, origem)
                                   VALUES ('ACIDENTE', 2, :t, ST_SetSRID(ST_MakePoint(-46.635, -23.55), 4326), :r, 1, 'simulada')"""),
                           {"t": ini + pd.Timedelta(minutes=5 + m), "r": rid})
        # previsão de uma hora que ainda não terminou: não é conferida
        _inserir(db, "P2", "regiao", rid, rid, agora, agora + pd.Timedelta(hours=1), 2.5, "NORMAL",
                 {"origem": agora.isoformat(), "normal": 5.0}, lo=1, hi=4)
        db.commit()
        assert acertometro.conferir(db, agora.to_pydatetime())["p2"] == 2
        assert db.execute(text("SELECT count(*) FROM previsao WHERE valor_real = 3")).scalar() == 2
    r = client.get("/modelos/acertometro", params={"dias": 1}).json()
    g = r["P2"]["geral"]
    assert g["n"] == 2 and g["mae"] == 0.5 and g["mae_baseline"] == 2.0 and g["ganho_pct"] == 75.0
    assert g["cobertura_intervalo"] == 1.0 and r["P2"]["serie_48h"] and r["dados_sinteticos"] is True


def test_modelos_sem_treino_e_risco_previsto(client, monkeypatch):
    r = client.get("/modelos").json()
    assert r["modelos"] == [] and r["treino"]["tem_modelo"] is False and len(r["derivados"]) == 3
    assert client.get("/risco-previsto").json()["regioes"] == []
    agora = pd.Timestamp.now(tz="UTC").floor("h")
    with SessionLocal() as db:
        rid = _centro(db)
        for k, v in ((1, 40), (2, 66)):
            ini = agora + pd.Timedelta(hours=k)
            _inserir(db, "P3", "regiao", rid, rid, ini, ini + pd.Timedelta(hours=1), v, "ALTO" if v > 50 else "MODERADO",
                     {"origem": agora.isoformat(), "granularidade": "hora", "nivel_nome": "Alto"})
        db.commit()
    rp = client.get("/risco-previsto").json()["regioes"]
    assert len(rp) == 1 and rp[0]["indice"] == 66 and rp[0]["geometria"]["type"] == "MultiPolygon"
    # Retreinar: só o gestor, em segundo plano
    chamadas = []
    monkeypatch.setattr(servico, "iniciar_treino", lambda: chamadas.append(1) or True)
    assert client.post("/modelos/treinar", headers={"X-Perfil": "operador", "X-Orgao-Id": "1"}).status_code == 403
    assert client.post("/modelos/treinar").status_code == 202 and chamadas == [1]
