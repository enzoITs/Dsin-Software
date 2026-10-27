"""Contrato de previsão (U1): toda previsão sai da API neste formato, que o Cartão de Previsão exibe.

Responde sempre às três perguntas do enunciado: o que estamos prevendo (`o_que_preve`, valor,
faixa, nível), com base em quê (`dados_considerados`, `fatores`) e como isso ajuda (`como_ajuda`,
`acao_recomendada`). Traz também a qualidade do modelo contra o baseline e um aviso honesto
quando a confiança é baixa.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModeloVersao, Previsao, Recomendacao
from app.preditivo import avaliacao

UNIDADE = {"P1": "probabilidade", "P2": "ocorrências", "P3": "índice", "P4": "equipes", "P6": "disponibilidade",
           "P7": "probabilidade", "P8": "técnicos-dia"}
NOME_MODULO = {"P1": "Risco de falha de equipamento", "P2": "Ocorrências por região e hora", "P3": "Índice de risco da região",
               "P4": "Reforço de equipes", "P6": "Tendência de disponibilidade", "P7": "Risco de furto de equipamento",
               "P8": "Carga de manutenção"}


def _fmt(v: float, casas: int = 2) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def selo(mv: ModeloVersao | None, modulo: str) -> dict:
    """Qualidade do modelo em relação ao baseline, em linguagem do gestor, e o nível de confiança."""
    if mv is None:
        return {"texto": "Modelo ainda sem avaliação", "confianca": "baixa", "ganho_pct": None}
    m, b = mv.metricas or {}, mv.metricas_baseline or {}
    if modulo == "P1":
        ganho = avaliacao.ganho(m.get("auc"), b.get("auc"), menor_melhor=False)
        p, pb = m.get("precisao_50"), b.get("precisao_50")
        quando = "na semana" if (mv.parametros or {}).get("janela_dias", 7) == 7 else "em 30 dias"
        texto = (f"De cada 50 equipamentos que o modelo aponta, {p * 50:.0f} falham {quando}; pela média histórica do tipo, "
                 f"{pb * 50:.0f}. Ordena {ganho:.0f}% melhor (AUC {_fmt(m['auc'])} × {_fmt(b['auc'])})"
                 if p is not None and pb is not None and ganho is not None else "Sem avaliação completa")
        detalhe = {"metrica": "AUC", "modelo": m.get("auc"), "baseline": b.get("auc"), "precisao_50": p, "precisao_50_baseline": pb}
    elif modulo == "P6":
        ganho = avaliacao.ganho(m.get("mae_pp"), b.get("mae_pp"), menor_melhor=True)
        g90 = avaliacao.ganho(m.get("mae_pp_90"), b.get("mae_pp_90"), menor_melhor=True)
        texto = (f"Erra {ganho:.0f}% menos que a média móvel de 30 dias: erro médio de {_fmt(m['mae_pp'])} ponto percentual "
                 f"em 30 dias, contra {_fmt(b['mae_pp'])}" + (f"; em 90 dias, {g90:.0f}% menos" if g90 is not None else "")
                 if ganho is not None else "Sem avaliação completa")
        detalhe = {"metrica": "erro médio em pontos percentuais (30 dias)", "modelo": m.get("mae_pp"), "baseline": b.get("mae_pp"),
                   "modelo_90": m.get("mae_pp_90"), "baseline_90": b.get("mae_pp_90")}
    elif modulo == "P7":
        ganho = avaliacao.ganho(m.get("auc"), b.get("auc"), menor_melhor=False)
        vezes = (m.get("precisao_50") or 0) / m["taxa_base"] if m.get("taxa_base") else None
        texto = (f"Ordena {ganho:.0f}% melhor que a taxa histórica de furto do tipo (AUC {_fmt(m['auc'])} × {_fmt(b['auc'])})"
                 + (f". Entre os 50 que o modelo aponta, furto é {vezes:.0f} vezes mais comum que na média" if vezes else "")
                 if ganho is not None else "Sem avaliação completa")
        detalhe = {"metrica": "AUC", "modelo": m.get("auc"), "baseline": b.get("auc"), "precisao_50": m.get("precisao_50"),
                   "precisao_50_baseline": b.get("precisao_50"), "taxa_base": m.get("taxa_base")}
    elif modulo == "P8":
        ganho = avaliacao.ganho(m.get("mae"), b.get("mae"), menor_melhor=True)
        texto = (f"Erra {ganho:.0f}% menos que a média histórica do tipo: erro médio de {_fmt(m['mae'])} falhas por tipo e "
                 f"região em 30 dias, contra {_fmt(b['mae'])}" if ganho is not None else "Sem avaliação completa")
        detalhe = {"metrica": "erro médio de falhas por tipo e região (30 dias)", "modelo": m.get("mae"), "baseline": b.get("mae")}
    else:
        ganho = avaliacao.ganho(m.get("mae"), b.get("mae"), menor_melhor=True)
        texto = (f"Erra {ganho:.0f}% menos que a média histórica: erro médio de {_fmt(m['mae'])} ocorrências por região e hora, "
                 f"contra {_fmt(b['mae'])}" if ganho is not None else "Sem avaliação completa")
        detalhe = {"metrica": "MAE por região e hora", "modelo": m.get("mae"), "baseline": b.get("mae"),
                   "cobertura_90": m.get("cobertura_90")}
    confianca = "baixa" if ganho is None or ganho < 5 else "moderada" if ganho < 25 else "alta"
    return {"texto": texto, "confianca": confianca, "ganho_pct": ganho, "avaliado_em": "backtest de 90 dias com origem móvel",
            "versao": mv.versao, **detalhe}


AVISO_CONFIANCA = {
    "baixa": "Confiança baixa: o modelo acerta pouco mais que a média histórica. Use como indicação, não como certeza.",
    "moderada": ("Confiança moderada: o modelo é melhor que a média histórica, mas parte do que acontece na cidade é acaso. "
                 "A faixa mostra a incerteza."),
    "alta": None,
}


def cartao(p: Previsao, db: Session, cache: dict | None = None) -> dict[str, Any]:
    cache = cache if cache is not None else {}
    d = p.detalhe or {}
    mv_id = p.modelo_versao_id
    if ("mv", mv_id) not in cache:
        cache[("mv", mv_id)] = db.get(ModeloVersao, mv_id) if mv_id else None
    mv = cache[("mv", mv_id)]
    s = selo(mv, p.modulo)
    if p.modulo == "P1" and p.valor < 0.05:
        s = {**s, "confianca": "moderada" if s["confianca"] == "alta" else s["confianca"]}
    rec = db.scalar(select(Recomendacao).where(Recomendacao.previsao_id == p.id).order_by(Recomendacao.id.desc()).limit(1))
    return {
        "id": f"prev_{p.id}", "previsao_id": p.id, "modulo": p.modulo, "modulo_nome": NOME_MODULO.get(p.modulo, p.modulo),
        "o_que_preve": d.get("o_que_preve"), "alvo": d.get("alvo"),
        "horizonte": {"inicio": p.horizonte_inicio, "fim": p.horizonte_fim},
        "valor": p.valor, "unidade": UNIDADE.get(p.modulo), "faixa": {"inferior": p.faixa_inferior, "superior": p.faixa_superior},
        "nivel": p.nivel, "dados_considerados": p.dados_considerados or [], "fatores": p.fatores or [],
        "como_ajuda": d.get("como_ajuda"), "acao_recomendada": d.get("acao_recomendada"),
        "qualidade_do_modelo": {**(d.get("qualidade_do_modelo") or {}), "selo": s},
        "confianca": {"nivel": s["confianca"], "aviso": AVISO_CONFIANCA[s["confianca"]]},
        "modelo": d.get("modelo"), "gerado_em": p.gerado_em, "valor_real": p.valor_real, "conferido_em": p.conferido_em,
        "dados_sinteticos": True,
        "extra": {k: v for k, v in d.items() if k not in {"o_que_preve", "alvo", "como_ajuda", "acao_recomendada",
                                                          "qualidade_do_modelo", "modelo"}},
        "recomendacao": None if rec is None else {
            "id": rec.id, "estado": rec.estado.value, "decidido_por": rec.decidido_por, "decidido_em": rec.decidido_em,
            "motivo": rec.motivo, "resultado": rec.resultado},
    }
