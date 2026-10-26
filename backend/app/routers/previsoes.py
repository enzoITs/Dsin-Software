"""API da Parte 3: previsões no formato do contrato (Cartão de Previsão), tela "Amanhã",
ranking de equipamentos em risco e decisões sobre as recomendações."""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.models import Equipamento, Previsao, Recomendacao
from app.models.enums import EstadoRecomendacao
from app.preditivo import calendario, cartoes, clima, decisoes, planejamento, preventivos
from app.preditivo.p3 import NOME_PERIODO

router = APIRouter(tags=["preditivo: previsões"])
DB = Annotated[Session, Depends(get_db)]
FUSO = clima.FUSO


class DecisaoIn(BaseModel):
    acao: Literal["aceitar", "ajustar", "rejeitar"]
    motivo: str | None = Field(None, max_length=500)
    parametros: dict | None = None


class LoteOrdensIn(BaseModel):
    previsao_ids: list[int] = Field(min_length=1, max_length=500)


def _nao_achou(o_que: str = "Previsão"):
    raise HTTPException(404, {"codigo": "nao_encontrado", "mensagem": f"{o_que} não encontrada."})


def _sem_previsoes():
    raise HTTPException(409, {"codigo": "sem_previsao",
                              "mensagem": "Ainda não há previsões. Rode o treino: python -m app.preditivo.treinar --todos"})


def _ultima_p1(db: Session) -> datetime | None:
    return db.scalar(select(func.max(Previsao.horizonte_inicio)).where(Previsao.modulo == "P1"))


# ---------------------------------------------------------------- previsões

@router.get("/previsoes")
def listar(db: DB, modulo: str | None = None, alvo_tipo: str | None = None, alvo_id: int | None = None,
           regiao_id: int | None = None, desde: datetime | None = None, ate: datetime | None = None,
           atuais: bool = True, limite: Annotated[int, Query(ge=1, le=500)] = 100):
    """Previsões no formato do contrato. `atuais`: só as do último lote de cada módulo."""
    q = select(Previsao)
    if modulo:
        q = q.where(Previsao.modulo == modulo)
    if alvo_tipo:
        q = q.where(Previsao.alvo_tipo == alvo_tipo)
    if alvo_id is not None:
        q = q.where(Previsao.alvo_id == alvo_id)
    if regiao_id is not None:
        q = q.where(Previsao.regiao_id == regiao_id)
    if desde:
        q = q.where(Previsao.horizonte_fim > desde)
    if ate:
        q = q.where(Previsao.horizonte_inicio < ate)
    if atuais:
        origem = planejamento.ultima_origem(db)
        ult_p1 = _ultima_p1(db)
        q = q.where((Previsao.modulo != "P1") | (Previsao.horizonte_inicio == ult_p1))
        if origem:
            q = q.where((Previsao.modulo == "P1") | (Previsao.detalhe["origem"].astext == origem))
    cache: dict = {}
    return [cartoes.cartao(p, db, cache) for p in db.scalars(q.order_by(Previsao.horizonte_inicio, Previsao.id).limit(limite))]


@router.get("/previsoes/{previsao_id}")
def ver(previsao_id: int, db: DB):
    p = db.get(Previsao, previsao_id)
    if p is None:
        _nao_achou()
    return cartoes.cartao(p, db)


@router.post("/previsoes/{previsao_id}/decisao")
def decidir_previsao(previsao_id: int, body: DecisaoIn, db: DB, ctx: Ctx):
    """Aceitar, ajustar ou rejeitar a ação recomendada no cartão. Aceitar executa a ação."""
    p = db.get(Previsao, previsao_id)
    if p is None:
        _nao_achou()
    if ctx.perfil == "prometheus":
        raise HTTPException(403, {"codigo": "sem_permissao", "mensagem": "Só pessoas decidem sobre recomendações."})
    rec = decisoes.recomendacao_da_previsao(db, p)
    decisoes.decidir(db, rec, body.acao, ctx.usuario, body.motivo, body.parametros)
    db.commit()
    preventivos.verificar(db)  # OS aberta ou reforço aceito: o alerta preventivo se resolve na hora
    return cartoes.cartao(p, db)


# ---------------------------------------------------------------- recomendações

def _rec_json(r: Recomendacao) -> dict:
    return {"id": r.id, "previsao_id": r.previsao_id, "tipo": r.tipo, "texto": r.texto, "parametros": r.parametros,
            "impacto_estimado": r.impacto_estimado, "estado": r.estado.value, "decidido_por": r.decidido_por,
            "decidido_em": r.decidido_em, "motivo": r.motivo, "resultado": r.resultado, "criado_em": r.criado_em}


@router.get("/recomendacoes")
def recomendacoes(db: DB, estado: EstadoRecomendacao | None = None, tipo: str | None = None,
                  limite: Annotated[int, Query(ge=1, le=500)] = 100):
    q = select(Recomendacao)
    if estado:
        q = q.where(Recomendacao.estado == estado)
    if tipo:
        q = q.where(Recomendacao.tipo == tipo)
    return [_rec_json(r) for r in db.scalars(q.order_by(Recomendacao.id.desc()).limit(limite))]


@router.patch("/recomendacoes/{rec_id}")
def decidir_recomendacao(rec_id: int, body: DecisaoIn, db: DB, ctx: Ctx):
    r = db.get(Recomendacao, rec_id)
    if r is None:
        _nao_achou("Recomendação")
    if ctx.perfil == "prometheus":
        raise HTTPException(403, {"codigo": "sem_permissao", "mensagem": "Só pessoas decidem sobre recomendações."})
    decisoes.decidir(db, r, body.acao, ctx.usuario, body.motivo, body.parametros)
    db.commit()
    preventivos.verificar(db)
    return _rec_json(r)


# ---------------------------------------------------------------- equipamentos em risco

@router.get("/equipamentos/risco")
def ranking(db: DB, janela: Annotated[int, Query(description="7 ou 30 dias")] = 7, nivel: list[str] = Query(default=[]), tipo: str | None = None,
            regiao: str | None = None, busca: str | None = None, limite: Annotated[int, Query(ge=1, le=1000)] = 200):
    """Ranking de P1: equipamentos em operação ordenados pela probabilidade de falhar."""
    if janela not in (7, 30):
        raise HTTPException(422, {"codigo": "janela_invalida", "mensagem": "A janela é de 7 ou 30 dias."})
    inicio = _ultima_p1(db)
    if inicio is None:
        _sem_previsoes()
    filtros = ["p.modulo = 'P1'", "p.horizonte_inicio = :ini", "p.horizonte_fim = :fim"]
    par: dict = {"ini": inicio, "fim": inicio + timedelta(days=janela), "lim": limite}
    if nivel:
        filtros.append("p.nivel = ANY(:niv)")
        par["niv"] = nivel
    if tipo:
        filtros.append("p.detalhe->'alvo'->>'tipo_equipamento' = :tipo")
        par["tipo"] = tipo
    if regiao:
        filtros.append("p.detalhe->'alvo'->>'regiao' = :reg")
        par["reg"] = regiao
    if busca:
        filtros.append("p.detalhe->'alvo'->>'nome' ILIKE :b")
        par["b"] = f"%{busca.strip()}%"
    onde = " AND ".join(filtros)
    linhas = db.execute(text(f"""
        SELECT p.id, p.alvo_id, p.valor, p.faixa_inferior, p.faixa_superior, p.nivel, p.fatores, p.detalhe,
               e.marca, e.modelo, e.situacao::text situacao,
               (SELECT r.estado::text FROM recomendacao r WHERE r.previsao_id = p.id ORDER BY r.id DESC LIMIT 1) decisao,
               EXISTS (SELECT 1 FROM ordem_servico o WHERE o.equipamento_id = p.alvo_id AND o.status = 'aberta') os_aberta
        FROM previsao p JOIN equipamento e ON e.id = p.alvo_id WHERE {onde} ORDER BY p.valor DESC LIMIT :lim"""), par).mappings().all()
    totais = dict(db.execute(text("""SELECT nivel, count(*) FROM previsao p
                                     WHERE p.modulo = 'P1' AND p.horizonte_inicio = :ini AND p.horizonte_fim = :fim
                                     GROUP BY nivel"""), {"ini": inicio, "fim": inicio + timedelta(days=janela)}).all())
    mv_id = db.scalar(text("SELECT id FROM modelo_versao WHERE nome = :n AND ativo"), {"n": f"falha_equipamento_{janela}d"})
    from app.models import ModeloVersao

    return {
        "gerado_para": inicio, "janela_dias": janela, "totais_por_nivel": totais,
        "selo": cartoes.selo(db.get(ModeloVersao, mv_id) if mv_id else None, "P1"),
        "itens": [{
            "previsao_id": r["id"], "equipamento_id": r["alvo_id"], "codigo": r["detalhe"]["alvo"]["nome"],
            "tipo": r["detalhe"]["alvo"].get("tipo_equipamento"), "regiao": r["detalhe"]["alvo"].get("regiao"),
            "marca": r["marca"].strip(), "modelo": r["modelo"], "situacao": r["situacao"],
            "probabilidade": r["valor"], "faixa": [r["faixa_inferior"], r["faixa_superior"]], "nivel": r["nivel"],
            "fatores": r["fatores"][:3], "acao": r["detalhe"].get("acao_recomendada"), "decisao": r["decisao"],
            "os_aberta": r["os_aberta"],
        } for r in linhas],
    }


@router.post("/equipamentos/risco/ordens")
def abrir_ordens(body: LoteOrdensIn, db: DB, ctx: Ctx):
    """Ação em lote: aceita a recomendação de OS preventiva de várias previsões de P1."""
    if ctx.perfil == "prometheus":
        raise HTTPException(403, {"codigo": "sem_permissao", "mensagem": "Só pessoas decidem sobre recomendações."})
    feitas, puladas = [], []
    for pid in body.previsao_ids:
        p = db.get(Previsao, pid)
        if p is None or p.modulo != "P1":
            puladas.append({"previsao_id": pid, "motivo": "não é uma previsão de falha"})
            continue
        rec = decisoes.recomendacao_da_previsao(db, p)
        if rec.estado != EstadoRecomendacao.pendente:
            puladas.append({"previsao_id": pid, "motivo": f"já {rec.estado.value}"})
            continue
        if rec.tipo not in ("ABRIR_ORDEM_SERVICO", "INCLUIR_ROTA_MANUTENCAO"):
            rec.tipo = "ABRIR_ORDEM_SERVICO"
            rec.texto = f"Abrir ordem de serviço preventiva para {(p.detalhe or {}).get('alvo', {}).get('nome', p.alvo_id)}"
            rec.parametros = {"equipamento_id": p.alvo_id, "prioridade": "media"}
        decisoes.decidir(db, rec, "aceitar", ctx.usuario)
        feitas.append({"previsao_id": pid, **(rec.resultado or {}).get("execucao", {})})
    db.commit()
    preventivos.verificar(db)
    return {"abertas": feitas, "puladas": puladas}


@router.get("/equipamentos/{equipamento_id}/risco")
def risco_equipamento(equipamento_id: int, db: DB):
    if db.get(Equipamento, equipamento_id) is None:
        _nao_achou("Equipamento")
    inicio = _ultima_p1(db)
    cache: dict = {}
    ps = db.scalars(select(Previsao).where(Previsao.modulo == "P1", Previsao.alvo_id == equipamento_id,
                                           Previsao.horizonte_inicio == inicio).order_by(Previsao.horizonte_fim)).all()
    return {"equipamento_id": equipamento_id, "cartoes": [cartoes.cartao(p, db, cache) for p in ps],
            "mensagem": None if ps else "Sem previsão para este equipamento (só equipamentos em operação recebem previsão)."}


# ---------------------------------------------------------------- tela "Amanhã"

def _contexto(db: Session, ini: datetime, fim: datetime) -> dict:
    d0, d1 = ini.astimezone(FUSO).date(), fim.astimezone(FUSO).date()
    cal = [c for c in calendario.periodo(db, d0, d1) if c.feriado or c.vespera_feriado]
    eventos = db.execute(text("""SELECT id, nome, tipo::text tipo, local_nome, inicio_em, fim_em, publico_estimado, simulado
                                 FROM evento_cidade WHERE fim_em > :a AND inicio_em < :b ORDER BY inicio_em"""),
                         {"a": ini, "b": fim}).mappings().all()
    clima_h = db.execute(text("""SELECT em, temperatura_c, chuva_mm, alerta_tempestade, editado_por FROM clima_hora
                                 WHERE em >= :a AND em < :b ORDER BY em"""), {"a": ini, "b": fim}).mappings().all()
    dias: dict[date, dict] = {}
    for c in clima_h:
        d = c["em"].astimezone(FUSO).date()
        x = dias.setdefault(d, {"dia": d, "chuva_mm": 0.0, "temp_max": -99.0, "temp_min": 99.0, "tempestade": False,
                                "editado": False, "horas_chuva": []})
        x["chuva_mm"] += c["chuva_mm"]
        x["temp_max"] = max(x["temp_max"], c["temperatura_c"])
        x["temp_min"] = min(x["temp_min"], c["temperatura_c"])
        x["tempestade"] |= c["alerta_tempestade"]
        x["editado"] |= c["editado_por"] is not None
        if c["chuva_mm"] >= 0.5:
            x["horas_chuva"].append(c["em"].astimezone(FUSO).hour)
    return {
        "feriados": [{"data": c.data, "nome": c.feriado_nome, "vespera": c.vespera_feriado} for c in cal],
        "eventos": [dict(e) for e in eventos],
        "clima": [{**x, "chuva_mm": round(x["chuva_mm"], 1), "temp_max": round(x["temp_max"], 1),
                   "temp_min": round(x["temp_min"], 1)} for x in dias.values()],
    }


@router.get("/amanha")
def amanha(db: DB):
    """Índice de risco (P3) por região, hora a hora e por período, nas próximas 72 h, com o contexto."""
    origem = planejamento.ultima_origem(db)
    if not origem:
        _sem_previsoes()
    p3 = pd.DataFrame(db.execute(text("""
        SELECT p.id, p.regiao_id, p.detalhe->'alvo'->>'nome' regiao, p.horizonte_inicio ini, p.horizonte_fim fim, p.valor, p.nivel,
               p.detalhe->>'motivo_principal' motivo, p.detalhe->>'granularidade' gran, p.detalhe->>'periodo' periodo
        FROM previsao p WHERE p.modulo = 'P3' AND p.detalhe->>'origem' = :o ORDER BY ini, regiao"""), {"o": origem}).mappings().all())
    p2 = dict(((r, t), (v, i)) for r, t, v, i in db.execute(text("""
        SELECT regiao_id, horizonte_inicio, valor, id FROM previsao WHERE modulo = 'P2' AND detalhe->>'origem' = :o"""),
        {"o": origem}).all())
    horas = []
    for t, x in p3[p3.gran == "hora"].groupby("ini"):
        local = t.tz_convert(FUSO)
        horas.append({"em": t, "local": local.isoformat(), "rotulo": f"{local:%d/%m} {local.hour} h",
                      "regioes": [{"regiao_id": int(r.regiao_id), "regiao": r.regiao, "indice": r.valor, "nivel": r.nivel,
                                   "motivo": r.motivo, "previsao_id": int(r.id),
                                   "ocorrencias": round(p2.get((int(r.regiao_id), t), (0, None))[0], 2),
                                   "previsao_p2_id": p2.get((int(r.regiao_id), t), (0, None))[1]}
                                  for r in x.sort_values("valor", ascending=False).itertuples()]})
    periodos = []
    for (a, b), x in p3[p3.gran == "periodo"].groupby(["ini", "fim"]):
        periodos.append({"inicio": a, "fim": b, "periodo": x.periodo.iloc[0],
                         "rotulo": planejamento._rotulo(a, b), "nome": NOME_PERIODO.get(x.periodo.iloc[0]),
                         "regioes": [{"regiao_id": int(r.regiao_id), "regiao": r.regiao, "indice": r.valor, "nivel": r.nivel,
                                      "motivo": r.motivo, "previsao_id": int(r.id)}
                                     for r in x.sort_values("valor", ascending=False).itertuples()]})
    ini = p3.ini.min().to_pydatetime()
    fim = p3.fim.max().to_pydatetime()
    mv_id = db.scalar(text("SELECT id FROM modelo_versao WHERE nome = 'ocorrencias_regiao_hora' AND ativo"))
    from app.models import ModeloVersao

    pend = db.scalars(select(Recomendacao).where(Recomendacao.tipo == "REFORCAR_EQUIPES",
                                                 Recomendacao.estado == EstadoRecomendacao.pendente)
                      .order_by(Recomendacao.id)).all()
    return {"origem": origem, "inicio": ini, "fim": fim, "horas": horas, "periodos": periodos,
            "contexto": _contexto(db, ini, fim), "selo": cartoes.selo(db.get(ModeloVersao, mv_id) if mv_id else None, "P2"),
            "recomendacoes": [_rec_json(r) for r in pend], "dados_sinteticos": True}


@router.get("/amanha/regioes/{regiao_id}")
def amanha_regiao(regiao_id: int, db: DB):
    """Detalhe de uma região: ocorrências previstas por hora com a faixa, o real nas horas que já passaram,
    o índice com os componentes e os cartões dos períodos."""
    origem = planejamento.ultima_origem(db)
    if not origem:
        _sem_previsoes()
    o = datetime.fromisoformat(origem)
    ini, fim = o - timedelta(hours=24), o + timedelta(hours=72)
    prev = db.execute(text("""
        SELECT DISTINCT ON (p.horizonte_inicio) p.id, p.horizonte_inicio em, p.valor, p.faixa_inferior, p.faixa_superior,
               (p.detalhe->>'normal')::float normal
        FROM previsao p WHERE p.modulo = 'P2' AND p.regiao_id = :r AND p.horizonte_inicio >= :a AND p.horizonte_inicio < :b
          AND (p.detalhe->>'origem')::timestamptz <= p.horizonte_inicio
        ORDER BY p.horizonte_inicio, (p.detalhe->>'origem')::timestamptz DESC"""), {"r": regiao_id, "a": ini, "b": fim}).mappings().all()
    if not prev:
        _nao_achou("Região com previsão")
    reais = dict(db.execute(text("""SELECT date_trunc('hour', inicio_em), count(*) FROM ocorrencia
                                    WHERE regiao_id = :r AND inicio_em >= :a AND inicio_em < :b GROUP BY 1"""),
                            {"r": regiao_id, "a": ini, "b": datetime.now(timezone.utc)}).all())
    agora = datetime.now(timezone.utc)
    indices = dict(db.execute(text("""SELECT horizonte_inicio, valor FROM previsao WHERE modulo = 'P3' AND regiao_id = :r
                                      AND detalhe->>'origem' = :o AND detalhe->>'granularidade' = 'hora'"""),
                              {"r": regiao_id, "o": origem}).all())
    serie = [{"em": p["em"], "local": p["em"].astimezone(FUSO).isoformat(), "previsto": round(p["valor"], 2),
              "inferior": round(p["faixa_inferior"], 2), "superior": round(p["faixa_superior"], 2),
              "normal": round(p["normal"] or 0, 2), "indice": indices.get(p["em"]), "previsao_id": p["id"],
              "real": reais.get(p["em"], 0) if p["em"] + timedelta(hours=1) <= agora else None} for p in prev]
    cache: dict = {}
    periodos = db.scalars(select(Previsao).where(Previsao.modulo.in_(["P3", "P4"]), Previsao.regiao_id == regiao_id,
                                                 Previsao.detalhe["origem"].astext == origem,
                                                 (Previsao.modulo == "P4") | (Previsao.detalhe["granularidade"].astext == "periodo"))
                          .order_by(Previsao.horizonte_inicio, Previsao.modulo)).all()
    nome = db.scalar(text("SELECT nome FROM regiao WHERE id = :r"), {"r": regiao_id})
    return {"regiao_id": regiao_id, "regiao": nome, "origem": origem, "serie": serie,
            "cartoes": [cartoes.cartao(p, db, cache) for p in periodos]}


@router.post("/previsoes/recalcular")
def recalcular(db: DB, ctx: Ctx):
    """Refaz agora P2, P3 e P4 (por exemplo, depois de editar o clima ou cadastrar um evento). Só o gestor."""
    ctx.exigir_gestor()
    from app.preditivo import prever

    res = prever.prever_p2_p3(db)
    if not res.get("p2"):
        _sem_previsoes()
    p4 = planejamento.prever_p4(db)
    return {"p2": res["p2"], "p3": res["p3"], "p4": p4["previsoes"], "recomendacoes": p4["recomendacoes"]}
