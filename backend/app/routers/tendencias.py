"""API da Parte 3, fase 12: tendência de disponibilidade (P6), carga de manutenção (P8), risco de furto (P7)
e expansão (C2). Todas as previsões saem no formato do contrato (Cartão de Previsão)."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import limites
from app.models import ModeloVersao, Previsao
from app.preditivo import cartoes, expansao

router = APIRouter(tags=["preditivo: tendências, furto e expansão"])
DB = Annotated[Session, Depends(get_db)]


def _ultima(db: Session, modulo: str) -> datetime | None:
    return db.scalar(select(func.max(Previsao.horizonte_inicio)).where(Previsao.modulo == modulo))


def _mv(db: Session, nome: str) -> ModeloVersao | None:
    return db.scalar(select(ModeloVersao).where(ModeloVersao.nome == nome, ModeloVersao.ativo).order_by(ModeloVersao.id.desc()))


def _sem(modulo: str):
    raise HTTPException(409, {"codigo": "sem_previsao",
                              "mensagem": f"Ainda não há previsões de {cartoes.NOME_MODULO[modulo].lower()}. "
                                          "Elas saem no lote diário (5 h) ou depois do treino."})


@router.get("/tendencias/disponibilidade")
def disponibilidade(db: DB, grupo: Literal["regiao", "tipo"] = "regiao"):
    """P6: disponibilidade prevista em 30 e 90 dias, com a série, a faixa e o cenário "seguindo P1"."""
    inicio = _ultima(db, "P6")
    if inicio is None:
        _sem("P6")
    tipos = ["regiao", "cidade"] if grupo == "regiao" else ["tipo"]
    ps = db.scalars(select(Previsao).where(Previsao.modulo == "P6", Previsao.horizonte_inicio == inicio,
                                           Previsao.alvo_tipo.in_(tipos)).order_by(Previsao.id)).all()
    cache: dict = {}
    por_alvo: dict[str, dict] = {}
    for p in ps:
        d = p.detalhe or {}
        nome = d["alvo"]["nome"]
        x = por_alvo.setdefault(nome, {"nome": nome, "alvo_tipo": p.alvo_tipo, "regiao_id": p.regiao_id, "atual": d.get("atual"),
                                       "meta": d.get("meta"), "em_servico": d.get("em_servico")})
        h = d.get("horizonte_dias")
        c = cartoes.cartao(p, db, cache)
        c["extra"] = {k: v for k, v in c["extra"].items() if k not in ("historico", "previsto")}  # já vão no item
        x[f"cartao_{h}"] = c
        x[f"previsto_{h}"] = p.valor
        x[f"seguindo_p1_{h}"] = d.get("seguindo_p1")
        x[f"nivel_{h}"] = p.nivel
        if h == 30:
            x.update(historico=d.get("historico"), previsto=d.get("previsto"), cruza_meta_em=d.get("cruza_meta_em"),
                     cruza_meta_seguindo_p1_em=d.get("cruza_meta_seguindo_p1_em"), falhas_evitaveis=d.get("falhas_evitaveis"),
                     dias_conserto=d.get("dias_conserto"))
    itens = sorted(por_alvo.values(), key=lambda x: (x["alvo_tipo"] == "cidade", x.get("previsto_30") or 1))
    cfg = limites.carregar(db)
    return {"gerado_para": inicio, "grupo": grupo, "meta": cfg["saude_meta_disponibilidade"] / 100,
            "eficacia_preventiva": cfg["prev_p6_eficacia_preventiva"],
            "selo": cartoes.selo(_mv(db, "disponibilidade_regiao"), "P6"), "itens": itens, "dados_sinteticos": True}


@router.get("/tendencias/manutencao")
def manutencao(db: DB, regiao: str | None = None):
    """P8: carga de manutenção por semana nas próximas 4 semanas, por região e na cidade."""
    origem = db.scalar(text("SELECT max(detalhe->>'origem') FROM previsao WHERE modulo = 'P8'"))
    if origem is None:
        _sem("P8")
    q = select(Previsao).where(Previsao.modulo == "P8", Previsao.detalhe["origem"].astext == origem)
    if regiao:
        q = q.where(Previsao.detalhe["alvo"]["nome"].astext == regiao)
    cache: dict = {}
    por_alvo: dict[str, dict] = {}
    for p in db.scalars(q.order_by(Previsao.horizonte_inicio, Previsao.id)):
        d = p.detalhe or {}
        nome = d["alvo"]["nome"]
        x = por_alvo.setdefault(nome, {"nome": nome, "alvo_tipo": p.alvo_tipo, "regiao_id": p.regiao_id, "semanas": []})
        x["semanas"].append({"semana": d.get("semana"), "inicio": p.horizonte_inicio, "fim": p.horizonte_fim, "rotulo": d.get("rotulo"),
                             "tecnicos_dia": p.valor, "faixa": [p.faixa_inferior, p.faixa_superior], "nivel": p.nivel,
                             "normal_tecnicos_dia": d.get("normal_tecnicos_dia"), "corretivas": d.get("corretivas"),
                             "pendentes": d.get("pendentes"), "preventivas": d.get("preventivas"),
                             "preventivas_atrasadas": d.get("preventivas_atrasadas"), "pecas": d.get("pecas"),
                             "por_tipo": d.get("por_tipo"), "cartao": cartoes.cartao(p, db, cache)})
    itens = sorted(por_alvo.values(), key=lambda x: (x["alvo_tipo"] == "cidade", -sum(s["tecnicos_dia"] for s in x["semanas"])))
    cfg = limites.carregar(db)
    return {"origem": origem, "jornada_h": cfg["prev_p8_horas_dia"], "horas_corretiva": cfg["prev_p8_horas_corretiva"],
            "horas_preventiva": cfg["prev_p8_horas_preventiva"], "selo": cartoes.selo(_mv(db, "carga_manutencao"), "P8"),
            "itens": itens, "dados_sinteticos": True}


@router.get("/furtos/risco")
def risco_furto(db: DB, nivel: list[str] = Query(default=[]), tipo: str | None = None, regiao: str | None = None,
                busca: str | None = None, limite: Annotated[int, Query(ge=1, le=1000)] = 200):
    """P7: ranking de equipamentos pela probabilidade de furto em 30 dias."""
    inicio = _ultima(db, "P7")
    if inicio is None:
        _sem("P7")
    filtros = ["p.modulo = 'P7'", "p.horizonte_inicio = :ini"]
    par: dict = {"ini": inicio, "lim": limite}
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
        filtros.append("(p.detalhe->'alvo'->>'nome' ILIKE :b OR p.detalhe->'alvo'->>'bairro' ILIKE :b)")
        par["b"] = f"%{busca.strip()}%"
    onde = " AND ".join(filtros)
    linhas = db.execute(text(f"""
        SELECT p.id, p.alvo_id, p.valor, p.nivel, p.fatores, p.detalhe, e.situacao::text situacao,
               ST_X(l.geom) lon, ST_Y(l.geom) lat,
               (SELECT r.estado::text FROM recomendacao r WHERE r.previsao_id = p.id ORDER BY r.id DESC LIMIT 1) decisao
        FROM previsao p JOIN equipamento e ON e.id = p.alvo_id LEFT JOIN localizacao l ON l.equipamento_id = e.id
        WHERE {onde} ORDER BY p.valor DESC LIMIT :lim"""), par).mappings().all()
    totais = dict(db.execute(text("SELECT nivel, count(*) FROM previsao WHERE modulo = 'P7' AND horizonte_inicio = :ini GROUP BY nivel"),
                             {"ini": inicio}).all())
    por_bairro = db.execute(text("""
        SELECT p.detalhe->'alvo'->>'bairro' bairro, p.detalhe->'alvo'->>'regiao' regiao, count(*) n, sum(p.valor) esperados,
               count(*) FILTER (WHERE p.nivel IN ('ALTO', 'MUITO_ALTO')) alto
        FROM previsao p WHERE p.modulo = 'P7' AND p.horizonte_inicio = :ini GROUP BY 1, 2 ORDER BY esperados DESC LIMIT 8"""),
        {"ini": inicio}).mappings().all()
    return {
        "gerado_para": inicio, "janela_dias": 30, "totais_por_nivel": totais,
        "furtos_esperados": float(db.scalar(text("SELECT sum(valor) FROM previsao WHERE modulo = 'P7' AND horizonte_inicio = :ini"),
                                            {"ini": inicio}) or 0),
        "por_bairro": [dict(b) for b in por_bairro], "selo": cartoes.selo(_mv(db, "furto_equipamento_30d"), "P7"),
        "itens": [{
            "previsao_id": r["id"], "equipamento_id": r["alvo_id"], "codigo": r["detalhe"]["alvo"]["nome"],
            "tipo": r["detalhe"]["alvo"].get("tipo_equipamento"), "regiao": r["detalhe"]["alvo"].get("regiao"),
            "bairro": r["detalhe"]["alvo"].get("bairro"), "situacao": r["situacao"], "probabilidade": r["valor"],
            "nivel": r["nivel"], "vezes_a_media": r["detalhe"].get("vezes_a_media"), "dist_camera_m": r["detalhe"].get("dist_camera_m"),
            "fatores": r["fatores"][:3], "acao": r["detalhe"].get("acao_recomendada"), "decisao": r["decisao"],
            "lon": r["lon"], "lat": r["lat"],
        } for r in linhas],
        "aviso": "Prevê lugares e equipamentos, nunca pessoas. Nenhum dado sobre pessoas entra no modelo.",
        "dados_sinteticos": True,
    }


@router.get("/expansao/sugestoes")
def sugestoes(db: DB, criterio: Literal["combinado", "ocorrencias", "furtos"] = "combinado",
              n: Annotated[int, Query(ge=1, le=30)] = 10):
    """C2: onde instalar as próximas câmeras, com o motivo de cada ponto."""
    return expansao.obter(db, n=n, criterio=criterio)
