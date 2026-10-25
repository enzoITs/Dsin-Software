"""Regras puras da Parte 2: nível pelo contexto, horário de pico e índice de saúde da região."""

from datetime import datetime

from app.domain import limites, regras
from app.domain.regras import Contexto
from app.models.enums import NivelAlerta as N
from app.models.enums import Situacao as S
from app.models.enums import TipoAlerta as R

CFG = limites.PADRAO


def test_nivel_inicial_de_cada_regra_segue_o_documento():
    assert regras.NIVEL_INICIAL[R.furto] == N.critica
    assert regras.NIVEL_INICIAL[R.incidente_correlacionado] == N.critica
    assert regras.NIVEL_INICIAL[R.mau_funcionamento] == N.alta
    assert regras.NIVEL_INICIAL[R.falha_silenciosa] == N.alta
    assert regras.NIVEL_INICIAL[R.regiao_descoberta] == N.alta
    for r in (R.sinal_degradado, R.manutencao_vencida, R.dispositivo_nao_cadastrado, R.agente_sem_posicao):
        assert regras.NIVEL_INICIAL[r] == N.media
    assert regras.NIVEL_INICIAL[R.manutencao_proxima] == N.baixa
    assert len(regras.NIVEL_INICIAL) == 10


def test_sem_contexto_fica_no_nivel_inicial():
    nivel, motivos = regras.decidir_nivel(R.falha_silenciosa, Contexto(situacao=S.operacional))
    assert nivel == N.alta and motivos == []


def test_cada_fator_de_contexto_sobe_um_nivel_e_explica():
    ctx = Contexto(situacao=S.operacional, sem_cobertura=True, nome_tipo="Câmera de videomonitoramento", raio_m=500)
    nivel, motivos = regras.decidir_nivel(R.sinal_degradado, ctx)
    assert nivel == N.alta
    assert motivos == ["Média → Alta: sem outra câmera operacional em 500 m"]

    ctx = Contexto(situacao=S.operacional, sem_cobertura=True, nome_tipo="Radar de fiscalização",
                   regiao="Norte", regiao_em_atencao=True, horario_pico=True)
    nivel, motivos = regras.decidir_nivel(R.sinal_degradado, ctx)
    assert nivel == N.critica  # média + 3, limitado a crítica
    assert motivos[0].startswith("Média → Alta: sem outro radar")
    assert motivos[1] == "Alta → Crítica: região Norte já em atenção"
    assert motivos[2].startswith("Já crítica; também: horário de pico")


def test_manutencao_planejada_suprime_mas_nunca_o_furto():
    ctx = Contexto(situacao=S.operacional, manutencao_em_andamento=True)
    assert regras.decidir_nivel(R.falha_silenciosa, ctx)[0] is None
    assert regras.decidir_nivel(R.mau_funcionamento, ctx)[0] is None
    assert regras.decidir_nivel(R.furto, ctx)[0] == N.critica


def test_desativado_ou_nao_instalado_nao_gera_alerta():
    for s in (S.desativado, S.nao_instalado):
        assert regras.decidir_nivel(R.falha_silenciosa, Contexto(situacao=s))[0] is None
        assert regras.decidir_nivel(R.furto, Contexto(situacao=s))[0] is None


def test_horario_de_pico_por_dia_e_hora():
    picos = [{"dias": [0, 1, 2, 3, 4], "inicio": "07:00", "fim": "09:30"}]
    segunda_8h = datetime(2026, 10, 26, 8, 0)
    assert regras.em_pico(picos, segunda_8h)
    assert not regras.em_pico(picos, datetime(2026, 10, 26, 9, 30))
    assert not regras.em_pico(picos, datetime(2026, 10, 25, 8, 0))  # domingo
    assert not regras.em_pico([], segunda_8h)


def test_indice_regiao_casos_conhecidos():
    assert regras.indice_regiao({}, 0.95, 3, CFG)["nota"] == 100
    r = regras.indice_regiao({"critica": 1}, 0.95, 3, CFG)
    assert r["nota"] == 75 and r["estado"] == "atencao"
    r = regras.indice_regiao({"critica": 1, "alta": 2}, 0.95, 3, CFG)
    assert r["nota"] == 55 and r["estado"] == "atencao"
    r = regras.indice_regiao({"alta": 1}, 0.85, 0, CFG)  # -10, -5 (85% < 90%), -20 sem agentes
    assert r["nota"] == 65
    assert {f["fator"] for f in r["fatores"]} == {"alta", "disponibilidade", "sem_agentes"}
    r = regras.indice_regiao({"critica": 2}, 0.95, 3, CFG)
    assert r["nota"] == 50 and r["estado"] == "atencao"
    assert regras.indice_regiao({"critica": 3}, 0.95, 3, CFG)["estado"] == "critica"
    assert regras.indice_regiao({"critica": 9}, 0.2, 0, CFG)["nota"] == 0  # nunca abaixo de 0


def test_indice_regiao_media_tem_teto():
    r = regras.indice_regiao({"media": 100}, 1.0, 5, CFG)
    assert r["nota"] == 100 - CFG["saude_teto_media"]
    assert regras.indice_regiao({"media": 2}, 1.0, 5, CFG)["nota"] == 94


def test_indice_regiao_sem_equipamento_nao_penaliza_disponibilidade():
    assert regras.indice_regiao({}, None, 2, CFG)["nota"] == 100
