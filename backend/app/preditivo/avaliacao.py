"""Métricas de avaliação, sempre calculadas igual para o modelo e para o baseline."""

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score


def classificacao(y: np.ndarray, p: np.ndarray, grupos: np.ndarray | None = None, top: int = 50) -> dict:
    """P1: AUC, Brier, precisão nos `top` primeiros do ranking (média por corte) e curva de calibração.

    Empates no ranking são desfeitos com uma ordem fixa (semente 0), para o baseline não ganhar nem perder por sorte.
    """
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    desempate = np.random.default_rng(0).random(len(p))
    grupos = np.zeros(len(p)) if grupos is None else np.asarray(grupos)
    precisoes = []
    for g in np.unique(grupos):
        m = grupos == g
        ordem = np.lexsort((desempate[m], -p[m]))[:top]
        precisoes.append(y[m][ordem].mean())
    return {
        "auc": float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else None,
        "brier": float(brier_score_loss(y, np.clip(p, 0, 1))),
        f"precisao_{top}": float(np.mean(precisoes)),
        "taxa_base": float(y.mean()),
        "n": int(len(y)),
        "calibracao": calibracao(y, p),
    }


def calibracao(y: np.ndarray, p: np.ndarray, faixas: int = 10) -> list[dict]:
    """Probabilidade média prevista × frequência observada, em faixas de mesmo tamanho."""
    df = pd.DataFrame({"y": y, "p": p})
    df["faixa"] = pd.qcut(df.p.rank(method="first"), q=min(faixas, len(df)), labels=False)
    g = df.groupby("faixa").agg(prevista=("p", "mean"), observada=("y", "mean"), n=("y", "size"))
    return [{"prevista": round(float(r.prevista), 4), "observada": round(float(r.observada), 4), "n": int(r.n)}
            for r in g.itertuples()]


def contagem(df: pd.DataFrame, col_real: str = "real", col_prev: str = "previsto",
             horas_pico: list[int] | None = None) -> dict:
    """P2: MAE e erro percentual por região e hora (bairros somados), separado nas horas de pico."""
    reg = df.groupby(["origem", "em", "regiao"], observed=True)[[col_real, col_prev]].sum().reset_index()
    reg = reg.merge(df[["em", "hora", "dia_semana", "feriado"]].drop_duplicates("em"), on="em")
    erro = (reg[col_prev] - reg[col_real]).abs()
    saida = {
        "mae": float(erro.mean()),
        "erro_pct": float(erro.sum() / max(reg[col_real].sum(), 1e-9) * 100),
        "mae_bairro": float((df[col_prev] - df[col_real]).abs().mean()),
        "real_medio": float(reg[col_real].mean()),
        "n": int(len(reg)),
    }
    if horas_pico:
        pico = reg.hora.isin(horas_pico) & (reg.dia_semana < 5) & ~reg.feriado.astype(bool)
        saida["mae_pico"] = float(erro[pico].mean()) if pico.any() else None
    saida["por_regiao"] = {str(k): float(v) for k, v in erro.groupby(reg.regiao, observed=True).mean().items()}
    return saida


def serie(real: np.ndarray, previsto: np.ndarray) -> dict:
    """P6: erro absoluto médio em pontos percentuais."""
    e = np.abs(np.asarray(previsto) - np.asarray(real)) * 100
    return {"mae_pp": float(np.nanmean(e)), "n": int(np.isfinite(e).sum())}


def ganho(modelo: float, baseline: float, menor_melhor: bool) -> float | None:
    """Quanto o modelo melhora sobre o baseline, em % (positivo = melhor)."""
    if modelo is None or baseline is None or baseline == 0:
        return None
    return float((baseline - modelo) / baseline * 100 if menor_melhor else (modelo - baseline) / baseline * 100)
