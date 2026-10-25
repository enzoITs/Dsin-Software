"""Regras sem banco: tabela de transições, disponibilidade, score e falha silenciosa."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain import disponibilidade, saude, silencio
from app.domain.estados import TRANSICOES, transicao_valida
from app.models.enums import Situacao as S

PERMITIDAS = {
    (S.nao_instalado, S.operacional), (S.nao_instalado, S.desativado),
    (S.operacional, S.mau_funcionamento), (S.operacional, S.em_manutencao),
    (S.operacional, S.furtado), (S.operacional, S.desativado),
    (S.mau_funcionamento, S.em_manutencao), (S.mau_funcionamento, S.furtado), (S.mau_funcionamento, S.desativado),
    (S.em_manutencao, S.operacional), (S.em_manutencao, S.furtado), (S.em_manutencao, S.desativado),
    (S.furtado, S.em_manutencao), (S.furtado, S.desativado),
    (S.desativado, S.em_manutencao),
}


@pytest.mark.parametrize("atual", list(S))
@pytest.mark.parametrize("nova", list(S))
def test_tabela_de_transicoes_igual_ao_documento(atual, nova):
    assert transicao_valida(atual, nova) == ((atual, nova) in PERMITIDAS)


def test_falha_nao_volta_direto_a_operacional():
    assert S.operacional not in TRANSICOES[S.mau_funcionamento]


def test_disponibilidade_ignora_nao_instalado_e_desativado():
    r = disponibilidade.calcular({S.operacional: 80, S.mau_funcionamento: 10, S.em_manutencao: 5,
                                  S.furtado: 5, S.nao_instalado: 100, S.desativado: 50})
    assert r["disponibilidade"] == 0.8
    assert r["fora_da_conta"] == 150


def test_disponibilidade_sem_base():
    assert disponibilidade.calcular({S.nao_instalado: 3})["disponibilidade"] is None


def fatos(**kw):
    base = dict(situacao=S.operacional, falhas_90d=0, furtos_365d=0, dias_manutencao_atrasada=0,
                sem_sinal=False, tem_dispositivo_iot=True, data_instalacao=date(2026, 1, 1),
                ultima_manutencao=datetime(2026, 5, 1, tzinfo=timezone.utc))
    base.update(kw)
    return saude.FatosSaude(**base)


def test_score_exemplo_do_documento():
    # "62 porque: 2 falhas em 90 dias (−20), manutenção atrasada há 5 dias (−18)"
    score, motivos = saude.calcular(fatos(falhas_90d=2, dias_manutencao_atrasada=5), date(2026, 10, 17))
    assert score == 62
    assert [(m["texto"], m["pontos"]) for m in motivos] == [
        ("2 falhas em 90 dias", -20), ("manutenção atrasada há 5 dias", -18)]


def test_score_perfeito_sem_motivos():
    assert saude.calcular(fatos(), date(2026, 10, 17)) == (100, [])


def test_score_nunca_negativo():
    score, _ = saude.calcular(fatos(situacao=S.furtado, falhas_90d=9, furtos_365d=3, dias_manutencao_atrasada=90,
                                    sem_sinal=True, tem_dispositivo_iot=False, data_instalacao=date(2010, 1, 1),
                                    ultima_manutencao=None), date(2026, 10, 17))
    assert score == 0


AGORA = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def test_silencio_alem_do_intervalo():
    assert silencio.esta_silencioso(S.operacional, True, AGORA - timedelta(minutes=16), 15, AGORA)
    assert not silencio.esta_silencioso(S.operacional, True, AGORA - timedelta(minutes=14), 15, AGORA)


def test_silencio_so_vale_para_operacional_com_iot():
    velho = AGORA - timedelta(days=3)
    assert not silencio.esta_silencioso(S.em_manutencao, True, velho, 15, AGORA)
    assert not silencio.esta_silencioso(S.operacional, False, velho, 15, AGORA)
    assert silencio.esta_silencioso(S.operacional, True, None, 15, AGORA)
