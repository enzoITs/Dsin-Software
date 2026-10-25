"""Regra única de disponibilidade, usada por todas as partes do F.O.G.O.

"Ainda não instalado" e "desativado" ficam fora da conta.
Disponibilidade = operacionais / (operacionais + mau funcionamento + em manutenção + furtados)
"""

from app.models.enums import Situacao

DISPONIVEIS = {Situacao.operacional}
INDISPONIVEIS = {Situacao.mau_funcionamento, Situacao.em_manutencao, Situacao.furtado}
FORA_DA_CONTA = {Situacao.nao_instalado, Situacao.desativado}


def calcular(contagem: dict[Situacao, int]) -> dict:
    disponiveis = sum(contagem.get(s, 0) for s in DISPONIVEIS)
    indisponiveis = sum(contagem.get(s, 0) for s in INDISPONIVEIS)
    base = disponiveis + indisponiveis
    return {
        "disponibilidade": round(disponiveis / base, 4) if base else None,
        "disponiveis": disponiveis,
        "indisponiveis": indisponiveis,
        "fora_da_conta": sum(contagem.get(s, 0) for s in FORA_DA_CONTA),
        "por_situacao": {s.value: contagem.get(s, 0) for s in Situacao},
    }
