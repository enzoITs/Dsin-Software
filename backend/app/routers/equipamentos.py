import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import Ctx
from app.domain import derivados, estados, schemas_tipo
from app.domain.estados import RegraViolada
from app.models import (
    Anexo,
    Cidade,
    Equipamento,
    HistoricoSituacao,
    Localizacao,
    OrdemServico,
    Orgao,
    PlanoManutencao,
    RegistroManutencao,
    TipoEquipamento,
)
from app.models.enums import Situacao, StatusManutencao, TipoPlano
from app.schemas.api import (
    EquipamentoIn,
    EquipamentoOut,
    EquipamentoPatch,
    EquipamentoResumo,
    HistoricoOut,
    LocalizacaoIn,
    MudancaSituacaoIn,
    MudancaSituacaoOut,
    OrdemOut,
    Pagina,
    PlanoIn,
    PlanoOut,
    RegistroCriadoOut,
    RegistroIn,
    RegistroOut,
    ScoreOut,
)
from app.services import eventos
from app.services import equipamentos as svc

router = APIRouter(prefix="/equipamentos", tags=["equipamentos"])
DB = Annotated[Session, Depends(get_db)]


def filtros_da_query(
    q: str | None = None,
    tipo_id: Annotated[list[int], Query()] = [],
    situacao: Annotated[list[Situacao], Query()] = [],
    orgao_id: Annotated[list[int], Query()] = [],
    cidade_id: int | None = None,
    bairro_id: Annotated[list[int], Query()] = [],
    regiao: Annotated[list[str], Query()] = [],
    status_manutencao: Annotated[list[StatusManutencao], Query()] = [],
    score_min: int | None = None,
    score_max: int | None = None,
    sem_sinal: bool | None = None,
    atributos: Annotated[str | None, Query(description='JSON, ex.: {"visao_noturna": false}')] = None,
    ordenar: str = "codigo",
    nivel: Annotated[list[str], Query(description="critica, alta, media, baixa")] = [],
    manutencao: Annotated[list[str], Query(description="imediata, vencida, proxima")] = [],
    area: Annotated[str | None, Query(description='Polígono "lon lat,lon lat,..."')] = None,
) -> svc.Filtros:
    attrs = {}
    if atributos:
        try:
            attrs = json.loads(atributos)
            assert isinstance(attrs, dict)
        except (ValueError, AssertionError):
            raise HTTPException(400, {"codigo": "atributos_invalidos", "mensagem": "atributos deve ser um objeto JSON"})
    return svc.Filtros(
        q=q, tipo_id=tipo_id, situacao=situacao, orgao_id=orgao_id, cidade_id=cidade_id,
        bairro_id=bairro_id, regiao=regiao, status_manutencao=status_manutencao,
        score_min=score_min, score_max=score_max, sem_sinal=sem_sinal, atributos=attrs, ordenar=ordenar,
        nivel=[n for n in nivel if n in ("critica", "alta", "media", "baixa")],
        manutencao=[m for m in manutencao if m in ("imediata", "vencida", "proxima")],
        area=svc.ler_area(area),
    )


def obter(db: Session, equipamento_id: int, ctx) -> Equipamento:
    e = db.get(Equipamento, equipamento_id)
    if e is None or (ctx.restrito and e.orgao_id != ctx.orgao_id):
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": "Equipamento não encontrado."})
    return e


@router.get("", response_model=Pagina[EquipamentoResumo])
def listar(
    db: DB,
    ctx: Ctx,
    f: Annotated[svc.Filtros, Depends(filtros_da_query)],
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(25, ge=1, le=200),
):
    itens, total = svc.listar(db, f, pagina, por_pagina, ctx.orgao_id if ctx.restrito else None)
    return Pagina(itens=itens, total=total, pagina=pagina, por_pagina=por_pagina)


@router.get("/codigo/{codigo}", response_model=EquipamentoOut)
def por_codigo(codigo: str, db: DB, ctx: Ctx):
    """Usado pela leitura do QR Code no modo campo."""
    e = db.scalar(select(Equipamento).where(Equipamento.codigo_interno == codigo.upper()))
    if e is None:
        raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": f"Nenhum equipamento com código {codigo}."})
    return svc.detalhe(obter(db, e.id, ctx))


def _validar_atributos(tipo: TipoEquipamento, atributos: dict) -> None:
    erros = schemas_tipo.validar_atributos(tipo.schema_atributos, atributos)
    if erros:
        raise RegraViolada("atributos_invalidos", f"Atributos não conferem com o tipo {tipo.nome}.", erros)


def _avisos_duplicidade(db: Session, marca: str, numero_serie: str, ignorar_id: int | None = None) -> list[dict]:
    normal = svc.normalizar_serie(numero_serie)
    stmt = select(Equipamento.codigo_interno).where(
        func.regexp_replace(func.upper(Equipamento.numero_serie), "[^A-Z0-9]", "", "g") == normal
    )
    if ignorar_id:
        stmt = stmt.where(Equipamento.id != ignorar_id)
    parecidos = db.scalars(stmt.limit(3)).all()
    if parecidos:
        return [{"codigo": "possivel_duplicidade", "mensagem": f"Mesmo número de série já usado em {', '.join(parecidos)}."}]
    return []


def _checar_unicidade(db: Session, marca: str, numero_serie: str, dispositivo: str | None, ignorar_id: int | None = None):
    q = select(Equipamento.codigo_interno).where(
        Equipamento.marca == marca.strip(), Equipamento.numero_serie == numero_serie.strip()
    )
    if ignorar_id:
        q = q.where(Equipamento.id != ignorar_id)
    if (cod := db.scalar(q)):
        raise RegraViolada("serie_duplicada", f"{cod} já usa este número de série nesta marca.", status=409)
    if dispositivo:
        q = select(Equipamento.codigo_interno).where(Equipamento.dispositivo_iot_id == dispositivo.strip())
        if ignorar_id:
            q = q.where(Equipamento.id != ignorar_id)
        if (cod := db.scalar(q)):
            raise RegraViolada("iot_duplicado", f"Este módulo IoT já está vinculado a {cod}.", status=409)


def _aplicar_localizacao(db: Session, e: Equipamento, loc: LocalizacaoIn) -> list[dict]:
    cidade = db.get(Cidade, loc.cidade_id)
    if cidade is None:
        raise RegraViolada("cidade_invalida", "Cidade não encontrada.")
    bairro_id, regiao, avisos = svc.avaliar_localizacao(db, cidade, loc.bairro_id, loc.lon, loc.lat)
    cep = loc.cep
    if cep and "-" not in cep:
        cep = f"{cep[:5]}-{cep[5:]}"
    dados = dict(
        cidade_id=cidade.id, rua=loc.rua.strip(), cep=cep, bairro_id=bairro_id,
        referencia=(loc.referencia or "").strip() or None, regiao=regiao,
        geom=f"SRID=4326;POINT({loc.lon} {loc.lat})" if loc.lon is not None and loc.lat is not None else None,
    )
    if e.localizacao is None:
        e.localizacao = Localizacao(**dados)
    else:
        for k, v in dados.items():
            setattr(e.localizacao, k, v)
    return avisos


def _salvar(db: Session):
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        msg = str(exc.orig)
        if "uq_equipamento_marca_serie" in msg:
            raise RegraViolada("serie_duplicada", "Já existe equipamento desta marca com este número de série.", status=409)
        if "dispositivo_iot_id" in msg:
            raise RegraViolada("iot_duplicado", "Este módulo IoT já está vinculado a outro equipamento.", status=409)
        raise


@router.post("", response_model=EquipamentoOut, status_code=status.HTTP_201_CREATED)
def criar(body: EquipamentoIn, db: DB, ctx: Ctx):
    ctx.exigir_alterar(body.orgao_id)
    tipo = db.get(TipoEquipamento, body.tipo_id)
    if tipo is None:
        raise RegraViolada("tipo_invalido", "Tipo de equipamento não encontrado.")
    if db.get(Orgao, body.orgao_id) is None:
        raise RegraViolada("orgao_invalido", "Órgão não encontrado.")
    _validar_atributos(tipo, body.atributos)
    _checar_unicidade(db, body.marca, body.numero_serie, body.dispositivo_iot_id)
    avisos = _avisos_duplicidade(db, body.marca, body.numero_serie)

    e = Equipamento(
        codigo_interno=svc.proximo_codigo(db, tipo),
        tipo_id=tipo.id,
        numero_serie=body.numero_serie.strip(),
        marca=body.marca.strip(),
        modelo=body.modelo.strip(),
        orgao_id=body.orgao_id,
        dispositivo_iot_id=body.dispositivo_iot_id,
        situacao=Situacao.nao_instalado,
        data_instalacao=body.data_instalacao,
        atributos=body.atributos,
        score_saude=100,
        score_motivos=[],
    )
    db.add(e)
    avisos += _aplicar_localizacao(db, e, body.localizacao)
    _salvar(db)

    evts = []
    if body.situacao_inicial == Situacao.operacional:
        evts = estados.mudar_situacao(db, e, Situacao.operacional, "Cadastrado já instalado", ctx.usuario, recalcular=False)
    derivados.recalcular(db, [e.id])
    db.commit()
    eventos.publicar(evts)
    db.refresh(e)
    return svc.detalhe(e, avisos)


@router.get("/{equipamento_id}", response_model=EquipamentoOut)
def ver(equipamento_id: int, db: DB, ctx: Ctx):
    return svc.detalhe(obter(db, equipamento_id, ctx))


@router.patch("/{equipamento_id}", response_model=EquipamentoOut)
@router.put("/{equipamento_id}", response_model=EquipamentoOut)
def editar(equipamento_id: int, body: EquipamentoPatch, db: DB, ctx: Ctx):
    e = obter(db, equipamento_id, ctx)
    ctx.exigir_alterar(e.orgao_id)
    dados = body.model_dump(exclude_unset=True)
    avisos: list[dict] = []
    if "orgao_id" in dados:
        ctx.exigir_alterar(dados["orgao_id"])
    if "atributos" in dados and dados["atributos"] is not None:
        _validar_atributos(e.tipo, dados["atributos"])
    _checar_unicidade(
        db, dados.get("marca") or e.marca, dados.get("numero_serie") or e.numero_serie,
        dados.get("dispositivo_iot_id") if "dispositivo_iot_id" in dados else None, e.id,
    )
    if "numero_serie" in dados or "marca" in dados:
        avisos += _avisos_duplicidade(db, dados.get("marca", e.marca), dados.get("numero_serie", e.numero_serie), e.id)
    for campo in ("numero_serie", "marca", "modelo", "orgao_id", "data_instalacao", "atributos"):
        if campo in dados and dados[campo] is not None:
            setattr(e, campo, dados[campo].strip() if isinstance(dados[campo], str) else dados[campo])
    if "dispositivo_iot_id" in dados:
        e.dispositivo_iot_id = (dados["dispositivo_iot_id"] or "").strip() or None
    if body.localizacao is not None:
        avisos += _aplicar_localizacao(db, e, body.localizacao)
    _salvar(db)
    derivados.recalcular(db, [e.id])
    db.commit()
    db.refresh(e)
    return svc.detalhe(e, avisos)


@router.patch("/{equipamento_id}/situacao", response_model=MudancaSituacaoOut)
def mudar_situacao(equipamento_id: int, body: MudancaSituacaoIn, db: DB, ctx: Ctx):
    e = obter(db, equipamento_id, ctx)
    ctx.exigir_alterar(e.orgao_id)
    evts = estados.mudar_situacao(db, e, body.situacao, body.motivo, body.usuario or ctx.usuario)
    db.commit()
    eventos.publicar(evts)
    db.refresh(e)
    return MudancaSituacaoOut(equipamento=svc.detalhe(e), acoes=evts[0]["acoes"])


@router.get("/{equipamento_id}/historico", response_model=list[HistoricoOut])
def historico(equipamento_id: int, db: DB, ctx: Ctx):
    obter(db, equipamento_id, ctx)
    return db.scalars(
        select(HistoricoSituacao)
        .where(HistoricoSituacao.equipamento_id == equipamento_id)
        .order_by(HistoricoSituacao.em.desc(), HistoricoSituacao.id.desc())
    ).all()


@router.get("/{equipamento_id}/score", response_model=ScoreOut)
def score(equipamento_id: int, db: DB, ctx: Ctx):
    e = obter(db, equipamento_id, ctx)
    motivos = e.score_motivos or []
    if motivos:
        partes = ", ".join(f"{m['texto']} ({m['pontos']})" for m in motivos)
        explicacao = f"{e.score_saude} porque: {partes}"
    else:
        explicacao = f"{e.score_saude}: nenhum problema encontrado"
    return ScoreOut(equipamento_id=e.id, codigo_interno=e.codigo_interno, score=e.score_saude, motivos=motivos, explicacao=explicacao)


@router.get("/{equipamento_id}/planos-manutencao", response_model=list[PlanoOut])
def listar_planos(equipamento_id: int, db: DB, ctx: Ctx):
    obter(db, equipamento_id, ctx)
    return db.scalars(
        select(PlanoManutencao)
        .where(PlanoManutencao.equipamento_id == equipamento_id)
        .order_by(PlanoManutencao.ativo.desc(), PlanoManutencao.proxima_data)
    ).all()


@router.post("/{equipamento_id}/planos-manutencao", response_model=PlanoOut, status_code=201)
def criar_plano(equipamento_id: int, body: PlanoIn, db: DB, ctx: Ctx):
    e = obter(db, equipamento_id, ctx)
    ctx.exigir_alterar(e.orgao_id)
    if e.situacao == Situacao.desativado:
        raise RegraViolada("equipamento_desativado", "Equipamento desativado não recebe plano de manutenção.")
    if body.tipo == TipoPlano.periodica and not body.periodicidade_dias:
        raise RegraViolada("periodicidade_obrigatoria", "Plano periódico precisa da periodicidade em dias.")
    if body.tipo != TipoPlano.imediata and body.proxima_data is None:
        raise RegraViolada("data_obrigatoria", "Informe a data da próxima manutenção.")
    plano = PlanoManutencao(
        equipamento_id=e.id, tipo=body.tipo,
        proxima_data=body.proxima_data or derivados.dia_local(datetime.now(timezone.utc)),
        periodicidade_dias=body.periodicidade_dias if body.tipo == TipoPlano.periodica else None,
        descricao=body.descricao, ativo=True,
    )
    db.add(plano)
    db.flush()
    derivados.recalcular(db, [e.id])
    db.commit()
    return plano


@router.get("/{equipamento_id}/registros-manutencao", response_model=list[RegistroOut])
def listar_registros(equipamento_id: int, db: DB, ctx: Ctx):
    obter(db, equipamento_id, ctx)
    return db.scalars(
        select(RegistroManutencao)
        .where(RegistroManutencao.equipamento_id == equipamento_id)
        .order_by(RegistroManutencao.executada_em.desc())
    ).all()


@router.post("/{equipamento_id}/registros-manutencao", response_model=RegistroCriadoOut, status_code=201)
def registrar(equipamento_id: int, body: RegistroIn, db: DB, ctx: Ctx):
    e = obter(db, equipamento_id, ctx)
    ctx.exigir_alterar(e.orgao_id)
    registro, evts = estados.registrar_manutencao(
        db, e, tecnico=body.tecnico, executada_em=body.executada_em, plano_id=body.plano_id,
        descricao=body.descricao, resultado=body.resultado, lon=body.lon, lat=body.lat,
    )
    db.commit()
    eventos.publicar(evts)
    db.refresh(e)
    acoes = ["manutencao_registrada"] + [f"situacao:{ev['situacao_nova']}" for ev in evts]
    return RegistroCriadoOut(registro=RegistroOut.model_validate(registro), equipamento=svc.detalhe(e), acoes=acoes)


@router.get("/{equipamento_id}/ordens-servico", response_model=list[OrdemOut])
def ordens(equipamento_id: int, db: DB, ctx: Ctx):
    obter(db, equipamento_id, ctx)
    return db.scalars(
        select(OrdemServico)
        .where(OrdemServico.equipamento_id == equipamento_id)
        .order_by(OrdemServico.aberta_em.desc())
    ).all()


# ---------- Anexos (fotos de campo e de etiqueta) ----------

TIPOS_FOTO = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@router.post("/{equipamento_id}/anexos", status_code=201)
async def anexar(
    equipamento_id: int, db: DB, ctx: Ctx,
    foto: UploadFile = File(...), tipo: Annotated[str, Form()] = "campo",
    registro_id: Annotated[int | None, Form()] = None,
):
    e = obter(db, equipamento_id, ctx)
    ctx.exigir_alterar(e.orgao_id)
    ext = TIPOS_FOTO.get(foto.content_type or "")
    if not ext:
        raise RegraViolada("imagem_invalida", "Envie a foto em JPG, PNG ou WEBP.")
    dados = await foto.read()
    if len(dados) > 8 * 1024 * 1024:
        raise RegraViolada("imagem_grande", "Foto maior que 8 MB.")
    pasta = Path(settings.uploads_dir) / str(e.id)
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"{uuid.uuid4().hex}{ext}"
    (pasta / nome).write_bytes(dados)
    a = Anexo(equipamento_id=e.id, registro_id=registro_id, tipo=tipo[:30], url=f"/uploads/{e.id}/{nome}")
    db.add(a)
    db.commit()
    return {"id": a.id, "url": a.url, "tipo": a.tipo, "em": a.em}


@router.get("/{equipamento_id}/anexos")
def listar_anexos(equipamento_id: int, db: DB, ctx: Ctx):
    obter(db, equipamento_id, ctx)
    return [
        {"id": a.id, "url": a.url, "tipo": a.tipo, "registro_id": a.registro_id, "em": a.em}
        for a in db.scalars(select(Anexo).where(Anexo.equipamento_id == equipamento_id).order_by(Anexo.em.desc()))
    ]
