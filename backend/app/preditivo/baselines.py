"""Baselines: o mínimo que cada modelo precisa superar. Sempre exibidos ao lado do modelo.

- P1: taxa histórica de falha do tipo de equipamento.
- P2: média da mesma hora e dia da semana nas últimas 8 semanas (sazonal ingênuo).
- P6: última média móvel de 30 dias da disponibilidade.

Usam só dados anteriores ao corte, como os modelos.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.preditivo.variaveis import Fontes, _estado_em


def p1_taxas(f: Fontes, corte: pd.Timestamp, dias: int = 365) -> pd.Series:
    """Falhas por equipamento-dia de cada tipo, nos `dias` antes do corte."""
    falhas = f.historico[(f.historico.nova == "mau_funcionamento") & (f.historico.em < corte)
                         & (f.historico.em >= corte - pd.Timedelta(days=dias))]
    por_tipo = falhas.merge(f.equipamentos[["id", "prefixo"]], left_on="equipamento_id", right_on="id").groupby("prefixo").size()
    estado = _estado_em(f.historico, corte)
    ativos = f.equipamentos[f.equipamentos.id.map(estado).isin(["operacional", "mau_funcionamento", "em_manutencao"])]
    n = ativos.groupby("prefixo").size()
    return (por_tipo.reindex(n.index, fill_value=0) / (n * dias)).fillna(0)


def p1_prever(f: Fontes, linhas: pd.DataFrame, janela_dias: int, dias: int = 365) -> np.ndarray:
    """Probabilidade de falhar em `janela_dias` = 1 - (1 - taxa diária do tipo) ^ janela."""
    saida = np.zeros(len(linhas))
    for corte, idx in linhas.groupby("corte").groups.items():
        taxa = p1_taxas(f, corte, dias)
        r = linhas.loc[idx, "prefixo"].astype(str).map(taxa).fillna(taxa.mean() if len(taxa) else 0).to_numpy()
        saida[linhas.index.get_indexer(idx)] = 1 - (1 - r) ** janela_dias
    return saida


def p2_prever(linhas: pd.DataFrame) -> np.ndarray:
    """Sazonal ingênuo: já calculado nas variáveis como `media_mesma_hora`."""
    return linhas.media_mesma_hora.to_numpy()


def p6_prever(serie: pd.DataFrame, corte: date, horizonte_dias: int, dias: int = 30) -> pd.DataFrame:
    """Disponibilidade prevista para corte + horizonte = média dos `dias` antes do corte, por região."""
    janela = serie[(serie.dia < corte) & (serie.dia >= corte - timedelta(days=dias))]
    media = janela.groupby("regiao").disponibilidade.mean()
    return pd.DataFrame({"regiao": media.index, "dia": corte + timedelta(days=horizonte_dias), "previsto": media.to_numpy()})
