"""Ocorrências da cidade (Parte 3): o que acontece nas ruas, não só nos equipamentos.

Chegam por três caminhos: o operador registra na central, o motor deriva de alertas de furto
e de incidente correlacionado, e o gerador de histórico cria as simuladas. Sempre gravam
quantos agentes estavam ativos na região, para corrigir o viés de patrulhamento nos modelos.
"""

from datetime import datetime, timezone

from geoalchemy2 import WKTElement
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Agente, Alerta, Bairro, CategoriaOcorrencia, Ocorrencia, Regiao
from app.models.enums import OrigemOcorrencia, SituacaoAgente, TipoAlerta
from app.services.barramento import emitir

# Alertas que viram ocorrência sozinhos: regra -> (categoria, gravidade)
DE_ALERTA = {
    TipoAlerta.furto: ("FURTO_EQUIPAMENTO", 4),
    TipoAlerta.incidente_correlacionado: ("OUTROS", 3),
}


class CategoriaInvalida(ValueError):
    pass


def localizar(db: Session, lon: float, lat: float) -> tuple[int | None, int | None, str | None, str | None]:
    """(bairro_id, regiao_id, nome do bairro, nome da região) do ponto."""
    p = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    b = db.execute(select(Bairro.id, Bairro.nome).where(func.ST_Contains(Bairro.geom, p)).limit(1)).first()
    r = db.execute(select(Regiao.id, Regiao.nome).where(func.ST_Contains(Regiao.geom, p)).limit(1)).first()
    return (b.id if b else None, r.id if r else None, b.nome if b else None, r.nome if r else None)


def agentes_ativos(db: Session, regiao: str | None) -> int | None:
    if not regiao:
        return None
    return db.scalar(select(func.count()).select_from(Agente).where(
        Agente.regiao == regiao, Agente.situacao == SituacaoAgente.em_atividade))


def para_json(o: Ocorrencia, regiao: str | None = None, bairro: str | None = None, lon=None, lat=None) -> dict:
    return {
        "id": o.id, "categoria": o.categoria, "categoria_nome": o.categoria_ref.nome if o.categoria_ref else o.categoria,
        "gravidade": o.gravidade, "inicio_em": o.inicio_em, "fim_em": o.fim_em, "lon": lon, "lat": lat,
        "regiao_id": o.regiao_id, "regiao": regiao, "bairro_id": o.bairro_id, "bairro": bairro,
        "origem": o.origem.value, "equipamento_id": o.equipamento_id, "alerta_id": o.alerta_id,
        "agentes_presentes_regiao": o.agentes_presentes_regiao, "descricao": o.descricao, "registrado_por": o.registrado_por,
    }


def registrar(db: Session, *, categoria: str, lon: float, lat: float, origem: OrigemOcorrencia,
              gravidade: int | None = None, inicio_em: datetime | None = None, fim_em: datetime | None = None,
              descricao: str | None = None, registrado_por: str | None = None,
              equipamento_id: int | None = None, alerta_id: int | None = None) -> dict:
    cat = db.get(CategoriaOcorrencia, categoria)
    if cat is None or not cat.ativa:
        raise CategoriaInvalida(categoria)
    bairro_id, regiao_id, bairro, regiao = localizar(db, lon, lat)
    o = Ocorrencia(
        categoria=categoria, gravidade=gravidade or cat.gravidade_padrao,
        inicio_em=inicio_em or datetime.now(timezone.utc), fim_em=fim_em,
        geom=WKTElement(f"POINT({lon} {lat})", srid=4326), regiao_id=regiao_id, bairro_id=bairro_id,
        origem=origem, equipamento_id=equipamento_id, alerta_id=alerta_id,
        agentes_presentes_regiao=agentes_ativos(db, regiao), descricao=descricao, registrado_por=registrado_por,
    )
    db.add(o)
    db.flush()
    db.refresh(o, ["categoria_ref"])
    js = para_json(o, regiao, bairro, lon, lat)
    emitir(db, {"tipo": "ocorrencia", "acao": "nova", "ocorrencia": js})
    return js


def de_alerta(db: Session, a: Alerta, lon: float | None, lat: float | None) -> dict | None:
    """Furto e incidente correlacionado geram ocorrência na hora. Uma por alerta."""
    regra = DE_ALERTA.get(a.tipo)
    if regra is None or lon is None or lat is None:
        return None
    if db.scalar(select(Ocorrencia.id).where(Ocorrencia.alerta_id == a.id)) is not None:
        return None
    categoria, gravidade = regra
    return registrar(db, categoria=categoria, gravidade=gravidade, lon=lon, lat=lat,
                     origem=OrigemOcorrencia.equipamento, inicio_em=a.criado_em, descricao=a.mensagem,
                     registrado_por="motor", equipamento_id=a.equipamento_id, alerta_id=a.id)


def listar(db: Session, *, desde: datetime | None = None, ate: datetime | None = None, regiao: str | None = None,
           categorias: list[str] | None = None, origem: OrigemOcorrencia | None = None, limite: int = 500) -> dict:
    stmt = (
        select(Ocorrencia, Regiao.nome, Bairro.nome, func.ST_X(Ocorrencia.geom), func.ST_Y(Ocorrencia.geom))
        .outerjoin(Regiao, Regiao.id == Ocorrencia.regiao_id)
        .outerjoin(Bairro, Bairro.id == Ocorrencia.bairro_id)
    )
    if desde:
        stmt = stmt.where(Ocorrencia.inicio_em >= desde)
    if ate:
        stmt = stmt.where(Ocorrencia.inicio_em < ate)
    if regiao:
        stmt = stmt.where(Regiao.nome == regiao)
    if categorias:
        stmt = stmt.where(Ocorrencia.categoria.in_(categorias))
    if origem:
        stmt = stmt.where(Ocorrencia.origem == origem)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    linhas = db.execute(stmt.order_by(Ocorrencia.inicio_em.desc()).limit(limite)).all()
    return {"itens": [para_json(o, r, b, x, y) for o, r, b, x, y in linhas], "total": total}
