"""Parte 3, fase 8: contrato de previsão na API e decisões sobre as recomendações (C5)."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import SessionLocal

CAMPOS_CONTRATO = {"id", "modulo", "o_que_preve", "alvo", "horizonte", "valor", "faixa", "nivel", "dados_considerados",
                   "fatores", "como_ajuda", "acao_recomendada", "qualidade_do_modelo", "modelo", "gerado_em"}


def _previsao(modulo: str, alvo_id: int, acao: dict, regiao_id: int | None = None, ini=None, fim=None) -> int:
    ini = ini or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    fim = fim or ini + timedelta(days=7)
    detalhe = {"o_que_preve": "Probabilidade de falha de RAD-0001 nos próximos 7 dias",
               "alvo": {"tipo": "equipamento", "id": alvo_id, "nome": "RAD-0001", "regiao": "Centro", "tipo_equipamento": "RAD"},
               "como_ajuda": "Antecipar a manutenção evita perder a fiscalização", "acao_recomendada": acao,
               "qualidade_do_modelo": {"metrica": "AUC", "modelo": 0.64, "baseline": 0.6},
               "modelo": {"nome": "falha_equipamento_7d", "versao": "teste"}, "origem": ini.isoformat()}
    with SessionLocal() as db:
        pid = db.execute(text("""
            INSERT INTO previsao (modulo, alvo_tipo, alvo_id, regiao_id, horizonte_inicio, horizonte_fim, valor, faixa_inferior,
                                  faixa_superior, nivel, fatores, dados_considerados, detalhe)
            VALUES (:m, 'equipamento', :a, :r, :i, :f, 0.3, 0.25, 0.35, 'MUITO_ALTO', CAST(:fat AS jsonb), CAST(:dados AS jsonb),
                    CAST(:d AS jsonb)) RETURNING id"""),
            {"m": modulo, "a": alvo_id, "r": regiao_id, "i": ini, "f": fim, "d": json.dumps(detalhe),
             "fat": json.dumps([{"descricao": "Manutenção preventiva atrasada há 21 dias", "efeito": 0.15, "grupo": "manutencao"}]),
             "dados": json.dumps(["Histórico de falhas dos últimos 180 dias"])}).scalar()
        db.commit()
    return pid


def test_contrato_completo(client, radar):
    eq = radar()
    pid = _previsao("P1", eq["id"], {"texto": "Abrir OS", "tipo": "ABRIR_ORDEM_SERVICO",
                                     "parametros": {"equipamento_id": eq["id"], "prioridade": "alta"}})
    c = client.get(f"/previsoes/{pid}").json()
    assert CAMPOS_CONTRATO <= set(c)
    assert c["dados_considerados"] and c["fatores"] and c["como_ajuda"] and c["acao_recomendada"]["texto"]
    assert c["faixa"]["inferior"] <= c["valor"] <= c["faixa"]["superior"]
    assert c["confianca"]["nivel"] in {"baixa", "moderada", "alta"} and c["dados_sinteticos"] is True
    lista = client.get("/previsoes", params={"modulo": "P1", "atuais": False}).json()
    assert [x["previsao_id"] for x in lista] == [pid]
    assert client.get("/previsoes/999999").status_code == 404


def test_aceitar_abre_os_e_registra(client, radar):
    eq = radar()
    pid = _previsao("P1", eq["id"], {"texto": "Abrir OS preventiva", "tipo": "ABRIR_ORDEM_SERVICO",
                                     "parametros": {"equipamento_id": eq["id"], "prioridade": "alta"}})
    r = client.post(f"/previsoes/{pid}/decisao", json={"acao": "aceitar"}, headers={"X-Usuario": "Ana Gestora"})
    assert r.status_code == 200, r.text
    rec = r.json()["recomendacao"]
    assert rec["estado"] == "aceita" and rec["decidido_por"] == "Ana Gestora" and rec["decidido_em"]
    os_id = rec["resultado"]["execucao"]["ordem_servico_id"]
    ordens = client.get(f"/equipamentos/{eq['id']}/ordens-servico").json()
    assert any(o["id"] == os_id and o["prioridade"] == "alta" for o in ordens)
    # decidir de novo não pode
    assert client.post(f"/previsoes/{pid}/decisao", json={"acao": "rejeitar", "motivo": "x"}).status_code == 409


def test_rejeitar_exige_motivo_e_ajustar_registra(client, radar):
    eq = radar()
    acao = {"texto": "Abrir OS", "tipo": "ABRIR_ORDEM_SERVICO", "parametros": {"equipamento_id": eq["id"]}}
    pid = _previsao("P1", eq["id"], acao)
    assert client.post(f"/previsoes/{pid}/decisao", json={"acao": "rejeitar"}).status_code == 422
    r = client.post(f"/previsoes/{pid}/decisao", json={"acao": "rejeitar", "motivo": "Equipamento será substituído"}).json()
    assert r["recomendacao"]["estado"] == "rejeitada" and r["recomendacao"]["motivo"] == "Equipamento será substituído"
    pid2 = _previsao("P1", eq["id"], acao)
    r = client.post(f"/previsoes/{pid2}/decisao",
                    json={"acao": "ajustar", "motivo": "Prioridade baixa", "parametros": {"prioridade": "baixa"}}).json()
    assert r["recomendacao"]["estado"] == "ajustada"
    assert client.get("/recomendacoes", params={"estado": "rejeitada"}).json()[0]["motivo"] == "Equipamento será substituído"


def test_prometheus_nao_decide(client, radar):
    eq = radar()
    pid = _previsao("P1", eq["id"], {"texto": "Abrir OS", "tipo": "ABRIR_ORDEM_SERVICO", "parametros": {"equipamento_id": eq["id"]}})
    assert client.post(f"/previsoes/{pid}/decisao", json={"acao": "aceitar"}, headers={"X-Perfil": "prometheus"}).status_code == 403


def test_ordens_em_lote(client, radar):
    a, b = radar(), radar(numero_serie="PK-2", dispositivo_iot_id="IOT-2")
    ids = [_previsao("P1", e["id"], {"texto": "Incluir na rota", "tipo": "INCLUIR_ROTA_MANUTENCAO",
                                      "parametros": {"equipamento_id": e["id"]}}) for e in (a, b)]
    r = client.post("/equipamentos/risco/ordens", json={"previsao_ids": ids}).json()
    assert len(r["abertas"]) == 2 and not r["puladas"]
    r = client.post("/equipamentos/risco/ordens", json={"previsao_ids": ids}).json()
    assert len(r["puladas"]) == 2


def test_aceitar_reforco_move_a_equipe_na_escala(client):
    with SessionLocal() as db:
        centro, oeste = (db.execute(text("SELECT id FROM regiao WHERE nome = :n"), {"n": n}).scalar() for n in ("Centro", "Oeste"))
        t0 = datetime(2026, 10, 30, 9, tzinfo=timezone.utc)
        esc = db.execute(text("""INSERT INTO escala_agente (equipe, orgao_id, regiao_id, inicio_em, fim_em, agentes, origem)
                                 VALUES ('Alfa-1', 1, :o, :a, :b, 10, 'escala') RETURNING id"""),
                         {"o": oeste, "a": t0, "b": t0 + timedelta(hours=8)}).scalar()
        db.commit()
    p0, p1 = t0 + timedelta(hours=3), t0 + timedelta(hours=6)
    pid = _previsao("P4", centro, {"texto": "Reforçar o Centro", "tipo": "REFORCAR_EQUIPES", "parametros": {}}, centro, p0, p1)
    with SessionLocal() as db:
        rec = db.execute(text("""INSERT INTO recomendacao (previsao_id, tipo, texto, parametros, impacto_estimado, estado, resultado)
                                 VALUES (:p, 'REFORCAR_EQUIPES', 'Reforçar o Centro com +1 equipe', CAST(:par AS jsonb), '{}', 'pendente', '{}')
                                 RETURNING id"""),
                         {"p": pid, "par": json.dumps({"inicio": p0.isoformat(), "fim": p1.isoformat(), "destino_regiao_id": centro,
                                                      "equipes": [{"escala_id": esc, "equipe": "Alfa-1", "orgao": "CET", "de": "Oeste"}]})}).scalar()
        db.commit()
    r = client.patch(f"/recomendacoes/{rec}", json={"acao": "aceitar"})
    assert r.status_code == 200, r.text
    turnos = client.get("/escala", params={"inicio": t0.isoformat(), "fim": (t0 + timedelta(hours=8)).isoformat()}).json()
    por_regiao = sorted((t["regiao"], t["inicio_em"][11:16], t["fim_em"][11:16], t["origem"]) for t in turnos)
    assert por_regiao == [("Centro", "12:00", "15:00", "recomendacao"), ("Oeste", "09:00", "12:00", "escala"),
                          ("Oeste", "15:00", "17:00", "escala")]


def test_telas_sem_previsoes(client):
    assert client.get("/amanha").status_code == 409
    assert client.get("/equipamentos/risco").status_code == 409
    assert client.get("/equipamentos/risco", params={"janela": 15}).status_code == 422
