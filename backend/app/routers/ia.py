import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from geoalchemy2.shape import to_shape
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import schemas_tipo
from app.domain.estados import RegraViolada
from app.models import Bairro, Cidade, Orgao, TipoEquipamento
from app.services import ia

router = APIRouter(tags=["ia"])
DB = Annotated[Session, Depends(get_db)]

TIPOS_IMAGEM = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGEM = 5 * 1024 * 1024


def _tipos(db: Session) -> list[dict]:
    return [
        {"id": t.id, "nome": t.nome, "mobilidade": t.mobilidade.value, "schema_atributos": t.schema_atributos}
        for t in db.scalars(select(TipoEquipamento).order_by(TipoEquipamento.id))
    ]


def _bairros(db: Session) -> dict[str, Bairro]:
    cidade = db.scalar(select(Cidade).where(Cidade.tem_lista_bairros.is_(True)).order_by(Cidade.id))
    if not cidade:
        return {}
    return {b.nome: b for b in db.scalars(select(Bairro).where(Bairro.cidade_id == cidade.id))}


def _json_obj(s: str) -> dict:
    try:
        v = json.loads(s or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


@router.post("/ia/extrair-cadastro")
async def extrair_cadastro(db: DB, texto: Annotated[str | None, Form()] = None, foto: UploadFile | None = File(None)):
    """Sugere o cadastro a partir de foto da etiqueta e/ou texto livre. Nada é salvo."""
    imagem = media = None
    if foto is not None:
        media = foto.content_type
        if media not in TIPOS_IMAGEM:
            raise RegraViolada("imagem_invalida", "Envie a foto em JPG, PNG, WEBP ou GIF.")
        imagem = await foto.read()
        if len(imagem) > MAX_IMAGEM:
            raise RegraViolada("imagem_grande", "Foto maior que 5 MB. Tire uma foto mais leve.")
    if not imagem and not (texto and texto.strip()):
        raise RegraViolada("entrada_vazia", "Envie uma foto ou uma descrição.")

    tipos = _tipos(db)
    bairros = _bairros(db)
    bruto = ia.extrair_cadastro(texto, imagem, media, tipos, list(bairros))
    obs: list[str] = list(bruto.get("observacoes") or [])[:3]

    # Tudo o que a IA devolve é conferido contra os dados reais antes de ir para a tela.
    tipo = next((t for t in tipos if t["id"] == bruto.get("tipo_id")), None)
    atributos: dict = {}
    if tipo:
        props = tipo["schema_atributos"].get("properties", {})
        candidatos = {k: v for k, v in _json_obj(bruto.get("atributos_json")).items() if k in props}
        for k, v in candidatos.items():
            parcial = {"type": "object", "properties": {k: props[k]}}
            if schemas_tipo.validar_atributos(parcial, {k: v}):
                obs.append(f"Valor sugerido para \"{props[k].get('title', k)}\" não é válido e foi descartado.")
            else:
                atributos[k] = v

    bairro = ia.casar_nome(bruto.get("bairro"), bairros)
    lon = lat = None
    if bairro is not None and bairro.geom is not None:
        p = to_shape(db.scalar(select(func.ST_PointOnSurface(Bairro.geom)).where(Bairro.id == bairro.id)))
        lon, lat = round(p.x, 6), round(p.y, 6)
        obs.append(f"Ponto aproximado no bairro {bairro.nome}: arraste o marcador para o local exato.")

    cep = re.sub(r"\D", "", bruto.get("cep") or "")
    return {
        "tipo_id": tipo["id"] if tipo else None,
        "marca": bruto.get("marca"),
        "modelo": bruto.get("modelo"),
        "numero_serie": bruto.get("numero_serie"),
        "dispositivo_iot_id": bruto.get("dispositivo_iot_id"),
        "atributos": atributos,
        "localizacao": {
            "rua": bruto.get("rua"), "referencia": bruto.get("referencia"),
            "cep": f"{cep[:5]}-{cep[5:]}" if len(cep) == 8 else None,
            "bairro_id": bairro.id if bairro else None, "lon": lon, "lat": lat,
        },
        "observacoes": obs,
    }


class BuscaIn(BaseModel):
    texto: str = Field(min_length=3, max_length=500)


@router.post("/busca")
def busca(body: BuscaIn, db: DB):
    """Pergunta em linguagem natural vira os mesmos filtros da listagem (parâmetros de URL)."""
    tipos = _tipos(db)
    orgaos = {o.sigla: o.id for o in db.scalars(select(Orgao))}
    bairros = _bairros(db)
    r = ia.interpretar_busca(body.texto, tipos, list(orgaos), list(bairros))

    ids_tipo = {t["id"] for t in tipos}
    props_validas = {k for t in tipos for k in t["schema_atributos"].get("properties", {})}
    params: dict[str, list[str] | str] = {}

    def lista(chave: str, valores: list):
        valores = [str(v) for v in valores if v is not None]
        if valores:
            params[chave] = valores

    lista("tipo_id", [t for t in r.get("tipo_ids", []) if t in ids_tipo])
    lista("situacao", [s for s in r.get("situacoes", []) if s in ia.SITUACOES])
    lista("orgao_id", [orgaos.get(s.upper()) for s in r.get("orgaos", [])])
    lista("regiao", [x for x in r.get("regioes", []) if x in ia.REGIOES])
    lista("bairro_id", [getattr(ia.casar_nome(b, bairros), "id", None) for b in r.get("bairros", [])])
    lista("status_manutencao", [m for m in r.get("status_manutencao", []) if m in ia.MANUTENCAO])
    if r.get("sem_sinal"):
        params["sem_sinal"] = "1"
    if isinstance(r.get("score_max"), int):
        params["score_max"] = str(max(0, min(100, r["score_max"])))
    attrs = {k: v for k, v in _json_obj(r.get("atributos_json")).items() if k in props_validas and isinstance(v, (str, int, float, bool))}
    if attrs:
        params["atributos"] = json.dumps(attrs, ensure_ascii=False)
    if r.get("texto"):
        params["q"] = r["texto"]
    return {"params": params, "interpretacao": r.get("interpretacao", [])}
