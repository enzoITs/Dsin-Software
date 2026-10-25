"""Parte 3, fase 6: P4, recomendação de reforço de agentes."""

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.preditivo import p4

REGIOES = ["Centro", "Sul", "Leste", "Norte", "Oeste"]


def _caso(semente: int, n_equipes: int = 18, muito_alto: str | None = None):
    r = np.random.default_rng(semente)
    equipes = [p4.Equipe(f"e{i}", f"Equipe {i}", str(r.choice(["CET", "GCM", "PM"])), str(r.choice(REGIOES)),
                         float(r.integers(40, 160)), 20) for i in range(n_equipes)]
    regioes = [p4.Regiao(n, float(r.uniform(50, 700)), peso=float(r.uniform(1, 3)), muito_alto=n == muito_alto)
               for n in REGIOES]
    return equipes, regioes


@pytest.mark.parametrize("semente", range(12))
def test_otimizacao_respeita_restricoes_e_nao_piora(semente):
    equipes, regioes = _caso(semente)
    r = p4.otimizar(equipes, regioes, max_deslocamentos=4)
    assert r.metodo == "otimizacao"
    assert p4.violacoes(r.alocacao, equipes, regioes, 4) == []
    assert r.nao_coberto_depois <= r.nao_coberto_antes + 1e-6
    g = p4.guloso(equipes, regioes, max_deslocamentos=4)
    assert p4.violacoes(g.alocacao, equipes, regioes, 4) == []          # heurística de reserva: solução válida
    assert p4.nao_coberto(g.alocacao, equipes, regioes) <= r.nao_coberto_antes + 1e-6
    assert r.nao_coberto_depois <= p4.nao_coberto(g.alocacao, equipes, regioes) + 1e-6  # ótima ≤ gulosa


def test_recomendacao_reduz_o_risco_nao_coberto():
    # Centro com muita demanda e pouca gente; Sul e Norte sobrando.
    equipes = [p4.Equipe("c1", "A", "CET", "Centro", 100), p4.Equipe("s1", "B", "CET", "Sul", 100),
               p4.Equipe("s2", "C", "GCM", "Sul", 100), p4.Equipe("s3", "D", "CET", "Sul", 100),
               p4.Equipe("n1", "E", "PM", "Norte", 100), p4.Equipe("n2", "F", "PM", "Norte", 100)]
    regioes = [p4.Regiao("Centro", 400, peso=3), p4.Regiao("Sul", 120), p4.Regiao("Norte", 90)]
    r = p4.otimizar(equipes, regioes, max_deslocamentos=4)
    assert r.nao_coberto_antes == pytest.approx(900)
    assert r.nao_coberto_depois < r.nao_coberto_antes and r.reducao_pct > 50
    destinos = {m["para"] for m in r.por_regiao["_movimentos"]}
    assert destinos == {"Centro"}
    # Sul guarda a GCM (órgão que já tinha) e cada região fica com pelo menos uma equipe
    assert p4.violacoes(r.alocacao, equipes, regioes, 4) == []
    assert any(r.alocacao[e.id] == "Sul" and e.orgao == "GCM" for e in equipes)


def test_limites_de_deslocamento_e_regioes_fixas():
    equipes, regioes = _caso(3)
    parada = p4.otimizar(equipes, regioes, max_deslocamentos=0)
    assert parada.alocacao == {e.id: e.regiao for e in equipes} and parada.movimentos == 0
    um = p4.otimizar(equipes, regioes, max_deslocamentos=1)
    assert um.movimentos <= 1
    fixa = p4.otimizar(equipes, regioes, max_deslocamentos=6, fixas={"Sul"})
    assert all(fixa.alocacao[e.id] == "Sul" for e in equipes if e.regiao == "Sul")
    assert p4.violacoes(fixa.alocacao, equipes, regioes, 6, fixas={"Sul"}) == []


def test_muito_alto_recebe_reforco():
    equipes, regioes = _caso(5, muito_alto="Norte")
    for reg in regioes:
        reg.demanda = 0 if reg.nome == "Norte" else reg.demanda    # mesmo sem falta, risco muito alto ganha reforço
    r = p4.otimizar(equipes, regioes, max_deslocamentos=4)
    antes = sum(1 for e in equipes if e.regiao == "Norte")
    depois = sum(1 for v in r.alocacao.values() if v == "Norte")
    assert depois >= antes + 1


def test_menos_equipes_aumenta_risco_nao_coberto():
    equipes, regioes = _caso(7)
    todos = p4.nao_coberto({e.id: e.regiao for e in equipes}, equipes, regioes)
    menos = equipes[1:]
    assert p4.nao_coberto({e.id: e.regiao for e in menos}, menos, regioes) >= todos


def test_sem_equipes_devolve_escala_atual():
    r = p4.otimizar([], [p4.Regiao("Centro", 100)])
    assert r.metodo == "escala_atual" and r.nao_coberto_antes == 100 == r.nao_coberto_depois


def test_api_sem_previsoes(client):
    assert client.get("/planejamento/equipes").status_code == 409
    assert client.post("/planejamento/equipes/recalcular", json={}).status_code == 409


def test_planejamento_gravado_no_banco_gerado(banco_gerado):
    eng, rodar = banco_gerado
    from app.preditivo import planejamento

    with eng.connect() as c:
        tem = c.execute(text("SELECT count(*) FROM previsao WHERE modulo = 'P3'")).scalar()
    if not tem:
        rodar("app.preditivo.treinar", "--todos")
    with Session(eng) as db:
        planos = planejamento.planejar(db)
        res = planejamento.resumo_json(planos)
        gravado = planejamento.gravar(db, planos, planejamento.ultima_origem(db))
    assert len(res["periodos"]) >= 12
    assert res["nao_coberto_depois"] <= res["nao_coberto_antes"]
    for p in res["periodos"]:
        for m in p["movimentos"]:
            assert m["de"] != m["para"]
    with eng.connect() as c:
        n = c.execute(text("SELECT count(*) FROM previsao WHERE modulo = 'P4'")).scalar()
        recs = c.execute(text("SELECT texto, parametros, impacto_estimado FROM recomendacao WHERE estado = 'pendente'")).all()
        cartoes = c.execute(text("SELECT fatores, dados_considerados, detalhe FROM previsao WHERE modulo = 'P4'")).all()
    assert n == gravado["previsoes"] == 5 * len(res["periodos"])
    assert len(recs) == gravado["recomendacoes"]
    for t, par, imp in recs:
        assert "reforçar a região" in t and "Motivo:" in t and par["equipes"]
        assert imp["nao_coberto_depois"] <= imp["nao_coberto_antes"]
    for fat, dados, det in cartoes:
        assert fat and dados and det["como_ajuda"] and det["acao_recomendada"]["texto"] and det["o_que_preve"]


@pytest.mark.parametrize("semente", range(8))
def test_regiao_nao_cede_e_recebe_no_mesmo_periodo(semente):
    equipes, regioes = _caso(100 + semente, n_equipes=20)
    for r in (p4.otimizar(equipes, regioes, 6), p4.guloso(equipes, regioes, 6)):
        for reg in REGIOES:
            cede = any(e.regiao == reg and r.alocacao[e.id] != reg for e in equipes)
            recebe = any(e.regiao != reg and r.alocacao[e.id] == reg for e in equipes)
            assert not (cede and recebe), (reg, r.metodo)
