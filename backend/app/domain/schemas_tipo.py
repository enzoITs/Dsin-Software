"""Validação dos atributos específicos de cada tipo via JSON Schema.

O mesmo schema gera o formulário no front (react-jsonschema-form) e valida aqui.
"""

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.domain.estados import RegraViolada

TIPOS_PERMITIDOS = {"string", "number", "integer", "boolean", "array"}


def validar_schema(schema: dict[str, Any]) -> None:
    """Confere se um schema criado pela interface é válido e simples o bastante para virar formulário."""
    if schema.get("type") != "object":
        raise RegraViolada("schema_invalido", "O schema de atributos precisa ser do tipo 'object'.")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise RegraViolada("schema_invalido", f"Schema inválido: {exc.message}") from exc
    for nome, prop in (schema.get("properties") or {}).items():
        if prop.get("type") not in TIPOS_PERMITIDOS:
            raise RegraViolada(
                "schema_invalido", f"Campo '{nome}' com tipo não suportado: {prop.get('type')}."
            )
    for obrig in schema.get("required", []):
        if obrig not in (schema.get("properties") or {}):
            raise RegraViolada("schema_invalido", f"Campo obrigatório '{obrig}' não está definido.")


def validar_atributos(schema: dict[str, Any], atributos: dict[str, Any]) -> list[dict]:
    """Devolve a lista de erros por campo (vazia se tudo certo)."""
    validador = Draft202012Validator(schema)
    erros = []
    for err in sorted(validador.iter_errors(atributos), key=lambda e: list(e.path)):
        campo = ".".join(str(p) for p in err.path) or None
        if err.validator == "required":
            campo = err.message.split("'")[1]
        erros.append({"campo": campo, "mensagem": err.message})
    return erros


def com_ordem(schema: dict[str, Any]) -> dict[str, Any]:
    """O banco (JSONB) não guarda a ordem das chaves; a ordem dos campos vai numa lista."""
    return {**schema, "x-ordem": list((schema.get("properties") or {}).keys())}
