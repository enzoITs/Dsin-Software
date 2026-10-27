"""Parte 3, fase 13: fim de vida útil (X3), monitor dos modelos (X4) e relatório semanal (X5)."""

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.preditivo import monitor, relatorio, vida_util
from app.preditivo import variaveis as V


def test_dias_parado_conta_so_o_ultimo_ano():
    ate = pd.Timestamp("2026-10-01", tz="UTC")
    h = pd.DataFrame({"equipamento_id": [1, 1, 1, 2, 2], "nova": ["operacional", "mau_funcionamento", "operacional",
                                                                   "mau_funcionamento", "operacional"],
                      "em": pd.to_datetime(["2025-01-01", "2026-09-01", "2026-09-11", "2025-09-01", "2025-10-21"], utc=True)})
    f = V.Fontes(*([None] * 10))
    f.historico = h
    d = vida_util.dias_parado(f, ate)
    assert d[1] == pytest.approx(10)
    assert d[2] == pytest.approx(20)  # só a parte depois de 01/10/2025


def test_rotas_sem_modelo(client):
    r = client.get("/equipamentos/fim-de-vida").json()
    assert r["itens"] == [] and r["mensagem"]
    m = client.get("/modelos/monitor").json()
    assert m["situacao"] == "ok" and m["modelos"] == []
    s = client.get("/relatorio/semanal").json()
    assert s["titulo"].startswith("Relatório semanal") and s["markdown"].startswith("# Relatório semanal")
    assert {x["id"] for x in s["secoes"]} >= {"resumo", "acertometro", "decisoes", "alertas", "tendencias", "modelos"}
    assert client.get("/relatorio/semanal.md").text.startswith("# Relatório semanal")


def _treinado(banco_gerado):
    eng, rodar = banco_gerado
    with eng.connect() as c:
        tem = c.execute(text("SELECT count(*) FROM modelo_versao WHERE nome = 'furto_equipamento_30d' AND ativo")).scalar()
    if not tem:
        rodar("app.preditivo.treinar", "--todos")
    return eng


def test_fim_de_vida_e_monitor_no_banco_gerado(banco_gerado):
    eng = _treinado(banco_gerado)
    with Session(eng) as db:
        r = vida_util.calcular(db, limite=50)
        m = monitor.avaliar(db)
        s = relatorio.montar(db)
    assert r["itens"] and r["resumo"]["recomendados"] >= len(r["itens"])
    for x in r["itens"]:
        assert x["uso_vida_pct"] >= 100 or x["reducao_pp"] >= 15
        assert x["p30_novo"] <= x["p30"] and x["motivos"]
    # Padrão 4: a marca frágil domina as câmeras a trocar
    cams = [m_ for m_ in r["resumo"]["marcas"] if m_["tipo"] == "CAM"]
    assert cams and cams[0]["marca"] == "Hikvision"
    nomes = {x["nome"] for x in m["modelos"]}
    assert {"falha_equipamento_7d", "ocorrencias_regiao_hora", "furto_equipamento_30d"} <= nomes
    for x in m["modelos"]:
        assert x["situacao"] in ("ok", "atencao", "retreinar") and any(c["verificacao"] == "idade" for c in x["verificacoes"])
    assert "Saúde dos modelos" in s["markdown"] and "Fim de vida útil" in s["markdown"]


def test_monitor_pede_retreino_de_modelo_velho(banco_gerado):
    eng = _treinado(banco_gerado)
    with Session(eng) as db:
        fim = db.execute(text("SELECT treino_fim FROM modelo_versao WHERE ativo AND nome = 'furto_equipamento_30d'")).scalar()
        agora = pd.Timestamp(fim, tz="UTC") + pd.Timedelta(days=60)
        m = monitor.avaliar(db, agora.to_pydatetime())
    x = next(x for x in m["modelos"] if x["nome"] == "furto_equipamento_30d")
    assert x["situacao"] == "retreinar" and m["situacao"] == "retreinar"
