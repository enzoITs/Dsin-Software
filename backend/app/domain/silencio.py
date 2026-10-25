"""Falha silenciosa: equipamento operacional que parou de mandar sinal.

Não muda a situação sozinho; só gera alerta para alguém conferir.
Na Parte 2 o limite é `fator` vezes o intervalo esperado do tipo (padrão 3, em limites.py).
"""

from datetime import datetime, timedelta

from app.models.enums import Situacao


def esta_silencioso(
    situacao: Situacao,
    tem_dispositivo: bool,
    ultimo_sinal_em: datetime | None,
    intervalo_min: int,
    agora: datetime,
    fator: float = 1,
) -> bool:
    if situacao != Situacao.operacional or not tem_dispositivo:
        return False
    if ultimo_sinal_em is None:
        return True
    return agora - ultimo_sinal_em > timedelta(minutes=intervalo_min * fator)
