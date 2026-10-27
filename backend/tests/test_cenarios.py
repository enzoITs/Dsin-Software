"""Parte 3, fase 10: cenários "e se" (C1), retorno das recomendações (C5) e padrões descobertos (Q2)."""

import json
from datetime import timedelta

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.preditivo import cenarios, descoberta, retorno


def _treinado(banco_gerado):
    eng, rodar = banco_gerado
    with eng.connect() as c:
        tem = c.execute(text("SELECT count(*) FROM modelo_versao WHERE nome = 'ocorrencias_regiao_hora' AND ativo")).scalar()
    if not tem:
        rodar("app.preditivo.treinar", "--todos")
    with eng.connect() as c:
        ate = c.execute(text("SELECT valor->>'ate' FROM estado_preditivo WHERE chave = 'continuo'")).scalar()
    return eng, pd.Timestamp(ate).to_pydatetime()


def test_menos_equipes_aumenta_risco_nao_coberto_sem_mudar_ocorrencias(banco_gerado):
    eng, agora = _treinado(banco_gerado)
    with Session(eng) as db:
        r = cenarios.simular(db, {"equipes": [{"regiao": "Centro", "delta": -2}]}, agora=agora)
    eq = r["equipes"]
    assert eq["cenario"]["nao_coberto_escala"] > eq["base"]["nao_coberto_escala"]
    assert r["aplicado"]["equipes"]["turnos_retirados"] > 0
    centro = next(x for x in r["regioes"] if x["regiao"] == "Centro")
    # Menos agentes não muda o que acontece na rua (viés de registro); muda a cobertura e o índice
    assert centro["ocorrencias_cenario"] == centro["ocorrencias_base"]
    assert centro["indice_medio_cenario"] >= centro["indice_medio_base"]
    assert any("Risco não coberto" in f for f in r["frases"])


def test_evento_aumenta_ocorrencias_perto_e_nao_longe(banco_gerado):
    eng, agora = _treinado(banco_gerado)
    with Session(eng) as db:
        bairro = db.execute(text("SELECT id FROM bairro WHERE regiao = 'Centro' AND geom IS NOT NULL ORDER BY id LIMIT 1")).scalar()
        ini = pd.Timestamp(agora) + timedelta(hours=20)
        r = cenarios.simular(db, {"eventos": [{"nome": "Show de teste", "bairro_id": bairro, "publico": 45000,
                                               "inicio": ini.isoformat(), "fim": (ini + timedelta(hours=4)).isoformat()}]},
                             agora=agora)
    por = {x["regiao"]: x for x in r["regioes"]}
    assert por["Centro"]["ocorrencias_cenario"] > por["Centro"]["ocorrencias_base"] * 1.01
    longe = [x for x in r["regioes"] if x["regiao"] != "Centro" and x["ocorrencias_cenario"] == x["ocorrencias_base"]]
    assert longe, "o evento não pode mudar todas as regiões"
    assert r["aplicado"]["eventos_novos"] == ["Show de teste"]


def test_chuva_manutencao_equipamentos_e_erros(banco_gerado):
    eng, agora = _treinado(banco_gerado)
    with Session(eng) as db:
        r = cenarios.simular(db, {"clima": [{"chuva_mm": 10}]}, agora=agora)
        assert sum(x["ocorrencias_cenario"] for x in r["regioes"]) > sum(x["ocorrencias_base"] for x in r["regioes"])
        m = cenarios.simular(db, {"manutencoes": {"quantidade": 3}}, agora=agora)["aplicado"]["manutencoes"]
        assert len(m) == 3 and all(x["prob_depois"] <= x["prob_antes"] for x in m if x["prob_antes"] is not None)
        fora = cenarios.simular(db, {"equipamentos_fora": {"prefixo": "CAM", "quantidade": 4}}, agora=agora)
        assert len(fora["aplicado"]["equipamentos_fora"]) == 4
        with pytest.raises(cenarios.CenarioInvalido):
            cenarios.simular(db, {"equipes": [{"regiao": "Atlântida", "delta": 1}]}, agora=agora)
    # nada foi gravado
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM evento_cidade WHERE nome = 'Show de teste'")).scalar() == 0


def test_padroes_descobertos(banco_gerado):
    eng, _ = _treinado(banco_gerado)
    with Session(eng) as db:
        r = descoberta.calcular(db)
    por = {i["padrao"]: i for i in r["padroes"]}
    assert {1, 2, 3, 4, 7, 8} <= set(por)
    for i in r["padroes"]:
        assert i["titulo"] and i["metodo"] and i["descoberto"] and i["plantado"]
        assert i["veredito"] in {"encontrado", "fraco", "nao_encontrado", "sem_dados"}
    assert por[1]["veredito"] == "encontrado" and por[8]["veredito"] == "encontrado"
    assert por[4]["efeito"] > 1.3 and por[7]["efeito"] > 1.2
    assert r["resumo"]["encontrado"] >= 6 and "sintéticos" in r["aviso"]


def test_api_cenarios_salvar_listar_remover(client, monkeypatch):
    r = client.post("/cenarios/simular", json={})
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "cenario_invalido"  # sem modelo treinado
    falso = {"origem": "2026-10-30T21:00:00+00:00", "frases": ["Ocorrências previstas nas próximas 72 h: 900 → 950 (+5,6%)"],
             "regioes": [], "periodos": [], "equipes": {}, "aplicado": {}}
    monkeypatch.setattr(cenarios, "simular", lambda db, p, agora=None: {**falso, "parametros": p})
    body = {"nome": "Show cancelado", "parametros": {"cancelar_eventos": [3]}}
    assert client.post("/cenarios", json=body, headers={"X-Perfil": "prometheus"}).status_code == 403
    c = client.post("/cenarios", json=body, headers={"X-Usuario": "Ana"}).json()
    assert c["nome"] == "Show cancelado" and c["criado_por"] == "Ana" and c["parametros"]["cancelar_eventos"] == [3]
    lista = client.get("/cenarios").json()
    assert lista[0]["id"] == c["id"] and lista[0]["frases"] == falso["frases"]
    assert client.get(f"/cenarios/{c['id']}").json()["resultado"]["origem"] == falso["origem"]
    assert client.delete(f"/cenarios/{c['id']}", headers={"X-Perfil": "operador", "X-Orgao-Id": "1", "X-Usuario": "Bia"}).status_code == 403
    assert client.delete(f"/cenarios/{c['id']}").status_code == 204
    assert client.get("/cenarios").json() == []
    assert client.get("/cenarios/opcoes").json()["regioes"] == ["Centro", "Oeste"]


def _p1(db, eid: int, ini, fim, valor: float) -> int:
    return db.execute(text("""
        INSERT INTO previsao (modulo, alvo_tipo, alvo_id, horizonte_inicio, horizonte_fim, valor, nivel, fatores,
                              dados_considerados, detalhe)
        VALUES ('P1', 'equipamento', :e, :i, :f, :v, 'MUITO_ALTO', '[]', '[]', CAST(:d AS jsonb)) RETURNING id"""),
        {"e": eid, "i": ini, "f": fim, "v": valor,
         "d": json.dumps({"acao_recomendada": {"texto": "Abrir OS preventiva", "tipo": "ABRIR_ORDEM_SERVICO",
                                               "parametros": {"equipamento_id": eid}}})}).scalar()


def test_retorno_registra_decisao_motivo_e_resultado(client, radar):
    a = radar()
    b = radar(numero_serie="PK-0002", dispositivo_iot_id="IOT-TESTE-2")
    agora = pd.Timestamp.now(tz="UTC")
    ini, fim = agora - timedelta(hours=1), agora + timedelta(days=2)
    with SessionLocal() as db:
        pa, pb = _p1(db, a["id"], ini, fim, 0.4), _p1(db, b["id"], ini, fim, 0.35)
        db.commit()
    assert client.post(f"/previsoes/{pa}/decisao", json={"acao": "aceitar"}, headers={"X-Usuario": "Ana"}).status_code == 200
    assert client.post(f"/previsoes/{pb}/decisao", json={"acao": "rejeitar", "motivo": "Será trocado mês que vem"}).status_code == 200
    with SessionLocal() as db:
        # A rejeitada falhou dentro da janela, depois da decisão
        db.execute(text("""INSERT INTO historico_situacao (equipamento_id, situacao_anterior, situacao_nova, motivo, usuario, em)
                           VALUES (:e, 'operacional', 'mau_funcionamento', 'Falha', 'teste', :t)"""),
                   {"e": b["id"], "t": agora + timedelta(days=1)})
        db.commit()
        assert retorno.conferir(db) == 0  # a janela ainda não terminou
        assert retorno.conferir(db, (agora + timedelta(days=3)).to_pydatetime()) == 2
    r = client.get("/recomendacoes/retorno").json()
    assert r["decididas"] == 2 and r["taxa_aceitacao"] == 0.5
    assert r["motivos_rejeicao"] == [{"motivo": "Será trocado mês que vem", "vezes": 1}]
    os_ = r["comparacao"]["os"]
    assert os_["aceitas"] == {"conferidas": 1, "falharam": 0, "taxa_falha": 0.0}
    assert os_["rejeitadas"] == {"conferidas": 1, "falharam": 1, "taxa_falha": 1.0}
    d = {x["estado"]: x for x in r["decisoes"]}
    assert d["aceita"]["decidido_por"] == "Ana" and d["aceita"]["execucao"]["ordem_servico_id"]
    assert d["rejeitada"]["retorno"]["falhou"] is True and "falhou" in d["rejeitada"]["retorno"]["texto"]
