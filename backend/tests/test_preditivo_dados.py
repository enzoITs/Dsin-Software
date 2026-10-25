"""Parte 3, fase 1: ocorrências, calendário, clima, eventos e a migração 0003."""

import os
from datetime import date, datetime, timedelta, timezone

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.preditivo import calendario, clima
from tests.conftest import BASE, RADAR

# Ponto dentro do bairro "Centro" do conftest.
CENTRO = {"lon": -46.635, "lat": -23.55}
GESTOR = {"X-Perfil": "gestor", "X-Usuario": "Ana Gestora"}
PROMETHEUS = {"X-Perfil": "prometheus"}


# ---------- Migração ----------


def test_migracao_0003_sobe_e_desce(banco):
    """Banco à parte: sobe tudo, desce para a Parte 2 (tabelas somem), sobe de novo."""
    url = BASE.rsplit("/", 1)[0] + "/atalaia_test_migracao"
    admin = create_engine(BASE, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS atalaia_test_migracao WITH (FORCE)"))
        c.execute(text("CREATE DATABASE atalaia_test_migracao"))
    raiz = os.path.join(os.path.dirname(__file__), "..")
    cfg = Config(os.path.join(raiz, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(raiz, "alembic"))
    novas = {"ocorrencia", "categoria_ocorrencia", "calendario", "clima_hora", "evento_cidade", "escala_agente",
             "previsao", "recomendacao", "modelo_versao", "backtest_resultado", "estado_preditivo"}
    eng = create_engine(url)
    try:
        def migrar(acao, alvo):
            with eng.begin() as con:
                cfg.attributes["connection"] = con
                acao(cfg, alvo)

        migrar(command.upgrade, "head")
        assert novas <= set(inspect(eng).get_table_names())
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM categoria_ocorrencia")).scalar() == 10
        migrar(command.downgrade, "0002")
        tabelas = set(inspect(eng).get_table_names())
        assert not (novas & tabelas) and {"equipamento", "alerta", "regiao"} <= tabelas
        migrar(command.upgrade, "head")
        assert novas <= set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
        with admin.connect() as c:
            c.execute(text("DROP DATABASE IF EXISTS atalaia_test_migracao WITH (FORCE)"))
        admin.dispose()


# ---------- Calendário (função pura) ----------


def test_calendario_feriados_vesperas_e_pagamento():
    dias = {d["data"]: d for d in calendario.dias(date(2026, 1, 1), date(2026, 12, 31))}
    assert dias[date(2026, 10, 12)]["feriado"] and dias[date(2026, 10, 12)]["feriado_esfera"] == "nacional"
    assert dias[date(2026, 7, 9)]["feriado_esfera"] == "estadual"            # Revolução Constitucionalista
    assert dias[date(2026, 1, 25)]["feriado_esfera"] == "municipal"          # aniversário de São Paulo
    assert dias[date(2026, 6, 4)]["feriado_nome"] == "Corpus Christi"
    assert dias[date(2026, 2, 16)]["feriado_esfera"] == "facultativo"        # Carnaval
    assert dias[date(2026, 10, 11)]["vespera_feriado"] and not dias[date(2026, 10, 12)]["vespera_feriado"]
    # 5º dia útil de novembro/2026: dia 2 é Finados, então 3, 4, 5, 6 e 9
    pag_nov = [d for d, x in dias.items() if x["dia_pagamento"] and d.month == 11]
    assert pag_nov == [date(2026, 11, 9)]
    assert sum(x["dia_pagamento"] for x in dias.values()) == 12
    assert not dias[date(2026, 7, 20)]["periodo_escolar"]  # férias de julho
    assert dias[date(2026, 10, 14)]["periodo_escolar"]
    assert not dias[date(2026, 10, 17)]["periodo_escolar"]  # sábado


def test_api_calendario(client):
    r = client.get("/calendario", params={"inicio": "2026-11-01", "fim": "2026-11-03"})
    assert r.status_code == 200
    assert [d["feriado"] for d in r.json()] == [False, True, False]
    assert client.get("/calendario", params={"inicio": "2026-11-03", "fim": "2026-11-01"}).status_code == 422


# ---------- Clima ----------


def test_clima_sintetico_deterministico_e_sazonal():
    d = date(2026, 1, 15)
    assert clima.dia(d, 42) == clima.dia(d, 42)
    assert clima.dia(d, 42) != clima.dia(d, 7)
    assert len(clima.dia(d)) == 24
    verao = [h for i in range(60) for h in clima.dia(date(2026, 1, 1) + timedelta(days=i))]
    inverno = [h for i in range(60) for h in clima.dia(date(2026, 6, 15) + timedelta(days=i))]
    media = lambda xs, k: sum(x[k] for x in xs) / len(xs)  # noqa: E731
    assert media(verao, "temperatura_c") > media(inverno, "temperatura_c") + 3
    assert sum(x["chuva_mm"] for x in verao) > 2 * sum(x["chuva_mm"] for x in inverno)
    # Pico de calor à tarde
    dia = clima.dia(date(2026, 3, 10))
    assert dia[15]["temperatura_c"] > dia[5]["temperatura_c"]


def test_previsao_de_clima_editavel(client):
    r = client.get("/clima/previsao", params={"horas": 24})
    assert r.status_code == 200
    horas = r.json()["horas"]
    assert 24 <= len(horas) <= 25 and all(h["editado_por"] is None for h in horas)

    amanha = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=20)
    body = {"inicio": amanha.isoformat(), "fim": (amanha + timedelta(hours=3)).isoformat(), "chuva_mm": 25,
            "alerta_tempestade": True}
    r = client.put("/clima/previsao", json=body, headers=GESTOR)
    assert r.status_code == 200 and r.json()["horas_alteradas"] == 3
    horas = client.get("/clima/previsao", params={"horas": 30}).json()["horas"]
    editadas = [h for h in horas if h["editado_por"] == "Ana Gestora"]
    assert len(editadas) == 3 and all(h["chuva_mm"] == 25 and h["alerta_tempestade"] for h in editadas)

    assert client.put("/clima/previsao", json=body, headers=PROMETHEUS).status_code == 403
    assert client.put("/clima/previsao", json={**body, "chuva_mm": None, "alerta_tempestade": None}).status_code == 422
    assert client.put("/clima/previsao", json={**body, "fim": body["inicio"]}).status_code == 422


def test_garantir_previsao_nao_apaga_edicao(client):
    from app.db import SessionLocal
    from app.routers.preditivo import cidade_principal

    agora = datetime.now(timezone.utc)
    alvo = clima.hora_cheia(agora) + timedelta(hours=5)
    client.put("/clima/previsao", json={"inicio": alvo.isoformat(), "fim": (alvo + timedelta(hours=1)).isoformat(),
                                        "temperatura_c": 40}, headers=GESTOR)
    with SessionLocal() as db:
        cid = cidade_principal(db)
        clima.gravar(db, cid, [{"em": alvo, "temperatura_c": 10, "chuva_mm": 0, "alerta_tempestade": False}], previsao=True)
        db.commit()
    h = [x for x in client.get("/clima/previsao", params={"horas": 8}).json()["horas"] if x["em"].startswith(alvo.isoformat()[:13])]
    assert h and h[0]["temperatura_c"] == 40


# ---------- Ocorrências ----------


def test_registrar_ocorrencia_na_central(client):
    r = client.post("/ocorrencias", json={"categoria": "ACIDENTE", **CENTRO, "descricao": "Colisão no cruzamento"},
                    headers=GESTOR)
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["regiao"] == "Centro" and o["bairro"] == "Centro"
    assert o["origem"] == "central" and o["gravidade"] == 3  # gravidade padrão de acidente
    assert o["registrado_por"] == "Ana Gestora" and o["agentes_presentes_regiao"] == 0

    lista = client.get("/ocorrencias", params={"horas": 1}).json()
    assert lista["total"] == 1 and lista["itens"][0]["id"] == o["id"]
    assert client.get("/ocorrencias", params={"regiao": "Oeste"}).json()["total"] == 0
    assert client.get("/ocorrencias", params={"categoria": ["ALAGAMENTO"]}).json()["total"] == 0


def test_ocorrencia_conta_agentes_ativos_da_regiao(client):
    for i in range(3):
        r = client.post("/agentes", json={"nome": f"Agente {i}", "matricula": f"CET9{i}", "categoria": "agente_transito",
                                          "orgao_id": 1, "situacao": "em_atividade" if i < 2 else "em_pausa"})
        assert r.status_code == 201, r.text
    from app.db import SessionLocal

    with SessionLocal() as db:
        db.execute(text("UPDATE agente SET regiao = 'Centro'"))
        db.commit()
    o = client.post("/ocorrencias", json={"categoria": "PERTURBACAO", **CENTRO}).json()
    assert o["agentes_presentes_regiao"] == 2


def test_ocorrencia_invalida(client):
    assert client.post("/ocorrencias", json={"categoria": "NAO_EXISTE", **CENTRO}).status_code == 422
    assert client.post("/ocorrencias", json={"categoria": "ACIDENTE", "gravidade": 5, **CENTRO}).status_code == 422
    assert client.post("/ocorrencias", json={"categoria": "ACIDENTE", "lon": -46.6}).status_code == 422


def test_prometheus_registra_ocorrencia_externa(client):
    o = client.post("/ocorrencias", json={"categoria": "ALAGAMENTO", **CENTRO}, headers=PROMETHEUS).json()
    assert o["origem"] == "externa"


def test_ocorrencia_fora_das_regioes_fica_sem_regiao(client):
    o = client.post("/ocorrencias", json={"categoria": "OUTROS", "lon": -46.9, "lat": -23.9}).json()
    assert o["regiao"] is None and o["bairro"] is None


def test_furto_gera_ocorrencia_uma_vez(client):
    r = client.post("/equipamentos", json={**RADAR, "localizacao": {**RADAR["localizacao"], **CENTRO}})
    e = r.json()
    client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "furtado", "motivo": "BO 123"})
    occ = client.get("/ocorrencias", params={"categoria": ["FURTO_EQUIPAMENTO"]}).json()
    assert occ["total"] == 1
    o = occ["itens"][0]
    assert o["origem"] == "equipamento" and o["equipamento_id"] == e["id"] and o["alerta_id"] and o["gravidade"] == 4
    assert o["regiao"] == "Centro"
    # O mesmo furto confirmado de novo pelo deslocamento não duplica a ocorrência
    from app.db import SessionLocal
    from app.models import Alerta
    from app.services import ocorrencias

    with SessionLocal() as db:
        a = db.get(Alerta, o["alerta_id"])
        assert ocorrencias.de_alerta(db, a, CENTRO["lon"], CENTRO["lat"]) is None
    assert client.get("/ocorrencias", params={"categoria": ["FURTO_EQUIPAMENTO"]}).json()["total"] == 1


def test_categorias(client):
    cats = client.get("/ocorrencias/categorias").json()
    assert len(cats) == 10 and {"ACIDENTE", "ALAGAMENTO", "FURTO_EQUIPAMENTO"} <= {c["codigo"] for c in cats}


# ---------- Eventos da cidade ----------


def test_eventos_da_cidade(client):
    inicio = datetime.now(timezone.utc) + timedelta(days=2)
    body = {"nome": "Show no estádio", "tipo": "show", "local_nome": "Pacaembu", "lon": -46.665, "lat": -23.547,
            "inicio_em": inicio.isoformat(), "fim_em": (inicio + timedelta(hours=4)).isoformat(),
            "publico_estimado": 35000}
    r = client.post("/eventos-cidade", json=body, headers=GESTOR)
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev["raio_influencia_m"] == 2000 and not ev["simulado"] and ev["criado_por"] == "Ana Gestora"
    assert [x["id"] for x in client.get("/eventos-cidade").json()] == [ev["id"]]
    longe = (inicio + timedelta(days=30)).isoformat()
    assert client.get("/eventos-cidade", params={"desde": longe}).json() == []

    assert client.post("/eventos-cidade", json=body, headers=PROMETHEUS).status_code == 403
    assert client.post("/eventos-cidade", json={**body, "fim_em": body["inicio_em"]}).status_code == 422
    assert client.post("/eventos-cidade", json={**body, "tipo": "carnaval"}).status_code == 422
    assert client.delete(f"/eventos-cidade/{ev['id']}").status_code == 204
    assert client.get("/eventos-cidade").json() == []
    assert client.delete(f"/eventos-cidade/{ev['id']}").status_code == 404


def test_escala_vazia_responde(client):
    assert client.get("/escala").json() == []
