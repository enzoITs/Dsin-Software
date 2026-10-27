"""Parte 3, fase 5: P2 (ocorrências por região e hora) e P3 (índice de risco)."""

import pytest
from sqlalchemy import text

from app.domain import limites
from app.preditivo import p3

PESOS = limites.PADRAO["prev_p3_pesos"]


def _entrada(**extra) -> p3.Entrada:
    base = dict(previstas=4.0, normal=4.0, gravidade_media=2.0, gravidade_normal=2.0, fixos=100, indisponiveis=0,
                alto_risco=0, vigilancia=50, vigilancia_operando=50, vigilancia_risco=0, agentes=60, demanda_agentes=48)
    return p3.Entrada(**{**base, **extra})


def test_p3_dia_tranquilo_e_baixo():
    r = p3.indice(_entrada(), PESOS)
    assert r["nivel"] == "BAIXO" and r["indice"] < 25
    assert {c["componente"] for c in r["componentes"]} == set(p3.COMPONENTES)


def test_p3_soma_dos_componentes_e_o_indice():
    r = p3.indice(_entrada(previstas=9, indisponiveis=8, alto_risco=4, vigilancia_operando=42, agentes=30,
                           demanda_agentes=108, evento_publico=38_000, evento_nome="Show", chuva_mm=6), PESOS)
    assert sum(c["contribuicao"] for c in r["componentes"]) == pytest.approx(r["indice"], abs=0.1)
    assert sum(c["peso"] for c in r["componentes"]) == pytest.approx(1.0)
    for c in r["componentes"]:
        assert 0 <= c["nota"] <= 100 and c["contribuicao"] == pytest.approx(c["peso"] * c["nota"], abs=0.01)


def test_p3_casos_conhecidos():
    n = p3.notas(_entrada(previstas=8))                      # o dobro do normal
    assert n["ocorrencias"] == pytest.approx(60)
    assert p3.notas(_entrada(indisponiveis=15))["equipamentos"] == pytest.approx(100)
    assert p3.notas(_entrada(vigilancia_operando=45))["cobertura"] == pytest.approx(40)
    assert p3.notas(_entrada(agentes=24, demanda_agentes=48))["agentes"] == pytest.approx(500 / 6, abs=0.1)
    assert p3.notas(_entrada())["agentes"] == 0                 # escala cobre a demanda
    assert p3.notas(_entrada(evento_publico=20_000))["externos"] == pytest.approx(50)
    assert p3.notas(_entrada(tempestade=True))["externos"] == 100
    # Tudo no máximo: muito alto
    pior = _entrada(previstas=20, indisponiveis=20, vigilancia_operando=30, agentes=0, evento_publico=60_000)
    assert p3.indice(pior, PESOS)["nivel"] == "MUITO_ALTO" and p3.indice(pior, PESOS)["indice"] == 100


def test_p3_faixas_e_periodos():
    assert [p3.faixa(v)[0] for v in (0, 24.9, 25, 49.9, 50, 74.9, 75, 100)] == \
        ["BAIXO", "BAIXO", "MODERADO", "MODERADO", "ALTO", "ALTO", "MUITO_ALTO", "MUITO_ALTO"]
    assert [p3.periodo_da_hora(h) for h in (0, 5, 6, 11, 12, 17, 18, 23)] == \
        ["madrugada", "madrugada", "manha", "manha", "tarde", "tarde", "noite", "noite"]
    junto = p3.somar([_entrada(previstas=2, agentes=10), _entrada(previstas=3, agentes=5, evento_publico=12_000, evento_nome="Jogo")])
    assert junto.previstas == 5 and junto.agentes == 15 and junto.evento_publico == 12_000 and junto.evento_nome == "Jogo"


def test_p3_pesos_configuraveis():
    e = _entrada(evento_publico=40_000)
    so_externos = {c: 0 for c in p3.COMPONENTES} | {"externos": 1}
    assert p3.indice(e, so_externos)["indice"] == 100


def test_p2_supera_o_baseline_e_grava_cartoes(banco_gerado):
    """Portão de qualidade: o teste falha se P2 não superar o sazonal ingênuo em MAE no backtest."""
    eng, rodar = banco_gerado
    with eng.connect() as c:
        tem = c.execute(text("SELECT count(*) FROM modelo_versao WHERE nome = 'ocorrencias_regiao_hora' AND ativo")).scalar()
    if not tem:
        rodar("app.preditivo.treinar", "--todos")
    with eng.connect() as c:
        m, b = c.execute(text("SELECT metricas, metricas_baseline FROM modelo_versao "
                              "WHERE ativo AND nome = 'ocorrencias_regiao_hora'")).one()
        assert m["mae"] < b["mae"], (m["mae"], b["mae"])
        assert m["erro_pct"] < b["erro_pct"]
        assert 0.8 <= m["cobertura_90"] <= 0.97
        # Só o lote mais recente: outro teste pode ter treinado de novo numa hora diferente
        ult = "detalhe->>'origem' = (SELECT max(detalhe->>'origem') FROM previsao WHERE modulo = 'P2')"
        p2 = c.execute(text("SELECT valor, faixa_inferior, faixa_superior, fatores, dados_considerados, detalhe "
                            f"FROM previsao WHERE modulo = 'P2' AND {ult}")).all()
        p3_ = c.execute(text("SELECT valor, faixa_inferior, faixa_superior, nivel, fatores, detalhe "
                             f"FROM previsao WHERE modulo = 'P3' AND {ult}")).all()
    regioes = 5
    assert len(p2) == regioes * 72
    for v, lo, hi, fat, dados, det in p2:
        assert lo <= v <= hi and fat and dados and det["como_ajuda"] and det["acao_recomendada"]["texto"]
        assert det["o_que_preve"].startswith("Ocorrências esperadas") and det["por_categoria"]
    horas = [x for x in p3_ if x[5]["granularidade"] == "hora"]
    periodos = [x for x in p3_ if x[5]["granularidade"] == "periodo"]
    assert len(horas) == regioes * 72 and len(periodos) >= regioes * 12
    for v, lo, hi, niv, fat, det in p3_:
        assert 0 <= v <= 100 and lo <= v <= hi and niv in {"BAIXO", "MODERADO", "ALTO", "MUITO_ALTO"}
        assert sum(c["contribuicao"] for c in det["componentes"]) == pytest.approx(v, abs=0.2)
        assert len(fat) == 5 and det["motivo_principal"]
