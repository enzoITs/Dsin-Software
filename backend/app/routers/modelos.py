"""Confiança dos modelos (Q1): versões ativas, backtest contra o baseline, acertômetro e treino.

Também a camada "Risco previsto (próximas 6 h)" da central.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx
from app.domain import limites
from app.models import BacktestResultado, ModeloVersao
from app.preditivo import acertometro, cartoes, servico

router = APIRouter(tags=["preditivo: confiança dos modelos"])
DB = Annotated[Session, Depends(get_db)]

NOMES_GRUPO = {
    "idade": "Idade do equipamento", "equipamento": "Tipo, marca e modelo", "manutencao": "Manutenção (atraso, última preventiva)",
    "falhas": "Falhas recentes", "chuva": "Chuva (passada e prevista)", "calor": "Calor (passado e previsto)",
    "furtos": "Furtos no bairro", "local": "Local (região, rodovia, móvel)",
    "calendario": "Hora, dia da semana e feriados", "padrao": "Padrão das últimas semanas", "agentes": "Agentes na escala",
    "evento": "Eventos programados", "clima": "Previsão do tempo", "recente": "Últimas horas",
    "horizonte": "Antecedência da previsão", "equipamentos": "Equipamentos fora de operação",
}

MODULOS = [
    {"modulo": "P1", "nome": "falha_equipamento_7d", "baseline": "baseline_falha_7d", "titulo": "Risco de falha em 7 dias",
     "o_que_preve": "Probabilidade de cada equipamento entrar em mau funcionamento nos próximos 7 dias",
     "metodo": "LightGBM com calibração isotônica; comparado com regressão logística e com a taxa histórica do tipo",
     "metrica": "auc", "menor_melhor": False},
    {"modulo": "P1", "nome": "falha_equipamento_30d", "baseline": "baseline_falha_30d", "titulo": "Risco de falha em 30 dias",
     "o_que_preve": "Probabilidade de cada equipamento entrar em mau funcionamento nos próximos 30 dias",
     "metodo": "LightGBM com calibração isotônica; comparado com regressão logística e com a taxa histórica do tipo",
     "metrica": "auc", "menor_melhor": False},
    {"modulo": "P2", "nome": "ocorrencias_regiao_hora", "baseline": "baseline_ocorrencias",
     "titulo": "Ocorrências por região e hora (72 h)",
     "o_que_preve": "Quantas ocorrências cada região terá em cada hora das próximas 72 horas, com faixa de 90%",
     "metodo": "LightGBM com perda de Poisson por bairro e hora; intervalo conformal; comparado com a média da mesma hora e dia da semana",
     "metrica": "mae", "menor_melhor": True},
]

DERIVADOS = [
    {"modulo": "P3", "titulo": "Índice de risco por região",
     "texto": "Combina as ocorrências previstas (P2), equipamentos em risco (P1) ou fora de operação, cobertura, escala de "
              "agentes e fatores externos, com pesos fixos e configuráveis. Não é um modelo treinado: a qualidade vem de P1 e P2."},
    {"modulo": "P4", "titulo": "Reforço de equipes",
     "texto": "Otimização (programação linear inteira) sobre a demanda prevista por P2 e o risco de P3. A recomendação "
              "só vale o que valem as previsões; o ganho é medido em risco não coberto antes e depois."},
    {"modulo": "P5", "titulo": "Anomalias",
     "texto": "Detectores estatísticos (decomposição sazonal robusta, Isolation Forest e o intervalo de P2), sem treino "
              "supervisionado. Validados nas anomalias plantadas: todas achadas, nenhum alarme falso nas séries normais."},
]


def _ativo(db: Session, nome: str) -> ModeloVersao | None:
    return db.scalar(select(ModeloVersao).where(ModeloVersao.nome == nome, ModeloVersao.ativo).order_by(ModeloVersao.id.desc()))


def _modelo_json(db: Session, m: dict) -> dict | None:
    mv = _ativo(db, m["nome"])
    if mv is None:
        return None
    met, base = mv.metricas or {}, mv.metricas_baseline or {}
    k = m["metrica"]
    cortes = db.execute(select(BacktestResultado.data_corte, BacktestResultado.metricas)
                        .where(BacktestResultado.modelo_versao_id == mv.id).order_by(BacktestResultado.data_corte)).all()
    backtest = [{"data_corte": d.isoformat(), "modelo": x.get(k), "baseline": x.get(f"{k}_baseline"),
                 **({"precisao_50": x.get("precisao_50"), "precisao_50_baseline": x.get("precisao_50_baseline")} if k == "auc" else
                    {"mae_pico": x.get("mae_pico"), "mae_pico_baseline": x.get("mae_pico_baseline"), "cobertura_90": x.get("cobertura_90")})}
                for d, x in cortes]
    imp = met.get("importancia") or {}
    total = sum(imp.values()) or 1
    resumo = {kk: met.get(kk) for kk in ("auc", "brier", "precisao_50", "taxa_base", "mae", "erro_pct", "mae_pico", "cobertura_90",
                                         "mae_por_horizonte", "por_regiao", "n") if met.get(kk) is not None}
    resumo_base = {kk: base.get(kk) for kk in ("auc", "brier", "precisao_50", "mae", "erro_pct", "mae_pico", "por_regiao")
                   if base.get(kk) is not None}
    return {
        **{kk: m[kk] for kk in ("modulo", "nome", "titulo", "o_que_preve", "metodo")},
        "versao": mv.versao, "treinado_em": mv.treinado_em, "treino_inicio": mv.treino_inicio, "treino_fim": mv.treino_fim,
        "selo": cartoes.selo(mv, m["modulo"]), "metricas": resumo, "baseline": resumo_base,
        "logistica": met.get("logistica") and {kk: met["logistica"].get(kk) for kk in ("auc", "brier", "precisao_50")},
        "calibracao": met.get("calibracao"), "calibracao_baseline": base.get("calibracao"),
        "importancia": sorted(({"grupo": g, "nome": NOMES_GRUPO.get(g, g), "peso": round(v / total, 3)} for g, v in imp.items()),
                              key=lambda x: -x["peso"]),
        "backtest": backtest,
    }


@router.get("/modelos")
def modelos(db: DB):
    """Modelos ativos com a avaliação no backtest de origem móvel, sempre contra o baseline."""
    cfg = limites.carregar(db)
    return {
        "modelos": [j for m in MODULOS if (j := _modelo_json(db, m)) is not None],
        "derivados": DERIVADOS,
        "avaliacao": (f"Backtest de origem móvel nos últimos {cfg['prev_backtest_dias']} dias: a cada "
                      f"{cfg['prev_backtest_passo_dias']} dias, o modelo é treinado só com o que existia até ali e "
                      "previsto para frente, como seria no uso real."),
        "treino": servico.estado_treino(db),
        "dados_sinteticos": True,
    }


@router.get("/modelos/acertometro")
def acertometro_(db: DB, dias: Annotated[int, Query(ge=1, le=60)] = 7):
    """Previsto × real do que já aconteceu (as previsões ficam guardadas e são conferidas de hora em hora)."""
    acertometro.conferir(db)
    return acertometro.resumo(db, dias)


@router.get("/modelos/padroes-descobertos")
def padroes_descobertos(db: DB, ctx: Ctx, refazer: bool = False):
    """O que os modelos aprenderam × os padrões plantados no gerador (Q2). Em cache até os modelos mudarem."""
    from app.preditivo import descoberta

    if refazer:
        ctx.exigir_gestor()
    return descoberta.obter(db, refazer=refazer)


@router.get("/modelos/treino")
def treino(db: DB):
    return servico.estado_treino(db)


@router.post("/modelos/treinar", status_code=202)
def treinar(db: DB, ctx: Ctx):
    """Retreina tudo em segundo plano (cerca de 3 minutos). Só o gestor."""
    ctx.exigir_gestor()
    if not servico.iniciar_treino():
        raise HTTPException(409, {"codigo": "treino_em_andamento", "mensagem": "Já há um treino em andamento."})
    return servico.estado_treino(db)


@router.get("/risco-previsto")
def risco_previsto(db: DB, horas: Annotated[int, Query(ge=1, le=72)] = 6):
    """Camada da central: maior índice de risco previsto (P3) de cada região nas próximas horas."""
    origem = db.scalar(text("SELECT max(detalhe->>'origem') FROM previsao WHERE modulo = 'P3'"))
    agora = datetime.now(timezone.utc)
    if not origem:
        return {"origem": None, "horas": horas, "regioes": []}
    linhas = db.execute(text("""
        SELECT DISTINCT ON (p.regiao_id) p.id previsao_id, p.regiao_id, r.nome regiao, p.valor indice, p.nivel,
               p.horizonte_inicio pico_em, p.detalhe->>'motivo_principal' motivo, p.detalhe->>'nivel_nome' nivel_nome,
               ST_AsGeoJSON(r.geom)::json geometria
        FROM previsao p JOIN regiao r ON r.id = p.regiao_id
        WHERE p.modulo = 'P3' AND p.detalhe->>'origem' = :o AND p.detalhe->>'granularidade' = 'hora'
          AND p.horizonte_fim > :a AND p.horizonte_inicio < :b
        ORDER BY p.regiao_id, p.valor DESC"""), {"o": origem, "a": agora, "b": agora + timedelta(hours=horas)}).mappings().all()
    return {"origem": origem, "horas": horas, "regioes": [dict(x) for x in linhas]}
