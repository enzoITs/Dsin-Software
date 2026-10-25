"""Backtest com origem móvel: treinar até a data T, prever T+1…T+k, avançar, repetir.

Cobre os últimos `prev_backtest_dias` (90 por padrão), com um corte por semana. A mesma
estrutura avalia baselines (que "treinam" só olhando o passado) e modelos.
"""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.preditivo import avaliacao, baselines
from app.preditivo import variaveis as V


def cortes(fim: date, dias: int = 91, passo: int = 7, horizonte_dias: int = 0) -> list[date]:
    """Datas de corte semanais nos últimos `dias` antes de `fim`, deixando espaço para o horizonte."""
    saida, d = [], fim - timedelta(days=dias)
    while d + timedelta(days=max(horizonte_dias, 1)) <= fim:
        saida.append(d)
        d += timedelta(days=passo)
    return saida


def origem_movel(datas: list[date], rodar: Callable[[date], dict[str, Any]]) -> list[dict]:
    """Roda `rodar(corte)` para cada corte. `rodar` treina com dados < corte e devolve métricas da janela seguinte."""
    return [{"data_corte": d, **rodar(d)} for d in datas]


# ---------------------------------------------------------------- baselines


def p1_baseline(f: V.Fontes, fim: date, cfg: dict, janela_dias: int) -> dict:
    datas = cortes(fim, cfg["prev_backtest_dias"], cfg["prev_backtest_passo_dias"], janela_dias)
    linhas = V.equipamentos(f, [V.corte_local(d) for d in datas])
    alvo = f"falha_{janela_dias}d"
    p = baselines.p1_prever(f, linhas, janela_dias, cfg["prev_p1_taxa_dias"])
    geral = avaliacao.classificacao(linhas[alvo].to_numpy(), p, linhas.corte.to_numpy())
    por_corte = []
    for c, idx in linhas.groupby("corte").groups.items():
        pos = linhas.index.get_indexer(idx)
        m = avaliacao.classificacao(linhas.loc[idx, alvo].to_numpy(), p[pos])
        m.pop("calibracao")
        por_corte.append({"data_corte": c.date(), **m})
    return {"geral": geral, "por_corte": por_corte, "linhas": len(linhas)}


def origens_do_corte(corte: date, passo: int, fim: date, horizonte_h: int = V.HORIZONTE_H) -> list[pd.Timestamp]:
    """Uma origem por dia (meia-noite) dentro da semana do corte, com o horizonte inteiro antes do fim."""
    limite = V.corte_local(fim) - pd.Timedelta(hours=horizonte_h)
    return [o for o in (V.corte_local(corte + timedelta(days=k)) for k in range(passo)) if o <= limite]


def p2_baseline(f: V.Fontes, fim: date, cfg: dict) -> dict:
    passo = cfg["prev_backtest_passo_dias"]
    datas = cortes(fim, cfg["prev_backtest_dias"], passo, 3)
    todas = [o for d in datas for o in origens_do_corte(d, passo, fim)]
    linhas = V.bairro_hora(f, todas, semanas=cfg["prev_p2_semanas_baseline"])
    linhas["real"] = linhas.ocorrencias
    linhas["previsto"] = baselines.p2_prever(linhas)
    geral = avaliacao.contagem(linhas, horas_pico=cfg["prev_horas_pico"])
    por_corte = []
    for d in datas:
        os_ = origens_do_corte(d, passo, fim)
        m = avaliacao.contagem(linhas[linhas.origem.isin(os_)], horas_pico=cfg["prev_horas_pico"])
        m.pop("por_regiao")
        por_corte.append({"data_corte": d, **m})
    return {"geral": geral, "por_corte": por_corte, "linhas": len(linhas)}


def p6_baseline(f: V.Fontes, fim: date, cfg: dict, horizonte_dias: int = 30) -> dict:
    serie = V.disponibilidade_diaria(f, fim - timedelta(days=cfg["prev_backtest_dias"] + 120), fim)
    datas = cortes(fim, cfg["prev_backtest_dias"], cfg["prev_backtest_passo_dias"], horizonte_dias)
    por_corte, todos = [], []
    for d in datas:
        prev = baselines.p6_prever(serie, d, horizonte_dias, cfg["prev_p6_media_dias"])
        real = serie[serie.dia == d + timedelta(days=horizonte_dias)][["regiao", "disponibilidade"]]
        x = prev.merge(real, on="regiao")
        todos.append(x)
        por_corte.append({"data_corte": d, **avaliacao.serie(x.disponibilidade, x.previsto)})
    x = pd.concat(todos) if todos else pd.DataFrame(columns=["disponibilidade", "previsto"])
    return {"geral": avaliacao.serie(x.disponibilidade.to_numpy(), x.previsto.to_numpy()), "por_corte": por_corte,
            "horizonte_dias": horizonte_dias}


def resumo_numerico(m: dict) -> dict:
    """Só os números (sem curvas), para gravar como métricas de versão."""
    return {k: v for k, v in m.items() if isinstance(v, (int, float)) or v is None or (isinstance(v, dict) and k == "por_regiao")}


def json_limpo(v):
    """Converte tipos do NumPy e datas para gravar em JSONB."""
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: json_limpo(x) for k, x in v.items()}
    if isinstance(v, list):
        return [json_limpo(x) for x in v]
    return v
