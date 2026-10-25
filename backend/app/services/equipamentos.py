"""Consultas e montagem de respostas de equipamento, compartilhadas por listagem, busca e ficha."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import Integer, Select, and_, cast, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.domain import limites, silencio
from app.domain.estados import TRANSICOES
from app.models import Bairro, Cidade, Equipamento, Localizacao, TipoEquipamento
from app.models.enums import Situacao, StatusManutencao
from app.schemas.api import EquipamentoOut, EquipamentoResumo, LocalizacaoOut, TipoResumo

# Brasil continental com folga (lon_min, lat_min, lon_max, lat_max).
BBOX_BRASIL = (-74.0, -34.0, -28.8, 5.3)
DISTANCIA_MAX_CIDADE_KM = 60


@dataclass
class Filtros:
    q: str | None = None
    tipo_id: list[int] = field(default_factory=list)
    situacao: list[Situacao] = field(default_factory=list)
    orgao_id: list[int] = field(default_factory=list)
    cidade_id: int | None = None
    bairro_id: list[int] = field(default_factory=list)
    regiao: list[str] = field(default_factory=list)
    status_manutencao: list[StatusManutencao] = field(default_factory=list)
    score_min: int | None = None
    score_max: int | None = None
    sem_sinal: bool | None = None
    atributos: dict[str, Any] = field(default_factory=dict)
    ordenar: str = "codigo"
    # Parte 2 (central)
    nivel: list[str] = field(default_factory=list)          # com alerta aberto destes níveis
    manutencao: list[str] = field(default_factory=list)     # imediata, vencida, proxima
    area: list[tuple[float, float]] = field(default_factory=list)  # polígono desenhado (lon, lat)

    @property
    def por_equipamento(self) -> bool:
        """Há filtro que só faz sentido para equipamento (e não para alertas de região ou de agente)."""
        return bool(self.q or self.tipo_id or self.situacao or self.status_manutencao or self.score_min is not None
                    or self.score_max is not None or self.sem_sinal or self.atributos or self.nivel or self.manutencao
                    or self.bairro_id)

    def como_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v not in (None, [], {}, "codigo") and k != "area"}
        if self.area:
            d["area"] = len(self.area)
        return {k: ([x.value if hasattr(x, "value") else x for x in v] if isinstance(v, list) else v) for k, v in d.items()}


TEXTO_BUSCA = (
    Equipamento.codigo_interno
    + literal_column("' '")
    + Equipamento.numero_serie
    + literal_column("' '")
    + Equipamento.marca
    + literal_column("' '")
    + Equipamento.modelo
)


def condicao_sem_sinal(fator: float | None = None):
    """Falha silenciosa em SQL: operacional, com IoT e sem sinal há mais de fator x o intervalo do tipo."""
    fator = fator if fator is not None else limites.carregar()["silencio_fator"]
    limite = func.now() - func.make_interval(0, 0, 0, 0, 0, TipoEquipamento.intervalo_sinal_esperado_min * fator)
    return and_(
        Equipamento.situacao == Situacao.operacional,
        Equipamento.dispositivo_iot_id.is_not(None),
        # Sem nenhum sinal ainda: conta a partir do cadastro (recém-instalado não é silêncio).
        func.coalesce(Equipamento.ultimo_sinal_em, Equipamento.criado_em) < limite,
    )


def aplicar_filtros(stmt: Select, f: Filtros, orgao_restrito: int | None) -> Select:
    stmt = stmt.select_from(Equipamento).join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id).outerjoin(
        Localizacao, Localizacao.equipamento_id == Equipamento.id
    )
    if orgao_restrito is not None:
        stmt = stmt.where(Equipamento.orgao_id == orgao_restrito)
    if f.q:
        termo = f.q.strip()
        stmt = stmt.where(
            or_(TEXTO_BUSCA.ilike(f"%{termo}%"), Equipamento.dispositivo_iot_id == termo)
        )
    if f.tipo_id:
        stmt = stmt.where(Equipamento.tipo_id.in_(f.tipo_id))
    if f.situacao:
        stmt = stmt.where(Equipamento.situacao.in_(f.situacao))
    if f.orgao_id:
        stmt = stmt.where(Equipamento.orgao_id.in_(f.orgao_id))
    if f.cidade_id:
        stmt = stmt.where(Localizacao.cidade_id == f.cidade_id)
    if f.bairro_id:
        stmt = stmt.where(Localizacao.bairro_id.in_(f.bairro_id))
    if f.regiao:
        stmt = stmt.where(Localizacao.regiao.in_(f.regiao))
    if f.status_manutencao:
        stmt = stmt.where(Equipamento.status_manutencao.in_(f.status_manutencao))
    if f.score_min is not None:
        stmt = stmt.where(Equipamento.score_saude >= f.score_min)
    if f.score_max is not None:
        stmt = stmt.where(Equipamento.score_saude <= f.score_max)
    if f.sem_sinal is True:
        stmt = stmt.where(condicao_sem_sinal())
    if f.atributos:
        stmt = stmt.where(Equipamento.atributos.contains(f.atributos))
    if f.nivel:
        from app.models import Alerta

        stmt = stmt.where(Equipamento.id.in_(
            select(Alerta.equipamento_id).where(Alerta.resolvido_em.is_(None), Alerta.nivel.in_(f.nivel))
        ))
    if f.manutencao:
        from app.models import PlanoManutencao
        from app.models.enums import TipoPlano

        conds = []
        if "imediata" in f.manutencao:
            conds.append(Equipamento.id.in_(select(PlanoManutencao.equipamento_id).where(
                PlanoManutencao.ativo.is_(True), PlanoManutencao.tipo == TipoPlano.imediata)))
        st = [StatusManutencao(m) for m in f.manutencao if m in ("vencida", "proxima")]
        if st:
            conds.append(Equipamento.status_manutencao.in_(st))
        if conds:
            stmt = stmt.where(or_(*conds))
    if f.area:
        stmt = stmt.where(func.ST_Within(posicao_atual(), area_wkt(f.area)))
    return stmt


def posicao_atual():
    """Onde o equipamento está agora: posição da telemetria (móveis) ou ponto de instalação."""
    return func.coalesce(Equipamento.posicao, Localizacao.geom)


def area_wkt(pontos: list[tuple[float, float]]):
    anel = list(pontos) + ([pontos[0]] if pontos[0] != pontos[-1] else [])
    return func.ST_GeomFromText("POLYGON((" + ",".join(f"{x} {y}" for x, y in anel) + "))", 4326)


def ler_area(texto: str | None) -> list[tuple[float, float]]:
    """"lon lat,lon lat,..." (mínimo 3 pontos)."""
    if not texto:
        return []
    try:
        pts = [tuple(float(v) for v in par.split()) for par in texto.split(",") if par.strip()]
        assert len(pts) >= 3 and all(len(p) == 2 and -180 <= p[0] <= 180 and -90 <= p[1] <= 90 for p in pts)
        return pts  # type: ignore[return-value]
    except (ValueError, AssertionError):
        return []


ORDENACOES = {
    "codigo": [Equipamento.tipo_id, Equipamento.codigo_interno],
    "score": [Equipamento.score_saude.asc(), Equipamento.id],
    "-score": [Equipamento.score_saude.desc(), Equipamento.id],
    "atualizado": [Equipamento.atualizado_em.desc(), Equipamento.id],
    "sinal": [Equipamento.ultimo_sinal_em.asc().nulls_first(), Equipamento.id],
}


def listar(db: Session, f: Filtros, pagina: int, por_pagina: int, orgao_restrito: int | None):
    base = aplicar_filtros(select(Equipamento.id), f, orgao_restrito)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    ids = db.scalars(
        base.order_by(*ORDENACOES.get(f.ordenar, ORDENACOES["codigo"]))
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
    ).all()
    itens = carregar(db, list(ids))
    return [resumo(e) for e in itens], total


def carregar(db: Session, ids: list[int]) -> list[Equipamento]:
    if not ids:
        return []
    por_id = {e.id: e for e in db.scalars(select(Equipamento).where(Equipamento.id.in_(ids))).unique()}
    return [por_id[i] for i in ids if i in por_id]


def _xy(geom) -> tuple[float | None, float | None]:
    if geom is None:
        return None, None
    p = to_shape(geom)
    return round(p.x, 6), round(p.y, 6)


def esta_sem_sinal(e: Equipamento, agora: datetime | None = None) -> bool:
    return silencio.esta_silencioso(
        e.situacao,
        bool(e.dispositivo_iot_id),
        e.ultimo_sinal_em or e.criado_em,
        e.tipo.intervalo_sinal_esperado_min,
        agora or datetime.now(timezone.utc),
        limites.carregar()["silencio_fator"],
    )


def resumo(e: Equipamento) -> EquipamentoResumo:
    loc = e.localizacao
    lon, lat = _xy(loc.geom) if loc else (None, None)
    return EquipamentoResumo(
        id=e.id,
        codigo_interno=e.codigo_interno,
        tipo=TipoResumo.model_validate(e.tipo),
        marca=e.marca,
        modelo=e.modelo,
        numero_serie=e.numero_serie,
        orgao=e.orgao.sigla,
        situacao=e.situacao,
        score_saude=e.score_saude,
        status_manutencao=e.status_manutencao,
        bairro=loc.bairro.nome if loc and loc.bairro else None,
        regiao=loc.regiao if loc else None,
        cidade=loc.cidade.nome if loc else None,
        ultimo_sinal_em=e.ultimo_sinal_em,
        sem_sinal=esta_sem_sinal(e),
        lon=lon,
        lat=lat,
    )


def detalhe(e: Equipamento, avisos: list[dict] | None = None) -> EquipamentoOut:
    r = resumo(e)
    loc = e.localizacao
    loc_out = None
    if loc:
        loc_out = LocalizacaoOut(
            cidade_id=loc.cidade_id,
            cidade=loc.cidade.nome,
            uf=loc.cidade.uf,
            rua=loc.rua,
            cep=loc.cep,
            bairro_id=loc.bairro_id,
            bairro=loc.bairro.nome if loc.bairro else None,
            referencia=loc.referencia,
            regiao=loc.regiao,
            lon=r.lon,
            lat=r.lat,
        )
    return EquipamentoOut(
        **r.model_dump(),
        orgao_id=e.orgao_id,
        dispositivo_iot_id=e.dispositivo_iot_id,
        data_instalacao=e.data_instalacao,
        atributos=e.atributos or {},
        score_motivos=e.score_motivos or [],
        localizacao=loc_out,
        transicoes_permitidas=sorted(TRANSICOES[e.situacao], key=lambda s: list(Situacao).index(s)),
        criado_em=e.criado_em,
        atualizado_em=e.atualizado_em,
        avisos=avisos or [],
    )


def proximo_codigo(db: Session, tipo: TipoEquipamento) -> str:
    ultimo = db.scalar(
        select(func.max(cast(func.split_part(Equipamento.codigo_interno, "-", 2), Integer)))
        .where(Equipamento.tipo_id == tipo.id)
    )
    return f"{tipo.prefixo}-{(ultimo or 0) + 1:04d}"


def normalizar_serie(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def avaliar_localizacao(db: Session, cidade: Cidade, bairro_id: int | None, lon: float | None, lat: float | None):
    """Sugere bairro e região pelo ponto e devolve avisos. Nunca bloqueia o cadastro."""
    avisos: list[dict] = []
    regiao = None
    bairro_final = bairro_id
    if bairro_id is not None:
        b = db.get(Bairro, bairro_id)
        if b is None or b.cidade_id != cidade.id:
            avisos.append({"codigo": "bairro_de_outra_cidade", "mensagem": "Bairro informado não pertence à cidade; foi ignorado."})
            bairro_final = None
        else:
            regiao = b.regiao

    if lon is None or lat is None:
        avisos.append({"codigo": "sem_coordenadas", "mensagem": "Sem coordenadas: o equipamento não aparecerá no mapa."})
        return bairro_final, regiao, avisos

    lon_min, lat_min, lon_max, lat_max = BBOX_BRASIL
    if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
        avisos.append({"codigo": "fora_do_brasil", "mensagem": "Coordenadas fora do Brasil. Confira o ponto no mapa."})
    elif cidade.centro is not None:
        dist_km = db.scalar(
            select(
                func.ST_DistanceSphere(cidade.centro, func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)) / 1000
            )
        )
        if dist_km and dist_km > DISTANCIA_MAX_CIDADE_KM:
            avisos.append({
                "codigo": "longe_da_cidade",
                "mensagem": f"O ponto está a {dist_km:.0f} km do centro de {cidade.nome}. Confira a cidade ou o ponto.",
            })

    if cidade.tem_lista_bairros:
        sugerido = db.execute(
            select(Bairro.id, Bairro.nome, Bairro.regiao).where(
                Bairro.cidade_id == cidade.id,
                func.ST_Contains(Bairro.geom, func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)),
            )
        ).first()
        if sugerido:
            if bairro_final is None:
                bairro_final, regiao = sugerido.id, sugerido.regiao
                avisos.append({"codigo": "bairro_sugerido", "mensagem": f"Bairro definido pelo ponto no mapa: {sugerido.nome}.", "bairro_id": sugerido.id})
            elif bairro_final != sugerido.id:
                avisos.append({
                    "codigo": "bairro_divergente",
                    "mensagem": f"O ponto no mapa fica em {sugerido.nome}, mas o bairro informado é outro.",
                    "bairro_id": sugerido.id,
                })
        else:
            avisos.append({"codigo": "fora_dos_bairros", "mensagem": "O ponto não está dentro de nenhum bairro oficial da cidade."})
    return bairro_final, regiao, avisos
