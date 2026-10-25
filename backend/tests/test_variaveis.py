"""Parte 3, fase 3: variáveis sem vazamento, baselines e backtest de origem móvel."""

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.preditivo import avaliacao, backtest, baselines, calendario
from app.preditivo import variaveis as V

HOJE = datetime.now(timezone.utc).astimezone(V.corte_local(date.today()).tzinfo).date()
CORTE_DIA = HOJE - timedelta(days=30)
CORTE = V.corte_local(CORTE_DIA)


def _sql(db, sql, **p):
    db.execute(text(sql), p)


def _evento(db, eid, em, anterior, nova):
    _sql(db, """INSERT INTO historico_situacao (equipamento_id, situacao_anterior, situacao_nova, motivo, usuario, em)
                VALUES (:e, CAST(:a AS situacao), CAST(:n AS situacao), 'teste', 'teste', :em)""",
         e=eid, a=anterior, n=nova, em=em)


def _ocorrencia(db, em, bairro=1, categoria="ACIDENTE", gravidade=2):
    _sql(db, """INSERT INTO ocorrencia (categoria, gravidade, inicio_em, geom, regiao_id, bairro_id, origem)
                VALUES (:c, :g, :em, ST_SetSRID(ST_MakePoint(-46.635, -23.55), 4326),
                        (SELECT id FROM regiao WHERE nome = 'Centro'), :b, 'simulada')""",
         c=categoria, g=gravidade, em=em, b=bairro)


@pytest.fixture
def cenario(radar):
    """Três radares em operação desde muito antes do corte, com falhas, manutenções e ocorrências no passado."""
    ids = [radar(numero_serie=f"PK-{i}", dispositivo_iot_id=f"IOT-{i}")["id"] for i in range(3)]
    with SessionLocal() as db:
        calendario.garantir(db, CORTE_DIA - timedelta(days=80), HOJE + timedelta(days=10))
        for eid in ids:
            _sql(db, "UPDATE equipamento SET data_instalacao = :d WHERE id = :e", d=CORTE_DIA - timedelta(days=500), e=eid)
            _evento(db, eid, CORTE - pd.Timedelta(days=400), "nao_instalado", "operacional")
            _sql(db, """INSERT INTO plano_manutencao (equipamento_id, tipo, proxima_data, periodicidade_dias, ativo, criado_em, atualizado_em)
                        VALUES (:e, 'periodica', :d, 90, true, now(), now())""", e=eid, d=CORTE_DIA)
        _evento(db, ids[0], CORTE - pd.Timedelta(days=20), "operacional", "mau_funcionamento")
        _evento(db, ids[0], CORTE - pd.Timedelta(days=18), "mau_funcionamento", "em_manutencao")
        _evento(db, ids[0], CORTE - pd.Timedelta(days=15), "em_manutencao", "operacional")
        _sql(db, """INSERT INTO registro_manutencao (equipamento_id, executada_em, tecnico, resultado, plano_id, criado_em, atualizado_em)
                    VALUES (:e, :em, 'T', 'concluida', (SELECT min(id) FROM plano_manutencao WHERE equipamento_id = :e), now(), now())""",
             e=ids[1], em=CORTE - pd.Timedelta(days=120))
        for k in range(1, 70):  # ocorrências diárias às 10 h nas 10 semanas antes do corte
            _ocorrencia(db, CORTE - pd.Timedelta(days=k) + pd.Timedelta(hours=10))
        _sql(db, """INSERT INTO escala_agente (equipe, orgao_id, regiao_id, inicio_em, fim_em, agentes, origem)
                    VALUES ('Alfa', 1, (SELECT id FROM regiao WHERE nome = 'Centro'), :a, :b, 4, 'escala')""",
             a=CORTE - pd.Timedelta(days=1), b=CORTE + pd.Timedelta(days=5))
        db.commit()
    return ids


def _variaveis():
    with SessionLocal() as db:
        f = V.carregar(db)
    eq = V.equipamentos(f, [CORTE]).sort_values("id").reset_index(drop=True)
    bh = V.bairro_hora(f, [CORTE]).sort_values(["bairro_id", "em"]).reset_index(drop=True)
    return eq, bh


def test_sem_vazamento_depois_do_corte(cenario):
    """Tudo o que acontece depois do corte muda os alvos, mas nenhuma variável."""
    eq1, bh1 = _variaveis()
    assert len(eq1) == 3 and eq1.falha_7d.sum() == 0
    ids = cenario
    with SessionLocal() as db:
        _evento(db, ids[1], CORTE + pd.Timedelta(days=2), "operacional", "mau_funcionamento")
        _evento(db, ids[1], CORTE + pd.Timedelta(days=3), "mau_funcionamento", "em_manutencao")
        _sql(db, """INSERT INTO registro_manutencao (equipamento_id, executada_em, tecnico, resultado, plano_id, criado_em, atualizado_em)
                    VALUES (:e, :em, 'T', 'concluida', NULL, now(), now())""", e=ids[1], em=CORTE + pd.Timedelta(days=4))
        _evento(db, ids[1], CORTE + pd.Timedelta(days=4), "em_manutencao", "operacional")
        _evento(db, ids[2], CORTE + pd.Timedelta(hours=3), "operacional", "furtado")
        for h in range(0, 72, 5):
            _ocorrencia(db, CORTE + pd.Timedelta(hours=h, minutes=10), categoria="PERTURBACAO", gravidade=3)
        db.commit()
    eq2, bh2 = _variaveis()

    alvos_eq = ["falha_7d", "falha_30d"]
    pd.testing.assert_frame_equal(eq1.drop(columns=alvos_eq), eq2.drop(columns=alvos_eq))
    assert eq2.falha_7d.sum() == 1                                  # o futuro chegou aos alvos
    alvos_bh = ["ocorrencias", "gravidade"]
    pd.testing.assert_frame_equal(bh1.drop(columns=alvos_bh), bh2.drop(columns=alvos_bh))
    assert bh2.ocorrencias.sum() > bh1.ocorrencias.sum()


def test_variaveis_do_equipamento(cenario):
    eq, _ = _variaveis()
    um = eq[eq.id == cenario[0]].iloc[0]
    assert um.falhas_30d == 1 and um.falhas_7d == 0 and um.dias_desde_falha == 20
    dois = eq[eq.id == cenario[1]].iloc[0]
    assert dois.dias_desde_preventiva == 120 and dois.atraso_preventiva == 120 - dois.periodicidade
    assert um.idade_dias == 500


def test_variaveis_do_bairro_e_baseline_sazonal(cenario):
    _, bh = _variaveis()
    centro = bh[bh.bairro == "Centro"]
    assert len(centro) == V.HORIZONTE_H and set(centro.horizonte_h) == set(range(1, 73))
    dez = centro[centro.hora == 10].iloc[0]                          # uma ocorrência às 10 h todo dia
    assert dez.media_mesma_hora == pytest.approx(1.0) and dez.oc_semana_anterior == 1
    assert centro.oc_24h_origem.iloc[0] == 1 and centro.oc_168h_origem.iloc[0] == 7
    assert (centro.agentes > 0).all()
    assert (baselines.p2_prever(centro) == centro.media_mesma_hora.to_numpy()).all()
    with pytest.raises(ValueError):
        with SessionLocal() as db:
            V.bairro_hora(V.carregar(db), [CORTE], horizonte=200)


def test_baseline_p1_taxa_do_tipo(cenario):
    with SessionLocal() as db:
        f = V.carregar(db)
    taxa = baselines.p1_taxas(f, CORTE, 365)
    assert taxa["RAD"] == pytest.approx(1 / (3 * 365))
    linhas = V.equipamentos(f, [CORTE])
    p = baselines.p1_prever(f, linhas, 7)
    assert np.allclose(p, 1 - (1 - 1 / (3 * 365)) ** 7)


def test_cortes_do_backtest():
    fim = date(2026, 10, 25)
    c7 = backtest.cortes(fim, 91, 7, 7)
    assert c7[0] == fim - timedelta(days=91) and len(c7) == 13
    assert all(b - a == timedelta(days=7) for a, b in zip(c7, c7[1:]))
    assert c7[-1] + timedelta(days=7) <= fim
    c30 = backtest.cortes(fim, 91, 7, 30)
    assert c30[-1] + timedelta(days=30) <= fim and len(c30) < len(c7)
    origens = backtest.origens_do_corte(fim - timedelta(days=7), 7, fim)
    assert len(origens) == 5                                         # as 2 últimas não cabem 72 h antes do fim


def test_metricas():
    y = np.array([0, 0, 1, 1, 0, 1])
    m = avaliacao.classificacao(y, np.array([0.1, 0.2, 0.9, 0.8, 0.3, 0.7]), top=3)
    assert m["auc"] == 1.0 and m["precisao_3"] == 1.0
    assert sum(c["n"] for c in m["calibracao"]) == 6
    assert avaliacao.ganho(0.84, 0.61, menor_melhor=False) == pytest.approx(37.7, abs=0.1)
    assert avaliacao.ganho(1.0, 2.0, menor_melhor=True) == pytest.approx(50)


def test_baselines_avaliados_e_registrados(banco_gerado):
    eng, rodar = banco_gerado
    saida = rodar("app.preditivo.treinar", "--baselines")
    assert "baseline P2" in saida
    with eng.connect() as c:
        ativos = dict(c.execute(text("SELECT nome, id FROM modelo_versao WHERE ativo")).all())
        assert {"baseline_falha_7d", "baseline_falha_30d", "baseline_ocorrencias", "baseline_disponibilidade_30d"} <= set(ativos)
        n = c.execute(text("SELECT count(*) FROM backtest_resultado WHERE modelo_versao_id = :i"),
                      {"i": ativos["baseline_falha_7d"]}).scalar()
        assert n == 13                                               # 90 dias, um corte por semana
        m = c.execute(text("SELECT metricas FROM modelo_versao WHERE id = :i"), {"i": ativos["baseline_ocorrencias"]}).scalar()
        assert m["mae"] > 0 and m["mae_pico"] is not None
        estado = c.execute(text("SELECT valor FROM estado_preditivo WHERE chave = 'treino'")).scalar()
        assert estado["situacao"] == "pronto"
