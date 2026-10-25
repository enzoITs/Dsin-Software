"""Perfil de quem chama a API.

Não há login nesta parte: o painel envia o perfil escolhido em cabeçalhos.
Operador e técnico enxergam e alteram só o próprio órgão; gestor e PROMETHEUS veem tudo.
"""

from dataclasses import dataclass
from typing import Annotated
from urllib.parse import unquote

from fastapi import Depends, Header, HTTPException

PERFIS = {"gestor", "operador", "tecnico", "prometheus"}


@dataclass
class Contexto:
    perfil: str
    orgao_id: int | None
    usuario: str

    @property
    def restrito(self) -> bool:
        return self.perfil in ("operador", "tecnico")

    def pode_alterar(self, orgao_id: int) -> bool:
        if self.perfil == "prometheus":
            return False
        return not self.restrito or self.orgao_id == orgao_id

    def exigir_alterar(self, orgao_id: int) -> None:
        if not self.pode_alterar(orgao_id):
            raise HTTPException(403, {"codigo": "sem_permissao", "mensagem": "Seu perfil não pode alterar dados de outro órgão."})

    def exigir_gestor(self) -> None:
        if self.perfil != "gestor":
            raise HTTPException(403, {"codigo": "sem_permissao", "mensagem": "Apenas o gestor municipal pode fazer isso."})


def contexto(
    x_perfil: Annotated[str | None, Header()] = None,
    x_orgao_id: Annotated[int | None, Header()] = None,
    x_usuario: Annotated[str | None, Header()] = None,
) -> Contexto:
    perfil = (x_perfil or "gestor").lower()
    if perfil not in PERFIS:
        raise HTTPException(400, {"codigo": "perfil_invalido", "mensagem": f"Perfil deve ser um de {sorted(PERFIS)}"})
    if perfil in ("operador", "tecnico") and x_orgao_id is None:
        raise HTTPException(400, {"codigo": "orgao_obrigatorio", "mensagem": "Operador e técnico precisam do cabeçalho X-Orgao-Id."})
    return Contexto(perfil=perfil, orgao_id=x_orgao_id, usuario=unquote(x_usuario or f"{perfil}"))


Ctx = Annotated[Contexto, Depends(contexto)]
