"""Parte 3, fase 11: copiloto (C3) com e sem IA, e briefing diário (C4)."""

import json
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import text

from app.db import SessionLocal
from app.preditivo import copiloto, prever
from app.services import ia


def _previsoes_de_hoje():
    """Um lote mínimo de P2 e P3 para hoje no Centro, com origem agora."""
    agora = pd.Timestamp.now(tz="UTC").floor("h")
    dia = prever.hoje_local()
    with SessionLocal() as db:
        rid = db.execute(text("SELECT id FROM regiao WHERE nome = 'Centro'")).scalar()
        ini = agora
        fim = ini + pd.Timedelta(hours=3)
        det = {"origem": agora.isoformat(), "granularidade": "periodo", "periodo": "noite", "data_local": dia.isoformat(),
               "alvo": {"tipo": "regiao", "id": rid, "nome": "Centro", "regiao": "Centro"},
               "motivo_principal": "Show com 40 mil pessoas", "nivel_nome": "Muito alto"}
        p3 = db.execute(text("""INSERT INTO previsao (modulo, alvo_tipo, alvo_id, regiao_id, horizonte_inicio, horizonte_fim, valor,
                                nivel, fatores, dados_considerados, detalhe)
                                VALUES ('P3', 'regiao', :r, :r, :i, :f, 82, 'MUITO_ALTO', '[]', '[]', CAST(:d AS jsonb)) RETURNING id"""),
                        {"r": rid, "i": ini, "f": fim, "d": json.dumps(det)}).scalar()
        for k in range(3):
            h = ini + pd.Timedelta(hours=k)
            db.execute(text("""INSERT INTO previsao (modulo, alvo_tipo, alvo_id, regiao_id, horizonte_inicio, horizonte_fim, valor,
                               fatores, dados_considerados, detalhe)
                               VALUES ('P2', 'regiao', :r, :r, :i, :f, 6, '[]', '[]', CAST(:d AS jsonb))"""),
                       {"r": rid, "i": h, "f": h + pd.Timedelta(hours=1),
                        "d": json.dumps({"origem": agora.isoformat(), "normal": 4.0, "alvo": {"nome": "Centro"}})})
        db.execute(text("""INSERT INTO recomendacao (previsao_id, tipo, texto, parametros, impacto_estimado, estado, resultado)
                           VALUES (:p, 'REFORCAR_EQUIPES', 'Hoje à noite: reforçar a região Centro com +2 equipes', CAST(:par AS jsonb),
                                   '{}', 'pendente', '{}')"""),
                   {"p": p3, "par": json.dumps({"inicio": (ini + pd.Timedelta(hours=1)).isoformat(), "fim": fim.isoformat()})})
        db.commit()
    return p3


def test_prontas_sem_ia(client):
    p3 = _previsoes_de_hoje()
    r = client.get("/copiloto/perguntas-prontas").json()
    assert r["ia_disponivel"] is False and len(r["perguntas"]) >= 6
    risco = client.post("/copiloto/perguntar", json={"pronta": "risco_24h"}).json()
    assert risco["modo"] == "sem_ia" and "Centro" in risco["resposta"] and f"[prev_{p3}]" in risco["resposta"]
    assert risco["previsoes"] == [p3] and risco["ferramentas"][0]["nome"] == "risco_por_regiao"
    reforco = client.post("/copiloto/perguntar", json={"pergunta": "Onde preciso reforçar as equipes?"}).json()
    assert reforco["pronta"] == "reforco" and "+2 equipes" in reforco["resposta"]
    for p in copiloto.prontas():  # nenhuma quebra, mesmo sem modelos treinados
        x = client.post("/copiloto/perguntar", json={"pronta": p["id"]})
        assert x.status_code == 200 and x.json()["resposta"], p["id"]
    fora = client.post("/copiloto/perguntar", json={"pergunta": "qual a capital da França?"}).json()
    assert fora["modo"] == "sem_ia" and "perguntas prontas" in fora["resposta"]
    assert client.post("/copiloto/perguntar", json={"pergunta": " "}).status_code == 422


class _ClienteFalso:
    """Faz o papel do SDK: primeiro pede uma ferramenta, depois responde com texto."""

    def __init__(self, **_):
        self.chamadas = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.chamadas.append(kw)
        if len(self.chamadas) == 1:
            bloco = SimpleNamespace(type="tool_use", id="tu_1", name="risco_por_regiao", input={"horas": 24, "regiao": None})
            return SimpleNamespace(stop_reason="tool_use", content=[bloco])
        resultado = kw["messages"][-1]["content"][0]
        assert resultado["type"] == "tool_result" and resultado["tool_use_id"] == "tu_1"
        pid = json.loads(resultado["content"])["periodos"][0]["previsao_id"]
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=f"Centro à noite [prev_{pid}]")])


def test_com_ia_usa_ferramentas_e_cai_para_sem_ia(client, monkeypatch):
    p3 = _previsoes_de_hoje()
    falso = _ClienteFalso()
    monkeypatch.setattr(ia, "disponivel", lambda: True)
    monkeypatch.setattr(copiloto.anthropic, "Anthropic", lambda **kw: falso)
    r = client.post("/copiloto/perguntar", json={"pergunta": "Onde vai ser pior hoje?",
                                                 "historico": [{"papel": "user", "texto": "oi"}]}).json()
    assert r["modo"] == "ia" and r["resposta"] == f"Centro à noite [prev_{p3}]" and r["previsoes"] == [p3]
    assert r["ferramentas"] == [{"nome": "risco_por_regiao", "entrada": {"horas": 24, "regiao": None}}]
    primeira = falso.chamadas[0]
    assert primeira["model"] == ia.MODELO and primeira["fallbacks"] == "default" and len(primeira["tools"]) == len(copiloto.FERRAMENTAS)
    assert all(t["strict"] and t["input_schema"]["additionalProperties"] is False for t in primeira["tools"])
    assert primeira["messages"][0] == {"role": "user", "content": "oi"}

    def quebra(**_):
        raise copiloto.anthropic.APIConnectionError(request=SimpleNamespace(method="POST", url="x"))
    monkeypatch.setattr(copiloto.anthropic, "Anthropic", lambda **kw: SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(create=quebra))))
    r = client.post("/copiloto/perguntar", json={"pergunta": "Tem alguma anomalia?"}).json()
    assert r["modo"] == "sem_ia" and r["pronta"] == "anomalias" and "não respondeu" in r["motivo"]


def test_briefing_do_dia(client):
    p3 = _previsoes_de_hoje()
    b = client.get("/briefing/hoje").json()
    assert b["data"] == prever.hoje_local().isoformat() and b["titulo"].startswith("Briefing de")
    ids = [s["id"] for s in b["secoes"]]
    assert ids == ["resumo", "risco", "reforcos", "manutencao", "anomalias", "contexto", "acertometro"]
    resumo = " ".join(i["texto"] for i in b["secoes"][0]["itens"])
    assert "Centro" in resumo and "muito alto" in resumo and "acima do normal" in resumo
    assert any(i["previsao_id"] == p3 for i in b["secoes"][1]["itens"])
    assert "+2 equipes" in b["secoes"][2]["itens"][0]["texto"]
    assert b["markdown"].startswith("# Briefing de") and "## Acertômetro de ontem" in b["markdown"] and "sintéticos" in b["rodape"]
    assert client.get("/briefing/hoje").json()["id"] == b["id"]  # gerado uma vez por dia
    assert client.post("/briefing/gerar", headers={"X-Perfil": "operador", "X-Orgao-Id": "1"}).status_code == 403
    assert client.post("/briefing/gerar").json()["id"] == b["id"]
    assert client.get("/briefing").json()[0]["data"] == b["data"]
    assert client.get(f"/briefing/{b['data']}").status_code == 200
    assert client.get("/briefing/2001-01-01").status_code == 404
