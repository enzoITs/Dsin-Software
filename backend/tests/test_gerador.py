"""Parte 3, fase 2: gerador de histórico com padrões plantados.

Funções puras (rápido) e um teste integrado num banco à parte: seed, central, histórico da
cidade, conferência de todos os padrões por consulta e reprodutibilidade (mesma semente, mesmos dados).
"""

from datetime import date, timedelta

import numpy as np
import pytest
from sqlalchemy import text

from app.preditivo import gerador_cidade as G
from app.preditivo import gerador_equipamentos as GE
from app.preditivo import padroes as P


# ---------- vida dos equipamentos ----------


def _frota(n: int = 400) -> list[dict]:
    r = np.random.default_rng(7)
    frota = []
    for i in range(1, n + 1):
        pref = ["CAM", "RAD", "TOT"][i % 3]
        frota.append({
            "id": i, "prefixo": pref, "marca": ["Hikvision", "Axis"][i % 2] if pref == "CAM" else "Perkons",
            "atributos": {"modalidade": "velocidade", "velocidade_maxima": 90} if pref == "RAD" else {},
            "instalado_em": date(2026, 10, 1) - timedelta(days=int(r.integers(30, 2000))), "desativado_em": None,
            "regiao": ["Leste", "Sul"][i % 2], "bairro": "Brás" if i % 10 == 0 else "Sé",
            "lon": -46.6 + r.normal(0, 0.01), "lat": -23.55 + r.normal(0, 0.01), "movel": False, "periodicidade": 120,
        })
    return frota


def _clima(inicio: date, dias: int) -> dict:
    return {inicio + timedelta(days=k - 1): (float(k % 7 == 0) * 20, 34.0 if k % 11 == 0 else 26.0) for k in range(dias + 2)}


def test_vida_dos_equipamentos_reprodutivel():
    inicio, fim = date(2026, 4, 1), date(2026, 10, 1)
    frota, clima = _frota(), _clima(inicio, (fim - inicio).days)
    a = GE.simular(frota, inicio, fim, clima, 42, ["Técnico"])
    b = GE.simular(frota, inicio, fim, clima, 42, ["Técnico"])
    c = GE.simular(frota, inicio, fim, clima, 43, ["Técnico"])
    assert a.historicos == b.historicos and a.registros == b.registros and a.situacao == b.situacao
    assert a.historicos != c.historicos
    assert len(a.historicos) > 100


def test_vida_respeita_a_maquina_de_estados():
    from app.domain.estados import TRANSICOES

    inicio, fim = date(2026, 1, 1), date(2026, 10, 1)
    res = GE.simular(_frota(), inicio, fim, _clima(inicio, (fim - inicio).days), 1, ["Técnico"])
    por_eq: dict[int, list] = {}
    for h in res.historicos:
        por_eq.setdefault(h["equipamento_id"], []).append(h)
    for hs in por_eq.values():
        hs.sort(key=lambda h: h["em"])
        for ant, prox in zip(hs, hs[1:]):
            assert prox["situacao_anterior"] == ant["situacao_nova"]
            assert prox["situacao_nova"] in TRANSICOES[prox["situacao_anterior"]]
            assert prox["em"] > ant["em"]


def test_risco_de_falha_tem_os_padroes():
    um = np.ones(1)
    base = dict(base=um * 0.002, idade_dias=um * 900, fragil=np.array([False]), rodovia=np.array([False]),
                atraso_dias=um * 0, fragilidade=um, chuva_ontem_mm=0.0, temp_max_c=25.0)
    ref = P.risco_falha_dia(**base)[0]
    assert P.risco_falha_dia(**{**base, "fragil": np.array([True])})[0] == pytest.approx(ref * 3)
    assert P.risco_falha_dia(**{**base, "fragil": np.array([True]), "chuva_ontem_mm": 15.0})[0] == pytest.approx(ref * 6)
    assert P.risco_falha_dia(**{**base, "fragil": np.array([True]), "idade_dias": um * 300})[0] < ref  # nova: sem efeito
    assert P.risco_falha_dia(**{**base, "rodovia": np.array([True]), "temp_max_c": 33.0})[0] == pytest.approx(ref * 4)
    assert P.risco_falha_dia(**{**base, "rodovia": np.array([True]), "temp_max_c": 31.0})[0] == pytest.approx(ref)
    assert P.risco_falha_dia(**{**base, "atraso_dias": um * 16})[0] == pytest.approx(ref * 2)
    assert P.risco_falha_dia(**{**base, "atraso_dias": um * 15})[0] == pytest.approx(ref)


# ---------- ocorrências, eventos, séries ----------

BAIRROS = [{"nome": "Sé", "regiao": "Centro", "peso": 1.0}, {"nome": "Casa Verde", "regiao": "Norte", "peso": 1.0},
           {"nome": "Brás", "regiao": "Centro", "peso": 1.0}, {"nome": "Moema", "regiao": "Sul", "peso": 1.0}]
SECO = np.zeros(24)


def _lam(dow, chuva=SECO, feriado=False, vespera=False):
    return P.intensidade_dia(BAIRROS, dow, feriado, vespera, chuva)


def test_intensidade_centro_sexta_a_noite():
    sexta, quinta = _lam(4), _lam(3)
    assert sexta[0, 20].sum() >= 2 * quinta[0, 20].sum()       # Sé (Centro)
    assert sexta[3, 20].sum() == pytest.approx(quinta[3, 20].sum(), rel=0.3)  # Moema (Sul): sem padrão 1


def test_intensidade_chuva_e_alagamento():
    chuva = np.zeros(24)
    chuva[16] = 12.0
    seco, molhado = _lam(2), _lam(2, chuva)
    i = P.IDX["ACIDENTE"]
    assert molhado[3, 16, i] == pytest.approx(seco[3, 16, i] * P.FATOR_CHUVA_ACIDENTE)
    a = P.IDX["ALAGAMENTO"]
    assert molhado[1, 16, a] > 10 * molhado[3, 16, a] > 0       # Casa Verde (baixo) muito acima de Moema
    assert seco[:, :, a].sum() == 0


def test_intensidade_picos_e_vespera():
    c = P.IDX["CONGESTIONAMENTO"]
    util, vespera, domingo = _lam(1), _lam(1, vespera=True), _lam(6)
    assert util[3, 8, c] > 3 * util[3, 11, c]
    assert vespera[3, 18, c] == pytest.approx(util[3, 18, c] * P.FATOR_VESPERA)
    assert domingo[3, 8, c] < util[3, 8, c] / 5
    assert _lam(1, feriado=True)[3, 8, c] == pytest.approx(domingo[3, 8, c])


def test_vandalismo_de_madrugada_nos_bairros_de_furto():
    v = P.IDX["VANDALISMO"]
    lam = _lam(2)
    assert lam[2, 2, v] == pytest.approx(lam[0, 2, v] * P.FATOR_VANDALISMO_MADRUGADA)  # Brás × Sé às 2 h
    assert lam[2, 14, v] == pytest.approx(lam[0, 14, v])


def test_eventos_grandes_e_pequenos():
    assert P.extra_evento_hora(9_000) == 0
    assert P.extra_evento_hora(20_000) == pytest.approx(2 * P.extra_evento_hora(10_001), rel=0.01)
    a = [G.eventos_dia(date(2026, 3, 1) + timedelta(days=k), 42) for k in range(60)]
    b = [G.eventos_dia(date(2026, 3, 1) + timedelta(days=k), 42) for k in range(60)]
    assert a == b and sum(map(len, a)) > 20
    demo = G.evento_demo(date(2026, 10, 25))
    assert demo["publico_estimado"] > P.PUBLICO_GRANDE
    assert demo["inicio_em"].astimezone(G.FUSO).weekday() == 4


def test_series_com_anomalias_plantadas():
    series = {"radares": [1, 2, 3, 4], "cameras": [10, 11, 12, 13]}
    ref = date(2026, 10, 25)
    anom = G.anomalias_plantadas(series, ref)
    assert len(anom) == 6
    dia = ref - timedelta(days=1)
    assert G.series_dia(42, series, anom, dia) == G.series_dia(42, series, anom, dia)
    linhas = G.series_dia(42, series, anom, dia)
    radar = sum(v for e, m, _, v in linhas if e == 4)            # queda há 2 dias
    normal = sum(v for e, m, _, v in G.series_dia(42, series, anom, ref - timedelta(days=40)) if e == 4)
    assert radar < 0.5 * normal
    noite = [v for e, m, em, v in linhas if e == 13 and em.astimezone(G.FUSO).hour < 5]
    assert max(noite) < 10                                         # câmera que cai toda noite


# ---------- integrado: banco à parte ----------


def test_padroes_aparecem_em_consultas_diretas(banco_gerado):
    from sqlalchemy.orm import Session

    from app.preditivo.verificacao import verificar

    eng, _ = banco_gerado
    with Session(eng) as db:
        itens = verificar(db)
    falhas = [f"padrão {x['padrao']}: {x['descricao']} = {x['obtido']} (mínimo {x['minimo']})" for x in itens if not x["ok"]]
    assert not falhas, "\n".join(falhas)
    assert {x["padrao"] for x in itens} == {1, 2, 3, 4, 5, 6, 7, 8, 11, 12}


def _assinatura(eng) -> dict:
    with eng.connect() as c:
        return {
            "ocorrencias": c.execute(text("""
                SELECT count(*), md5(string_agg(categoria || gravidade || inicio_em::text || ST_AsText(geom), ','
                                                ORDER BY inicio_em, categoria, ST_AsText(geom)))
                FROM ocorrencia WHERE origem = 'simulada' AND inicio_em < '2026-10-25 03:00+00'""")).one(),
            "eventos": c.execute(text("SELECT count(*), md5(string_agg(nome || inicio_em::text, ',' ORDER BY inicio_em, nome)) "
                                      "FROM evento_cidade WHERE simulado")).one(),
            "series": c.execute(text("SELECT count(*), sum(valor) FROM serie_equipamento_hora "
                                     "WHERE em < '2026-10-25 03:00+00'")).one(),
            "historico": c.execute(text("SELECT count(*), md5(string_agg(equipamento_id || situacao_nova::text || em::text, ',' "
                                        "ORDER BY em, equipamento_id)) FROM historico_situacao")).one(),
        }


def test_mesma_semente_mesmos_dados(banco_gerado):
    eng, rodar = banco_gerado
    antes = _assinatura(eng)
    assert antes["ocorrencias"][0] > 50_000
    rodar("scripts.gerar_historico", "--forcar")
    depois = _assinatura(eng)
    assert antes == depois
