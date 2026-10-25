"""Endereço a partir do CEP. Sem internet, o CEP vira campo opcional e o endereço é digitado."""

import re

import httpx


class CepIndisponivel(Exception):
    pass


def consultar(cep: str) -> dict | None:
    digitos = re.sub(r"\D", "", cep)
    if len(digitos) != 8:
        return None
    try:
        r = httpx.get(f"https://viacep.com.br/ws/{digitos}/json/", timeout=4)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise CepIndisponivel(str(exc)) from exc
    dados = r.json()
    if dados.get("erro"):
        return None
    return {
        "cep": dados.get("cep"),
        "rua": dados.get("logradouro"),
        "bairro": dados.get("bairro"),
        "cidade": dados.get("localidade"),
        "uf": dados.get("uf"),
    }
