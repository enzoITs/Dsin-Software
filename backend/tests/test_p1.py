"""Parte 3, fase 4: P1, risco de falha de equipamento."""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from app.preditivo import p1
from app.preditivo import variaveis as V


def _sintetico(n_cortes: int = 12, por_corte: int = 800) -> pd.DataFrame:
    """Frota inventada em que a marca X falha muito mais: o modelo precisa achar isso."""
    r = np.random.default_rng(1)
    partes = []
    for k in range(n_cortes):
        n = por_corte
        df = pd.DataFrame({
            "corte": V.corte_local(pd.Timestamp("2026-01-05").date() + pd.Timedelta(days=7 * k)),
            "prefixo": r.choice(["CAM", "RAD"], n), "marca": r.choice(["x", "y", "z"], n),
            "modelo": r.choice(["m1", "m2"], n), "regiao": r.choice(["Centro", "Sul"], n),
            "movel": False, "velocidade_maxima": np.nan, "idade_dias": r.integers(30, 2000, n),
        })
        for c in p1.NUMERICAS:
            if c not in df:
                df[c] = r.random(n) * 10
        risco = np.where(df.marca == "x", 0.25, 0.03)
        df["falha_7d"] = (r.random(n) < risco).astype(int)
        df["falha_30d"] = df.falha_7d
        partes.append(df)
    df = pd.concat(partes, ignore_index=True)
    for c in V.CATEGORICAS_EQUIPAMENTO:
        df[c] = df[c].astype("category")
    return df


def test_modelo_acha_o_padrao_e_explica():
    df = _sintetico()
    m = p1.ajustar(df, 7)
    novo = df[df.corte == df.corte.max()]
    p = m.prever(novo)
    assert p[novo.marca == "x"].mean() > 3 * p[novo.marca != "x"].mean()
    imp = p1.importancia_global(m, novo)
    assert next(iter(imp)) == "equipamento"                        # marca e modelo pesam mais
    fs = p1.fatores(m, novo.head(50))
    assert all(1 <= len(x) <= 4 for x in fs)
    for f in fs[0]:
        assert "_" not in f["descricao"] and f["descricao"]          # linguagem do gestor, sem nome de variável
    x = novo.marca.to_numpy() == "x"
    efeito_equip = [next(f["efeito"] for f in fs_i if f["grupo"] == "equipamento")
                    for fs_i, xi in zip(fs, x[:50]) if xi and any(f["grupo"] == "equipamento" for f in fs_i)]
    assert efeito_equip and min(efeito_equip) > 0


def test_efeitos_somam_a_diferenca_para_o_tipico():
    df = _sintetico()
    m = p1.ajustar(df, 7)
    linha = df[df.corte == df.corte.max()].head(20)
    todos = p1.fatores(m, linha, top=len(p1.GRUPOS))
    contrib, ref = m.contribuicoes(linha)
    base = float(m.calibrador.predict([1 / (1 + np.exp(-ref))])[0])
    for fs, p in zip(todos, m.prever(linha)):
        assert sum(f["efeito"] for f in fs) == pytest.approx(p - base, abs=0.01)


def test_frases_do_gestor():
    x = {"idade_dias": 700, "modelo": "VIP 5450", "marca": "INTELBRAS ", "atraso_preventiva": 21,
         "falhas_90d": 0, "falhas_180d": 1, "dias_chuva_forte_previstos_7d": 2, "dias_chuva_forte_7d": 0,
         "tmax_prevista_7d": 34.2, "furtos_bairro_90d": 0, "velocidade_maxima": 90, "regiao": "Leste"}
    assert p1.frase("idade", x) == "Instalado há 23 meses"
    assert p1.frase("equipamento", x) == "Modelo VIP 5450 (Intelbras)"
    assert p1.frase("manutencao", x) == "Manutenção preventiva atrasada há 21 dias"
    assert p1.frase("manutencao", {**x, "atraso_preventiva": -10}) == "Manutenção preventiva em dia (próxima em 10 dias)"
    assert p1.frase("manutencao", {**x, "atraso_preventiva": float("nan")}).startswith("Sem manutenção preventiva")
    assert p1.frase("falhas", x) == "1 falha nos últimos 180 dias"
    assert p1.frase("chuva", x) == "Chuva forte prevista em 2 dias da próxima semana"
    assert p1.frase("calor", x) == "Temperatura prevista de até 34 °C nos próximos 7 dias"
    assert p1.frase("local", x) == "Via de 90 km/h, região Leste"


def test_faixa_nivel_e_acao():
    lo, hi = p1.faixa(0.3)
    assert lo < 0.3 < hi and hi - lo < 0.15
    assert p1.faixa(0.3, n=3000)[1] - p1.faixa(0.3, n=3000)[0] < hi - lo
    lim = [0.05, 0.12, 0.25]
    assert [p1.nivel(p, lim) for p in (0.01, 0.06, 0.2, 0.4)] == ["BAIXO", "MODERADO", "ALTO", "MUITO_ALTO"]
    a = p1.acao(0.4, "MUITO_ALTO", "RAD", "RAD-0042", 42, pd.Timestamp("2026-10-26").date())
    assert a["tipo"] == "ABRIR_ORDEM_SERVICO" and a["parametros"]["equipamento_id"] == 42 and "28/10" in a["texto"]
    assert p1.acao(0.01, "BAIXO", "RAD", "RAD-0042", 42, pd.Timestamp("2026-10-26").date())["tipo"] == "NENHUMA"


def test_p1_supera_o_baseline_e_grava_cartoes_completos(banco_gerado):
    """Portão de qualidade: o teste falha se o modelo não superar o baseline em AUC e Brier no backtest."""
    eng, rodar = banco_gerado
    saida = rodar("app.preditivo.treinar", "--todos")
    assert "previsões de P1 gravadas" in saida
    with eng.connect() as c:
        for janela in (7, 30):
            m, b = c.execute(text("SELECT metricas, metricas_baseline FROM modelo_versao WHERE ativo AND nome = :n"),
                             {"n": f"falha_equipamento_{janela}d"}).one()
            assert m["auc"] > b["auc"], (janela, m["auc"], b["auc"])
            assert m["brier"] < b["brier"], (janela, m["brier"], b["brier"])
            assert m["precisao_50"] > b["precisao_50"]
            assert m["logistica"]["auc"] > 0.5
        linhas = c.execute(text("""SELECT valor, faixa_inferior, faixa_superior, nivel, fatores, dados_considerados, detalhe
                                   FROM previsao WHERE modulo = 'P1' ORDER BY valor DESC LIMIT 200""")).all()
    assert len(linhas) == 200
    for v, lo, hi, niv, fat, dados, det in linhas:
        assert lo <= v <= hi and niv
        assert fat and dados and det["como_ajuda"] and det["o_que_preve"].startswith("Probabilidade de falha")
        assert det["acao_recomendada"]["texto"] and det["acao_recomendada"]["tipo"]
        q = det["qualidade_do_modelo"]
        assert q["modelo"] > q["baseline"] and q["metrica"] == "AUC"
