"""P2: ocorrências esperadas por região e hora nas próximas 72 horas.

- Modelo: LightGBM com objetivo Poisson sobre bairro × hora; a região é a soma dos bairros.
- Intervalo: conformal com escore normalizado (|real − previsto| ÷ √previsto) calibrado nas últimas
  semanas do treino, no nível de região e hora. Cobertura alvo de 90%.
- Por categoria: o total previsto é repartido pela proporção de cada categoria na mesma região,
  tipo de dia e hora nas 8 semanas anteriores à origem.
- Avaliação: MAE e erro percentual por região e hora contra o sazonal ingênuo, com as horas de pico à parte.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd

from app.preditivo import avaliacao, backtest
from app.preditivo import variaveis as V

COLUNAS = V.COLUNAS_BAIRRO
PARAMS_LGBM = dict(objective="poisson", n_estimators=300, learning_rate=0.05, num_leaves=63, min_child_samples=100,
                   subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=42, n_jobs=4)
DIAS_CALIBRACAO = 28
COBERTURA = 0.9
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


@dataclass
class ModeloP2:
    lgbm: lgb.LGBMRegressor
    categorias: dict[str, list]
    q: float                    # escore conformal (90%)
    treino_origens: tuple[date, date]

    def matriz(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[COLUNAS].copy()
        for c, cats in self.categorias.items():
            X[c] = pd.Categorical(X[c].astype(str), categories=cats)
        X["feriado"] = X.feriado.astype(int)
        X["vespera"] = X.vespera.astype(int)
        return X

    def prever(self, df: pd.DataFrame) -> np.ndarray:
        return self.lgbm.predict(self.matriz(df))

    def faixa(self, mu: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        r = self.q * np.sqrt(np.asarray(mu) + 0.25)
        return np.maximum(0, mu - r), mu + r

    def contribuicoes(self, df: pd.DataFrame) -> tuple[np.ndarray, float]:
        c = self.lgbm.booster_.predict(self.matriz(df), pred_contrib=True)
        return c[:, :-1], float(np.mean(c[:, -1]))


def por_regiao(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df.groupby(["origem", "em", "regiao_id", "regiao"], observed=True)[col].sum().reset_index()


def _escore(real: np.ndarray, mu: np.ndarray) -> np.ndarray:
    return np.abs(real - mu) / np.sqrt(mu + 0.25)


def ajustar(df: pd.DataFrame, refazer: bool = True) -> ModeloP2:
    """Treina nas origens mais antigas; calibra o intervalo nas últimas 4 semanas (em ordem temporal)."""
    origens = sorted(df.origem.unique())
    corte_cal = origens[-DIAS_CALIBRACAO] if len(origens) > DIAS_CALIBRACAO * 2 else origens[len(origens) // 2]
    treino, cal = df[df.origem < corte_cal], df[df.origem >= corte_cal]
    categorias = {c: sorted(df[c].astype(str).unique()) for c in V.CATEGORICAS_BAIRRO}
    m = ModeloP2(lgb.LGBMRegressor(**PARAMS_LGBM), categorias, 1.645,
                 (pd.Timestamp(origens[0]).date(), pd.Timestamp(origens[-1]).date()))
    m.lgbm.fit(m.matriz(treino), treino.ocorrencias)
    cal = cal.assign(previsto=m.prever(cal))
    reg = cal.groupby(["origem", "em", "regiao"], observed=True)[["ocorrencias", "previsto"]].sum()
    m.q = float(np.quantile(_escore(reg.ocorrencias.to_numpy(), reg.previsto.to_numpy()), COBERTURA))
    if refazer:  # modelo final: refaz com todas as origens (o intervalo continua o calibrado fora da amostra)
        m.lgbm = lgb.LGBMRegressor(**PARAMS_LGBM).fit(m.matriz(df), df.ocorrencias)
    return m


def dados(f: V.Fontes, fim: date, cfg: dict, g: V.GradeHoras | None = None) -> pd.DataFrame:
    """Uma origem por dia, do início do treino do primeiro fold até a última com as 72 h já observadas."""
    primeiro = fim - timedelta(days=cfg["prev_backtest_dias"] + cfg["prev_treino_origens_dias"])
    ultimo = fim - timedelta(days=3)
    origens = [V.corte_local(primeiro + timedelta(days=k)) for k in range((ultimo - primeiro).days + 1)]
    return V.bairro_hora(f, origens, g=g, semanas=cfg["prev_p2_semanas_baseline"])


def avaliar(df: pd.DataFrame, fim: date, cfg: dict, log=print) -> dict:
    """Backtest: em cada corte semanal, treina com origens cujas 72 h já tinham passado e prevê a semana."""
    passo = cfg["prev_backtest_passo_dias"]
    datas = backtest.cortes(fim, cfg["prev_backtest_dias"], passo, 3)
    retreino = max(1, cfg.get("prev_p2_retreino_semanas", 2))
    partes, por_corte = [], []
    modelo = None
    for k, d in enumerate(datas):
        corte = V.corte_local(d)
        if k % retreino == 0:
            sabido = df[(df.origem + pd.Timedelta(hours=V.HORIZONTE_H) <= corte)
                        & (df.origem > corte - pd.Timedelta(days=cfg["prev_treino_origens_dias"]))]
            modelo = ajustar(sabido, refazer=False)
        origens = backtest.origens_do_corte(d, passo, fim)
        teste = df[df.origem.isin(origens)].copy()
        if teste.empty:
            continue
        teste["previsto"] = modelo.prever(teste)
        teste["real"] = teste.ocorrencias
        teste["base"] = teste.media_mesma_hora
        partes.append(teste)
        m = avaliacao.contagem(teste, horas_pico=cfg["prev_horas_pico"])
        b = avaliacao.contagem(teste, col_prev="base", horas_pico=cfg["prev_horas_pico"])
        reg = teste.groupby(["origem", "em", "regiao"], observed=True)[["real", "previsto"]].sum()
        lo, hi = modelo.faixa(reg.previsto.to_numpy())
        cobertura = float(((reg.real >= lo) & (reg.real <= hi)).mean())
        por_corte.append({"data_corte": d, "mae": m["mae"], "mae_baseline": b["mae"], "erro_pct": m["erro_pct"],
                          "erro_pct_baseline": b["erro_pct"], "mae_pico": m["mae_pico"], "mae_pico_baseline": b["mae_pico"],
                          "cobertura_90": cobertura, "n": m["n"]})
        log(f"[P2] corte {d}: MAE {m['mae']:.3f} (baseline {b['mae']:.3f}), cobertura {cobertura:.0%}")
    todos = pd.concat(partes, ignore_index=True)
    geral = avaliacao.contagem(todos, horas_pico=cfg["prev_horas_pico"])
    base = avaliacao.contagem(todos, col_prev="base", horas_pico=cfg["prev_horas_pico"])
    geral["cobertura_90"] = float(np.mean([c["cobertura_90"] for c in por_corte]))
    # Erro por faixa de horizonte (as primeiras 24 h, de 24 a 48, de 48 a 72)
    todos["faixa_h"] = pd.cut(todos.horizonte_h, [0, 24, 48, 72], labels=["0-24 h", "24-48 h", "48-72 h"])
    geral["mae_por_horizonte"] = {str(k): avaliacao.contagem(x, horas_pico=None)["mae"]
                                  for k, x in todos.groupby("faixa_h", observed=True)}
    return {"modelo": geral, "baseline": base, "por_corte": por_corte, "previsoes": todos}


# ---------------------------------------------------------------- categorias

def proporcoes(f: V.Fontes, origem: pd.Timestamp, semanas: int = 8) -> pd.DataFrame:
    """Proporção de cada categoria por região, tipo de dia (útil ou não) e hora, nas semanas antes da origem."""
    oc = f.ocorrencias[(f.ocorrencias.em < origem) & (f.ocorrencias.em >= origem - pd.Timedelta(weeks=semanas))]
    reg = dict(zip(f.bairros.id, f.bairros.regiao))
    local = oc.em.dt.tz_convert(V.FUSO)
    x = pd.DataFrame({"regiao": oc.bairro_id.map(reg), "util": local.dt.day_of_week.to_numpy() < 5,
                      "hora": local.dt.hour, "categoria": oc.categoria})
    n = x.groupby(["regiao", "util", "hora", "categoria"]).size()
    return (n / n.groupby(level=[0, 1, 2]).transform("sum")).rename("proporcao").reset_index()


# ---------------------------------------------------------------- explicação

GRUPOS = {
    "calendario": ["hora", "dia_semana", "feriado", "vespera"],
    "evento": ["evento_publico", "evento_dist_km"],
    "clima": ["chuva_mm", "temperatura_c"],
    "recente": ["oc_1h_origem", "oc_24h_origem", "oc_168h_origem"],
    "padrao": ["oc_semana_anterior", "media_mesma_hora"],
    "local": ["bairro", "regiao"],
    "agentes": ["agentes"],
    "equipamentos": ["indisponiveis_origem"],
    "horizonte": ["horizonte_h"],
}
OCULTOS = {"horizonte"}

DADOS_CONSIDERADOS = [
    "Ocorrências das últimas 8 semanas, por bairro e hora",
    "Ocorrências das últimas 24 horas e da última semana",
    "Hora, dia da semana, feriados e vésperas",
    "Previsão de chuva e temperatura por hora",
    "Eventos programados e público estimado",
    "Agentes previstos na escala e equipamentos fora de operação",
]


def _fmt(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def frase(grupo: str, x: dict) -> str:
    if grupo == "calendario":
        dia = DIAS_SEMANA[int(x["dia_semana"])].capitalize()
        extra = " (feriado)" if x["feriado"] else " (véspera de feriado)" if x["vespera"] else ""
        return f"{dia}, {int(x['hora'])} h{extra}"
    if grupo == "evento":
        if x["evento_publico"] > 0:
            return f"Evento com {_fmt(x['evento_publico'] / 1000, 0)} mil pessoas a {_fmt(x['evento_dist_km'])} km"
        return "Nenhum evento grande por perto"
    if grupo == "clima":
        if x["chuva_mm"] >= 0.5:
            return f"Chuva prevista de {_fmt(x['chuva_mm'])} mm na hora"
        return f"Tempo seco previsto, {_fmt(x['temperatura_c'], 0)} °C"
    if grupo == "recente":
        return f"{int(x['oc_24h_origem'])} ocorrências na região nas últimas 24 h"
    if grupo == "padrao":
        return f"Normal desta hora: {_fmt(x['media_mesma_hora'])} ocorrências (média de 8 semanas)"
    if grupo == "local":
        return f"Perfil dos bairros da região {x['regiao']}"
    if grupo == "agentes":
        return f"{int(x['agentes'])} agentes previstos na escala"
    if grupo == "equipamentos":
        n = int(x["indisponiveis_origem"])
        return f"{n} equipamentos fora de operação na região" if n else "Nenhum equipamento fora de operação na região"
    return "Distância até a hora prevista"


def fatores_regiao(m: ModeloP2, linhas: pd.DataFrame, top: int = 4) -> dict[tuple, list[dict]]:
    """Fatores por região e hora: efeito de cada grupo em ocorrências a mais (ou a menos) que uma hora típica.

    Em cada bairro, a diferença entre o previsto e o típico é repartida pelos grupos na proporção das
    contribuições SHAP (log). Os efeitos dos bairros são somados na região.
    """
    contrib, ref = m.contribuicoes(linhas)
    idx = {c: i for i, c in enumerate(COLUNAS)}
    z = np.column_stack([contrib[:, [idx[c] for c in cols]].sum(axis=1) for cols in GRUPOS.values()])
    mu = np.exp(ref + contrib.sum(axis=1))
    tot = z.sum(axis=1)
    incl = np.where(np.abs(tot) > 1e-6, (mu - math.exp(ref)) / np.where(np.abs(tot) > 1e-6, tot, 1), mu)
    ef = pd.DataFrame(z * incl[:, None], columns=list(GRUPOS))
    ef[["em", "regiao"]] = linhas[["em", "regiao"]].to_numpy()
    soma = ef.groupby(["em", "regiao"], observed=True)[list(GRUPOS)].sum()
    agg = linhas.groupby(["em", "regiao"], observed=True).agg(
        hora=("hora", "first"), dia_semana=("dia_semana", "first"), feriado=("feriado", "first"),
        vespera=("vespera", "first"), evento_publico=("evento_publico", "max"), evento_dist_km=("evento_dist_km", "min"),
        chuva_mm=("chuva_mm", "first"), temperatura_c=("temperatura_c", "first"), oc_24h_origem=("oc_24h_origem", "sum"),
        media_mesma_hora=("media_mesma_hora", "sum"), agentes=("agentes", "first"),
        indisponiveis_origem=("indisponiveis_origem", "sum"))
    saida = {}
    for chave, efeitos in soma.iterrows():
        x = agg.loc[chave].to_dict()
        x["regiao"] = chave[1]
        ordem = [g for g in efeitos.abs().sort_values(ascending=False).index if g not in OCULTOS][:top]
        saida[chave] = [{"descricao": frase(g, x), "efeito": round(float(efeitos[g]), 2), "grupo": g} for g in ordem]
    return saida


def importancia_global(m: ModeloP2, linhas: pd.DataFrame) -> dict[str, float]:
    contrib, _ = m.contribuicoes(linhas)
    idx = {c: i for i, c in enumerate(COLUNAS)}
    tot = {g: float(np.abs(contrib[:, [idx[c] for c in cols]].sum(axis=1)).mean()) for g, cols in GRUPOS.items()}
    s = sum(tot.values()) or 1
    return {g: round(v / s, 4) for g, v in sorted(tot.items(), key=lambda kv: -kv[1])}
