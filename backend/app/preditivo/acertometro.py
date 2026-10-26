"""Acertômetro (Q1): toda previsão guardada é comparada com o que aconteceu.

- `conferir` grava `valor_real` nas previsões cujo período já terminou:
  P2 = ocorrências registradas na região e hora; P1 = 1 se o equipamento entrou em mau funcionamento
  na janela, senão 0. P3 e P4 não são conferidas uma a uma (o índice e as equipes não têm um "valor
  real" único); a qualidade deles vem de P2, que os alimenta.
- `resumo` junta o que já foi conferido: erro do modelo contra o baseline guardado na própria previsão
  (para P2, a média da mesma hora e dia da semana nas 8 semanas anteriores), por dia e por antecedência,
  e a série previsto × real das últimas horas. Para P1, quantos dos apontados falharam de fato,
  inclusive no lote ainda em andamento.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.preditivo.variaveis import FUSO


def conferir(db: Session, agora: datetime | None = None) -> dict:
    agora = agora or datetime.now(timezone.utc)
    p2 = db.execute(text("""
        UPDATE previsao p SET valor_real = (
            SELECT count(*) FROM ocorrencia o
            WHERE o.regiao_id = p.regiao_id AND o.bairro_id IS NOT NULL
              AND o.inicio_em >= p.horizonte_inicio AND o.inicio_em < p.horizonte_fim),
            conferido_em = :agora
        WHERE p.modulo = 'P2' AND p.valor_real IS NULL AND p.horizonte_fim <= :agora"""), {"agora": agora}).rowcount
    p1 = db.execute(text("""
        UPDATE previsao p SET valor_real = CASE WHEN EXISTS (
            SELECT 1 FROM historico_situacao h
            WHERE h.equipamento_id = p.alvo_id AND h.situacao_nova = 'mau_funcionamento'
              AND h.em >= p.horizonte_inicio AND h.em < p.horizonte_fim) THEN 1 ELSE 0 END,
            conferido_em = :agora
        WHERE p.modulo = 'P1' AND p.valor_real IS NULL AND p.horizonte_fim <= :agora"""), {"agora": agora}).rowcount
    db.commit()
    return {"p2": p2, "p1": p1}


def _num(v) -> float | None:
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 3)


def resumo_p2(db: Session, agora: datetime, dias: int) -> dict:
    """Erro de P2 já conferido, contra o baseline sazonal guardado em cada previsão."""
    df = pd.DataFrame(db.execute(text("""
        SELECT p.regiao_id, r.nome regiao, p.horizonte_inicio em, (p.detalhe->>'origem')::timestamptz origem,
               p.valor previsto, p.faixa_inferior lo, p.faixa_superior hi, (p.detalhe->>'normal')::float baseline,
               p.valor_real real
        FROM previsao p JOIN regiao r ON r.id = p.regiao_id
        WHERE p.modulo = 'P2' AND p.valor_real IS NOT NULL AND p.horizonte_inicio >= :a"""),
        {"a": agora - timedelta(days=dias)}).mappings().all())
    if df.empty:
        return {"conferidas": 0}
    df["em"] = pd.to_datetime(df.em, utc=True)
    df["origem"] = pd.to_datetime(df.origem, utc=True)
    df["antecedencia_h"] = (df.em - df.origem).dt.total_seconds() / 3600
    df["erro"] = (df.previsto - df.real).abs()
    df["erro_base"] = (df.baseline - df.real).abs()
    df["dentro"] = (df.real >= np.floor(df.lo)) & (df.real <= np.ceil(df.hi))

    # Uma previsão por região e hora: a feita mais perto da hora (como a central usa)
    recente = df.sort_values("origem").groupby(["regiao_id", "em"]).tail(1)

    def metricas(x: pd.DataFrame) -> dict:
        mae, base = float(x.erro.mean()), float(x.erro_base.mean())
        return {"n": len(x), "mae": round(mae, 3), "mae_baseline": round(base, 3),
                "ganho_pct": round((base - mae) / base * 100, 1) if base > 0 else None,
                "cobertura_intervalo": round(float(x.dentro.mean()), 3), "real_medio": round(float(x.real.mean()), 2)}

    faixas = [(0, 24, "0-24 h"), (24, 48, "24-48 h"), (48, 72, "48-72 h")]
    por_antecedencia = [{"faixa": nome, **metricas(df[(df.antecedencia_h >= a) & (df.antecedencia_h < b)])}
                        for a, b, nome in faixas if ((df.antecedencia_h >= a) & (df.antecedencia_h < b)).any()]
    recente = recente.assign(dia=recente.em.dt.tz_convert(FUSO).dt.date)
    por_dia = [{"dia": d.isoformat(), **metricas(x)} for d, x in recente.groupby("dia")]
    por_regiao = [{"regiao": r, **metricas(x)} for r, x in recente.groupby("regiao")]
    ultimas = recente[recente.em >= agora - timedelta(hours=48)].groupby("em").agg(
        previsto=("previsto", "sum"), real=("real", "sum"), baseline=("baseline", "sum"))
    serie = [{"em": em.isoformat(), **{k: _num(v) for k, v in linha.items()}} for em, linha in ultimas.iterrows()]
    return {"conferidas": len(df), "geral": metricas(recente), "por_antecedencia": por_antecedencia, "por_dia": por_dia,
            "por_regiao": sorted(por_regiao, key=lambda r: r["regiao"]), "serie_48h": serie}


def resumo_p1(db: Session, agora: datetime, top: int = 50) -> dict:
    """P1: dos equipamentos apontados como mais arriscados, quantos falharam (conferido e em andamento)."""
    lotes = db.execute(text("""
        SELECT horizonte_inicio ini, horizonte_fim fim, count(*) n, count(valor_real) conferidas
        FROM previsao WHERE modulo = 'P1' AND horizonte_fim - horizonte_inicio = interval '7 days'
        GROUP BY 1, 2 ORDER BY 1 DESC LIMIT 8""")).mappings().all()
    saida = []
    for lote in lotes:
        x = pd.DataFrame(db.execute(text("""
            SELECT p.valor, coalesce(p.valor_real, CASE WHEN EXISTS (
                SELECT 1 FROM historico_situacao h WHERE h.equipamento_id = p.alvo_id AND h.situacao_nova = 'mau_funcionamento'
                  AND h.em >= p.horizonte_inicio AND h.em < least(p.horizonte_fim, :agora)) THEN 1 ELSE 0 END) falhou
            FROM previsao p WHERE p.modulo = 'P1' AND p.horizonte_inicio = :i AND p.horizonte_fim = :f"""),
            {"i": lote["ini"], "f": lote["fim"], "agora": agora}).mappings().all())
        if x.empty:
            continue
        x = x.sort_values("valor", ascending=False)
        apontados = x.head(top)
        decorrido = min(1.0, max(0.0, (agora - lote["ini"]).total_seconds() / (lote["fim"] - lote["ini"]).total_seconds()))
        saida.append({
            "inicio": lote["ini"].isoformat(), "fim": lote["fim"].isoformat(), "encerrado": lote["fim"] <= agora,
            "decorrido_pct": round(decorrido * 100), "equipamentos": len(x),
            "apontados": len(apontados), "falharam_apontados": int(apontados.falhou.sum()),
            "esperado_apontados": round(float(apontados.valor.sum()), 1),
            "taxa_apontados": round(float(apontados.falhou.mean()), 3), "taxa_geral": round(float(x.falhou.mean()), 3),
            "falharam_total": int(x.falhou.sum()),
        })
    return {"top": top, "lotes": saida}


def resumo(db: Session, dias: int = 7, agora: datetime | None = None) -> dict:
    agora = agora or datetime.now(timezone.utc)
    return {"gerado_em": agora.isoformat(), "dias": dias, "P2": resumo_p2(db, agora, dias), "P1": resumo_p1(db, agora),
            "dados_sinteticos": True}
