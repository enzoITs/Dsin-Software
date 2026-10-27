"""Parte 3, fase 12: tendência de disponibilidade (P6), risco de furto (P7), carga de manutenção (P8) e expansão (C2)."""

import json

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.preditivo import baselines, diarias, expansao, p6, p7, preventivos
from app.preditivo import variaveis as V


# ---------------------------------------------------------------- P6

def test_p6_segue_a_queda_e_nao_inventa_tendencia():
    r = np.random.default_rng(3)
    plano = 0.97 + r.normal(0, 0.002, 365)
    queda = np.concatenate([plano[:245], np.linspace(0.97, 0.91, 120)]) + r.normal(0, 0.002, 365)
    real_90 = 0.91 - 0.0005 * 90  # a queda continua no mesmo ritmo
    prev = p6.prever_serie(queda, 90)
    media_30 = queda[-30:].mean()
    assert prev[-1] < queda[-1] < media_30                       # segue a tendência para baixo
    assert abs(prev[-1] - real_90) < abs(media_30 - real_90)       # melhor que a média móvel (baseline)
    assert prev[29] > prev[-1]                                     # amortecida, mas ainda caindo
    estavel = p6.prever_serie(plano, 90)
    assert abs(estavel[-1] - plano[-30:].mean()) < 0.005           # série plana não ganha tendência


def test_p6_seguindo_p1_faixa_e_nivel():
    g = p6.ganho_seguindo_p1(evitadas_mes=30, dias_conserto=10, em_servico=1000, dias=90)
    assert g[0] == pytest.approx(1 / 1000) and g[9] == pytest.approx(10 / 1000) and g[-1] == pytest.approx(10 / 1000)
    assert p6.ganho_seguindo_p1(30, 10, 0, 5).sum() == 0
    f = p6.faixa({30: 0.01, 90: 0.02}, 90)
    assert f[0] < f[29] == pytest.approx(0.01) and f[-1] == pytest.approx(0.02)
    assert p6.nivel(0.89, 0.91, 0.90) == "ABAIXO_META"
    assert p6.nivel(0.905, 0.95, 0.90) == "ATENCAO"
    assert p6.nivel(0.96, 0.96, 0.90) == "NORMAL"
    fs = p6.fatores(0.92, 0.905, 12, 0.004, 30, 14, 8)
    assert fs[0]["grupo"] == "tendencia" and fs[0]["efeito"] == pytest.approx(-1.5)
    assert "recuperariam 0,4 ponto" in fs[1]["descricao"] and "cidade: 8" in fs[-1]["descricao"]


def test_p6_baseline_media_movel():
    serie = pd.DataFrame({"dia": pd.date_range("2026-01-01", periods=60).date, "regiao": "Leste",
                          "disponibilidade": np.linspace(1, 0.9, 60)})
    b = baselines.p6_prever(serie, serie.dia.iloc[-1], 30, 30)
    assert b.previsto.iloc[0] == pytest.approx(serie.disponibilidade.iloc[-31:-1].mean())


# ---------------------------------------------------------------- P7

def _furtos_sinteticos(n_cortes: int = 10, por_corte: int = 3000) -> pd.DataFrame:
    """Furtos inventados: muito mais comuns onde já houve furto por perto e não há câmera a menos de 300 m."""
    r = np.random.default_rng(7)
    partes = []
    for k in range(n_cortes):
        n = por_corte
        df = pd.DataFrame({"corte": V.corte_local(pd.Timestamp("2026-01-05").date() + pd.Timedelta(days=7 * k)),
                           "prefixo": r.choice(["CAM", "RAD", "TOT"], n), "movel": False, "idade_dias": r.integers(30, 2000, n),
                           "furtos_bairro_90d": r.poisson(1, n), "furtos_bairro_365d": r.poisson(4, n),
                           "furtos_500m_365d": r.poisson(0.3, n), "vandalismo_madrugada_bairro_90d": r.poisson(5, n),
                           "dist_camera_m": r.exponential(200, n), "agentes_madrugada": r.uniform(5, 30, n)})
        risco = 0.002 * np.where(df.furtos_500m_365d > 0, 8, 1) * np.where(df.dist_camera_m > 300, 5, 1)
        df["furto_30d"] = (r.random(n) < risco).astype(int)
        partes.append(df)
    return pd.concat(partes, ignore_index=True)


def test_p7_acha_furtos_e_camera_e_explica_sem_falar_de_pessoas():
    df = _furtos_sinteticos()
    m = p7.ajustar(df)
    x = df[df.corte == df.corte.max()]
    perto = x[x.furtos_500m_365d > 0]
    longe = perto.assign(dist_camera_m=1000.0)
    com_camera = perto.assign(dist_camera_m=50.0)
    assert m.prever(longe).mean() > 2 * m.prever(com_camera).mean()     # câmera por perto reduz o risco
    assert m.prever(perto).mean() > 2 * m.prever(x[x.furtos_500m_365d == 0]).mean()
    fs = p7.fatores(m, x.head(40))
    for f in fs[0]:
        assert f["descricao"] and "_" not in f["descricao"]
    assert p7.frase("cobertura", {"dist_camera_m": 480}) .startswith("Sem câmera em operação a menos de 300 m")
    assert p7.frase("historico_local", {"furtos_500m_365d": 2, "furtos_bairro_365d": 5}).startswith("2 furtos")
    for c in p7.COLUNAS:  # só lugares e equipamentos
        assert not any(t in c for t in ("pessoa", "cpf", "placa", "rosto", "nome"))


def test_p7_nivel_e_acao():
    lim = [0.004, 0.012, 0.03]
    assert [p7.nivel(p, lim) for p in (0.001, 0.005, 0.02, 0.05)] == ["BAIXO", "MODERADO", "ALTO", "MUITO_ALTO"]
    a = p7.acao("ALTO", "CAM-0001", 1, 450, "Leste")
    assert a["tipo"] == "INCLUIR_RONDA_NOTURNA" and a["parametros"]["avaliar_camera"] and "Expansão" in a["texto"]
    assert p7.acao("BAIXO", "CAM-0001", 1, 450, "Leste")["tipo"] == "NENHUMA"


# ---------------------------------------------------------------- P8

def test_p8_avaliacao_soma_por_tipo_e_regiao():
    df = pd.DataFrame({"corte": [1, 1, 1, 1], "regiao": ["A", "A", "B", "B"], "prefixo": ["CAM"] * 4,
                       "y": [1, 0, 1, 1], "p": [0.5, 0.5, 0.9, 0.9], "p_base": [0.1, 0.1, 0.1, 0.1]})
    r = diarias.avaliar_p8(df)
    assert r["modelo"]["mae"] == pytest.approx((0 + 0.2) / 2)
    assert r["baseline"]["mae"] == pytest.approx((0.8 + 1.8) / 2)
    assert r["modelo"]["mae"] < r["baseline"]["mae"]


# ---------------------------------------------------------------- alerta e decisão

def _inserir_p6(db, rid: int, detalhe: dict, valor: float = 0.88, acao: dict | None = None) -> int:
    corte = V.corte_local(pd.Timestamp.now(tz=V.FUSO).date())
    d = {"horizonte_dias": 30, "meta": 0.9, "atual": 0.92, "seguindo_p1": 0.905,
         "alvo": {"tipo": "regiao", "id": rid, "nome": "Centro", "regiao": "Centro"}, "o_que_preve": "Disponibilidade",
         "acao_recomendada": acao or {"tipo": "NENHUMA", "texto": "x", "parametros": {}}, **detalhe}
    return db.execute(text("""
        INSERT INTO previsao (modulo, alvo_tipo, alvo_id, regiao_id, horizonte_inicio, horizonte_fim, valor, nivel, fatores,
                              dados_considerados, detalhe)
        VALUES ('P6', 'regiao', :r, :r, :i, :f, :v, 'ABAIXO_META', '[]', '[]', CAST(:d AS jsonb)) RETURNING id"""),
        {"r": rid, "i": corte.to_pydatetime(), "f": (corte + pd.Timedelta(days=30)).to_pydatetime(), "v": valor,
         "d": json.dumps(d)}).scalar()


def test_alerta_de_disponibilidade_dispara_e_resolve(client):
    agora = pd.Timestamp.now(tz="UTC")
    with SessionLocal() as db:
        rid = db.execute(text("SELECT id FROM regiao WHERE nome = 'Centro'")).scalar()
        pid = _inserir_p6(db, rid, {"cruza_meta_em": (agora.tz_convert(V.FUSO) + pd.Timedelta(days=12)).date().isoformat()})
        db.commit()
        assert preventivos.verificar(db, agora.to_pydatetime())["disponibilidade"] == 1
        msg, dados = db.execute(text("""SELECT mensagem, dados FROM alerta WHERE tipo::text = 'previsao_disponibilidade'
                                        AND resolvido_em IS NULL""")).one()
    assert msg.startswith("Previsto para") and "meta de 90%" in msg and "92,0%" in msg and "90,5%" in msg
    assert dados["preditivo"]["previsao_id"] == pid and dados["preditivo"]["modulo"] == "P6"
    with SessionLocal() as db:
        db.execute(text("UPDATE previsao SET detalhe = detalhe - 'cruza_meta_em' WHERE id = :i"), {"i": pid})
        db.commit()
        assert preventivos.verificar(db, agora.to_pydatetime())["resolvidas"] == 1


def test_priorizar_manutencao_abre_as_os(client, radar):
    eq = radar()
    with SessionLocal() as db:
        rid = db.execute(text("SELECT id FROM regiao WHERE nome = 'Centro'")).scalar()
        pid = _inserir_p6(db, rid, {}, acao={"tipo": "PRIORIZAR_MANUTENCAO", "texto": "Priorizar a manutenção da região Centro",
                                             "parametros": {"equipamento_ids": [eq["id"]]}})
        db.commit()
    c = client.post(f"/previsoes/{pid}/decisao", json={"acao": "aceitar"}).json()
    assert c["recomendacao"]["estado"] == "aceita"
    assert c["recomendacao"]["resultado"]["execucao"]["novas"] == 1
    with SessionLocal() as db:
        assert db.execute(text("SELECT count(*) FROM ordem_servico WHERE equipamento_id = :e AND status = 'aberta'"),
                          {"e": eq["id"]}).scalar() == 1


def test_telas_sem_previsoes(client):
    for u in ("/tendencias/disponibilidade", "/tendencias/manutencao", "/furtos/risco"):
        r = client.get(u)
        assert r.status_code == 409 and r.json()["detail"]["codigo"] == "sem_previsao"


# ---------------------------------------------------------------- banco gerado

def _treinado(banco_gerado):
    eng, rodar = banco_gerado
    with eng.connect() as c:
        tem = c.execute(text("SELECT count(*) FROM modelo_versao WHERE nome = 'furto_equipamento_30d' AND ativo")).scalar()
    if not tem:
        rodar("app.preditivo.treinar", "--todos")
    return eng


def test_p6_p7_p8_no_banco_gerado(banco_gerado):
    """Portão de qualidade de P7 (supera a taxa do tipo em AUC) e de P8 (supera a taxa do tipo no erro de falhas)."""
    eng = _treinado(banco_gerado)
    with eng.connect() as c:
        mv = {n: (m, b) for n, m, b in c.execute(text("""SELECT nome, metricas, metricas_baseline FROM modelo_versao
            WHERE ativo AND nome IN ('disponibilidade_regiao', 'furto_equipamento_30d', 'carga_manutencao')"""))}
        assert set(mv) == {"disponibilidade_regiao", "furto_equipamento_30d", "carga_manutencao"}
        m, b = mv["furto_equipamento_30d"]
        assert m["auc"] > b["auc"], (m["auc"], b["auc"])
        m, b = mv["carga_manutencao"]
        assert m["mae"] < b["mae"], (m["mae"], b["mae"])
        m, _ = mv["disponibilidade_regiao"]
        assert m["mae_pp"] is not None and m["q90"]
        for mod in ("P6", "P7", "P8"):
            linhas = c.execute(text("""SELECT valor, faixa_inferior, faixa_superior, nivel, fatores, dados_considerados, detalhe
                                       FROM previsao WHERE modulo = :m ORDER BY valor DESC LIMIT 50"""), {"m": mod}).all()
            assert linhas, mod
            for v, lo, hi, niv, fat, dados, det in linhas:
                assert lo <= v <= hi and niv and fat and dados, mod
                assert det["o_que_preve"] and det["como_ajuda"] and det["acao_recomendada"]["tipo"]
                assert det["qualidade_do_modelo"]["metrica"]
        # Padrão 11: a região sem preventiva é a que mais cai na tendência
        queda = c.execute(text("""SELECT detalhe->'alvo'->>'nome', valor - (detalhe->>'atual')::float FROM previsao
                                  WHERE modulo = 'P6' AND alvo_tipo = 'regiao' AND (detalhe->>'horizonte_dias')::int = 90
                                  ORDER BY 2 LIMIT 1""")).one()
        assert queda[0] == "Leste"
        # Padrão 6: os bairros dos furtos plantados lideram o risco previsto
        topo = [b for (b,) in c.execute(text("""SELECT detalhe->'alvo'->>'bairro' FROM previsao WHERE modulo = 'P7'
                                                GROUP BY 1 ORDER BY avg(valor) DESC LIMIT 2"""))]
        assert set(topo) == {"Brás", "Itaquera"}


def test_expansao_sugere_pontos_sem_camera(banco_gerado):
    eng = _treinado(banco_gerado)
    with Session(eng) as db:
        r = expansao.calcular(db, n=6)
        dmin = 800
    s = r["sugestoes"]
    assert s and r["resumo"]["cobertura_com_sugestoes_pct"] >= r["resumo"]["cobertura_hoje_pct"]
    for x in s:
        assert x["camera_mais_proxima_m"] > 300 and x["motivos"] and x["bairro"]
    xy = p7._metros(np.array([x["lon"] for x in s]), np.array([x["lat"] for x in s]))
    for i in range(len(s)):
        for j in range(i + 1, len(s)):
            assert np.hypot(*(xy[i] - xy[j])) >= dmin - 1
    assert [x["pontuacao"] for x in s] == sorted((x["pontuacao"] for x in s), reverse=True)
