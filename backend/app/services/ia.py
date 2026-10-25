"""Recursos de IA do Atalaia, via Claude.

1. extrair_cadastro: foto da etiqueta e/ou frase livre -> sugestão de cadastro.
2. interpretar_busca: pergunta em linguagem natural -> filtros estruturados.

A IA nunca grava nada: a resposta volta como sugestão, é validada aqui contra os
schemas e as listas reais do banco, e só então vai para a tela, onde a pessoa revisa.
Sem chave de API ou sem internet, os endpoints respondem 503 e a tela segue manual.
"""

import base64
import json
import logging
import unicodedata
from typing import Any

import anthropic

from app.config import settings
from app.domain.estados import RegraViolada

log = logging.getLogger("atalaia.ia")

MODELO = settings.anthropic_model or "claude-opus-5-5"
# Em recusa por política, o servidor reexecuta a mesma chamada num modelo de fallback.
BETAS = ["server-side-fallback-2026-07-01"]


def disponivel() -> bool:
    return bool(settings.anthropic_api_key)


def _cliente() -> anthropic.Anthropic:
    if not disponivel():
        raise RegraViolada(
            "ia_indisponivel",
            "IA indisponível: defina ANTHROPIC_API_KEY no .env. O cadastro e a busca por filtros continuam funcionando.",
            status=503,
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=90.0, max_retries=1)


def _nulo(tipo: dict) -> dict:
    return {"anyOf": [tipo, {"type": "null"}]}


def _chamar(system: str, conteudo: list[dict], schema: dict, effort: str) -> dict:
    cliente = _cliente()
    try:
        resp = cliente.beta.messages.create(
            model=MODELO,
            max_tokens=16000,
            betas=BETAS,
            fallbacks="default",
            system=system,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": conteudo}],
        )
    except anthropic.AuthenticationError:
        raise RegraViolada("ia_indisponivel", "Chave da API do Claude inválida. Confira ANTHROPIC_API_KEY.", status=503)
    except anthropic.RateLimitError:
        raise RegraViolada("ia_ocupada", "Limite de uso da IA atingido. Tente de novo em instantes.", status=503)
    except anthropic.APIConnectionError:
        raise RegraViolada("ia_indisponivel", "Sem conexão com a IA. Siga com o preenchimento manual.", status=503)
    except anthropic.APIStatusError as exc:
        log.warning("erro da API do Claude: %s", exc)
        raise RegraViolada("ia_erro", "A IA não respondeu agora. Siga com o preenchimento manual.", status=503)

    if resp.stop_reason == "refusal":
        raise RegraViolada("ia_recusou", "A IA não processou este pedido. Preencha manualmente.", status=422)
    if resp.stop_reason == "max_tokens":
        raise RegraViolada("ia_erro", "Resposta da IA incompleta. Tente uma descrição mais curta.", status=503)
    texto = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.warning("IA devolveu JSON inválido: %r", texto[:300])
        raise RegraViolada("ia_erro", "Resposta da IA em formato inesperado.", status=503)


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").strip()


# ---------- 1. Cadastro por foto ou texto ----------

SCHEMA_CADASTRO = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tipo_id", "marca", "modelo", "numero_serie", "dispositivo_iot_id", "atributos_json",
                 "rua", "referencia", "cep", "bairro", "observacoes"],
    "properties": {
        "tipo_id": _nulo({"type": "integer"}),
        "marca": _nulo({"type": "string"}),
        "modelo": _nulo({"type": "string"}),
        "numero_serie": _nulo({"type": "string"}),
        "dispositivo_iot_id": _nulo({"type": "string"}),
        "atributos_json": {"type": "string"},
        "rua": _nulo({"type": "string"}),
        "referencia": _nulo({"type": "string"}),
        "cep": _nulo({"type": "string"}),
        "bairro": _nulo({"type": "string"}),
        "observacoes": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM_CADASTRO = """Você ajuda a cadastrar equipamentos urbanos (radares, câmeras, totens, veículos etc.) num inventário municipal.
Recebe uma foto de etiqueta/placa de identificação e/ou uma descrição livre em português e devolve os campos do cadastro.

Regras:
- Preencha só o que estiver na foto ou no texto. Campo sem evidência fica null. Nunca invente número de série, MAC ou IMEI.
- tipo_id: escolha um dos tipos listados pelo id; null se nenhum servir.
- atributos_json: um objeto JSON (como string) só com chaves do schema do tipo escolhido, respeitando os valores de enum exatamente como escritos. "{}" se não houver.
- Endereço: rua sem o número; o número ou a posição vai em referencia ("número 181", "oposto ao 181", "KM 203", "S/N").
- bairro: só se citado, com o nome como na lista de bairros quando houver correspondência.
- observacoes: até 3 frases curtas em português sobre o que ficou incerto ou precisa de conferência."""


def extrair_cadastro(texto: str | None, imagem: bytes | None, media_type: str | None,
                     tipos: list[dict], bairros: list[str]) -> dict:
    catalogo = [
        {"id": t["id"], "nome": t["nome"], "mobilidade": t["mobilidade"], "schema": t["schema_atributos"].get("properties", {}),
         "obrigatorios": t["schema_atributos"].get("required", [])}
        for t in tipos
    ]
    conteudo: list[dict] = []
    if imagem:
        conteudo.append({"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                       "data": base64.standard_b64encode(imagem).decode()}})
    conteudo.append({"type": "text", "text": (
        f"Tipos disponíveis:\n{json.dumps(catalogo, ensure_ascii=False)}\n\n"
        f"Bairros oficiais: {', '.join(bairros)}\n\n"
        + (f"Descrição: {texto}" if texto else "Use só a foto.")
    )})
    return _chamar(SYSTEM_CADASTRO, conteudo, SCHEMA_CADASTRO, effort="medium")


# ---------- 2. Busca em linguagem natural ----------

SITUACOES = ["nao_instalado", "operacional", "mau_funcionamento", "em_manutencao", "desativado", "furtado"]
REGIOES = ["Centro", "Norte", "Sul", "Leste", "Oeste"]
MANUTENCAO = ["em_dia", "proxima", "vencida"]

SCHEMA_BUSCA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tipo_ids", "situacoes", "orgaos", "regioes", "bairros", "status_manutencao", "sem_sinal",
                 "score_max", "atributos_json", "texto", "interpretacao"],
    "properties": {
        "tipo_ids": {"type": "array", "items": {"type": "integer"}},
        "situacoes": {"type": "array", "items": {"type": "string", "enum": SITUACOES}},
        "orgaos": {"type": "array", "items": {"type": "string"}},
        "regioes": {"type": "array", "items": {"type": "string", "enum": REGIOES}},
        "bairros": {"type": "array", "items": {"type": "string"}},
        "status_manutencao": {"type": "array", "items": {"type": "string", "enum": MANUTENCAO}},
        "sem_sinal": {"type": "boolean"},
        "score_max": _nulo({"type": "integer"}),
        "atributos_json": {"type": "string"},
        "texto": _nulo({"type": "string"}),
        "interpretacao": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM_BUSCA = """Você converte perguntas de gestores municipais sobre o inventário de equipamentos em filtros estruturados.
Use só os filtros e valores disponíveis. Listas vazias significam "sem filtro".
- "Centro", "Zona Norte" etc. são regiões; nomes de bairro vão em bairros (use o nome da lista).
- "manutenção vencendo" ou "perto de vencer" = status_manutencao ["proxima", "vencida"]; "vencida" = ["vencida"].
- "parados", "sem sinal", "mudos" = sem_sinal true. "quebrados"/"com defeito" = situacoes ["mau_funcionamento"].
- "saúde ruim"/"em risco" = score_max 50.
- atributos_json: objeto JSON (como string) com chaves do schema dos tipos, ex.: "sem visão noturna" -> {"visao_noturna": false}. "{}" se não houver.
- texto: só para código, número de série, marca ou modelo citados literalmente; senão null.
- interpretacao: uma frase curta em português por filtro aplicado, ex.: "Tipo: câmera", "Região: Centro"."""


def interpretar_busca(pergunta: str, tipos: list[dict], orgaos: list[str], bairros: list[str]) -> dict:
    catalogo = [{"id": t["id"], "nome": t["nome"], "atributos": t["schema_atributos"].get("properties", {})} for t in tipos]
    conteudo = [{"type": "text", "text": (
        f"Tipos: {json.dumps(catalogo, ensure_ascii=False)}\nÓrgãos (siglas): {', '.join(orgaos)}\n"
        f"Bairros: {', '.join(bairros)}\n\nPergunta: {pergunta}"
    )}]
    return _chamar(SYSTEM_BUSCA, conteudo, SCHEMA_BUSCA, effort="low")


def casar_nome(nome: str | None, opcoes: dict[str, Any]) -> Any:
    """Acha a opção pelo nome ignorando acento e caixa."""
    if not nome:
        return None
    alvo = _sem_acento(nome)
    for k, v in opcoes.items():
        if _sem_acento(k) == alvo:
            return v
    return None
