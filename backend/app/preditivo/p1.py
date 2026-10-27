"""P1: risco de falha de equipamento nos próximos 7 e 30 dias.

- Modelo: LightGBM (gradient boosting) com probabilidade calibrada por regressão isotônica numa
  janela temporal separada; regressão logística como segundo comparativo.
- Explicação: contribuições SHAP do próprio LightGBM (TreeSHAP), agrupadas em fatores que o gestor
  entende ("Manutenção preventiva atrasada há 21 dias") e convertidas em efeito na probabilidade.
- Avaliação: backtest de origem móvel nos últimos 90 dias, contra o baseline (taxa do tipo).
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.preditivo import avaliacao, backtest, baselines
from app.preditivo import variaveis as V

COLUNAS = V.COLUNAS_EQUIPAMENTO
NUMERICAS = [c for c in COLUNAS if c not in V.CATEGORICAS_EQUIPAMENTO]
PARAMS_LGBM = dict(n_estimators=250, learning_rate=0.05, num_leaves=31, min_child_samples=200, subsample=0.8,
                   subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=42, n_jobs=4)
SEMANAS_CALIBRACAO = 4
AMOSTRA_LOGISTICA = 150_000


@dataclass
class ModeloP1:
    janela: int
    lgbm: lgb.LGBMClassifier
    calibrador: IsotonicRegression
    categorias: dict[str, list]
    taxa_treino: float
    treino_cortes: tuple[date, date]
    calibracao_backtest: list[dict] = field(default_factory=list)

    def matriz(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[COLUNAS].copy()
        for c, cats in self.categorias.items():
            X[c] = pd.Categorical(X[c].astype(str), categories=cats)
        X["movel"] = X.movel.astype(int)
        return X

    def prever(self, df: pd.DataFrame) -> np.ndarray:
        bruta = self.lgbm.predict_proba(self.matriz(df))[:, 1]
        return np.clip(self.calibrador.predict(bruta), 1e-4, 0.999)

    def contribuicoes(self, df: pd.DataFrame) -> tuple[np.ndarray, float]:
        """Contribuições SHAP (em log-chance) por variável e o valor de referência."""
        c = self.lgbm.booster_.predict(self.matriz(df), pred_contrib=True)
        return c[:, :-1], float(np.mean(c[:, -1]))


def _alvo(janela: int) -> str:
    return f"falha_{janela}d"


def ajustar(df: pd.DataFrame, janela: int) -> ModeloP1:
    """Treina o LightGBM nos cortes mais antigos e calibra nas últimas semanas (sempre em ordem temporal)."""
    cortes = sorted(df.corte.unique())
    corte_cal = cortes[-SEMANAS_CALIBRACAO] if len(cortes) > SEMANAS_CALIBRACAO * 2 else cortes[len(cortes) // 2]
    treino, cal = df[df.corte < corte_cal], df[df.corte >= corte_cal]
    categorias = {c: sorted(df[c].astype(str).unique()) for c in V.CATEGORICAS_EQUIPAMENTO}
    m = ModeloP1(janela, lgb.LGBMClassifier(**PARAMS_LGBM), IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1),
                 categorias, float(df[_alvo(janela)].mean()), (cortes[0].date(), cortes[-1].date()))
    m.lgbm.fit(m.matriz(treino), treino[_alvo(janela)])
    m.calibrador.fit(m.lgbm.predict_proba(m.matriz(cal))[:, 1], cal[_alvo(janela)])
    return m


def logistica(df: pd.DataFrame, janela: int):
    """Segundo comparativo: regressão logística com as mesmas variáveis (amostra, para treinar rápido)."""
    amostra = df.sample(min(len(df), AMOSTRA_LOGISTICA), random_state=42)
    prep = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=50), V.CATEGORICAS_EQUIPAMENTO),
        ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), NUMERICAS),
    ])
    modelo = make_pipeline(prep, LogisticRegression(max_iter=500, C=0.5))
    X = amostra[COLUNAS].copy()
    X["movel"] = X.movel.astype(int)
    modelo.fit(X, amostra[_alvo(janela)])
    return modelo


def _prever_logistica(modelo, df: pd.DataFrame) -> np.ndarray:
    X = df[COLUNAS].copy()
    X["movel"] = X.movel.astype(int)
    return modelo.predict_proba(X)[:, 1]


def dados(f: V.Fontes, fim: date, cfg: dict, janela: int) -> pd.DataFrame:
    """Cortes semanais desde o início do treino do primeiro fold do backtest até o último com alvo completo."""
    passo = cfg["prev_backtest_passo_dias"]
    primeiro = fim - timedelta(days=cfg["prev_backtest_dias"]) - timedelta(weeks=cfg["prev_treino_semanas"] + 1)
    cortes, d = [], primeiro
    while d + timedelta(days=janela) <= fim:   # mesma grade dos cortes do backtest
        cortes.append(V.corte_local(d))
        d += timedelta(days=passo)
    return V.equipamentos(f, cortes)


def avaliar(f: V.Fontes, df: pd.DataFrame, fim: date, cfg: dict, janela: int, log=print) -> dict:
    """Backtest de origem móvel: para cada corte, treina só com linhas cujo alvo já era conhecido no corte."""
    alvo = _alvo(janela)
    datas = backtest.cortes(fim, cfg["prev_backtest_dias"], cfg["prev_backtest_passo_dias"], janela)
    retreino = max(1, cfg.get("prev_p1_retreino_semanas", 2))
    previsto = []
    por_corte = []
    modelo = log_modelo = None
    for k, d in enumerate(datas):
        corte = V.corte_local(d)
        if k % retreino == 0:
            sabido = df[(df.corte + pd.Timedelta(days=janela) <= corte)
                        & (df.corte > corte - pd.Timedelta(weeks=cfg["prev_treino_semanas"]))]
            modelo = ajustar(sabido, janela)
            log_modelo = logistica(sabido, janela)
        teste = df[df.corte == corte]
        if teste.empty:
            continue
        p = modelo.prever(teste)
        pl = _prever_logistica(log_modelo, teste)
        pb = baselines.p1_prever(f, teste, janela, cfg["prev_p1_taxa_dias"])
        previsto.append(pd.DataFrame({"corte": teste.corte, "y": teste[alvo], "p": p, "p_log": pl, "p_base": pb,
                                      "regiao": teste.regiao.astype(str), "prefixo": teste.prefixo.astype(str)}))
        m, mb = avaliacao.classificacao(teste[alvo], p), avaliacao.classificacao(teste[alvo], pb)
        por_corte.append({"data_corte": d, "auc": m["auc"], "brier": m["brier"], "precisao_50": m["precisao_50"],
                          "auc_baseline": mb["auc"], "brier_baseline": mb["brier"], "precisao_50_baseline": mb["precisao_50"],
                          "taxa_base": m["taxa_base"], "n": m["n"]})
        def f3(v):
            return "—" if v is None else f"{v:.3f}"  # semana sem nenhuma falha: AUC indefinida
        log(f"[P1 {janela}d] corte {d}: AUC {f3(m['auc'])} (baseline {f3(mb['auc'])})")
    todos = pd.concat(previsto, ignore_index=True)
    geral = avaliacao.classificacao(todos.y, todos.p, todos.corte)
    return {
        "modelo": geral,
        "baseline": avaliacao.classificacao(todos.y, todos.p_base, todos.corte),
        "logistica": {k: v for k, v in avaliacao.classificacao(todos.y, todos.p_log, todos.corte).items() if k != "calibracao"},
        "por_corte": por_corte,
        "previsoes": todos,
    }


# ---------------------------------------------------------------- explicação em linguagem do gestor

GRUPOS = {
    "idade": ["idade_dias"],
    "equipamento": ["prefixo", "marca", "modelo"],
    "manutencao": ["atraso_preventiva", "dias_desde_preventiva", "dias_desde_manutencao", "periodicidade"],
    "falhas": ["falhas_7d", "falhas_30d", "falhas_90d", "falhas_180d", "dias_desde_falha"],
    "chuva": ["chuva_ontem", "chuva_7d", "dias_chuva_forte_7d", "chuva_prevista_7d", "dias_chuva_forte_previstos_7d"],
    "calor": ["tmax_7d", "tmax_prevista_7d", "dias_calor_previstos_7d"],
    "furtos": ["furtos_bairro_90d"],
    "local": ["regiao", "velocidade_maxima", "movel"],
}

DADOS_CONSIDERADOS = [
    "Histórico de falhas dos últimos 180 dias",
    "Manutenções preventivas e corretivas, e atrasos",
    "Idade, tipo, marca e modelo do equipamento",
    "Chuva e temperatura dos últimos 7 dias e previsão dos próximos 7",
    "Furtos no bairro nos últimos 90 dias",
    "Região e tipo de via",
]


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _plural(n: float, um: str, varios: str) -> str:
    n = int(round(n))
    return f"{n} {um if n == 1 else varios}"


def frase(grupo: str, x: dict) -> str:
    """Descrição do fator com os valores deste equipamento, sem nomes técnicos."""
    if grupo == "idade":
        meses = (_num(x["idade_dias"]) or 0) / 30.4
        return f"Instalado há {_plural(meses, 'mês', 'meses')}" if meses < 24 else f"Instalado há {meses / 12:.1f} anos".replace(".", ",")
    if grupo == "equipamento":
        return f"Modelo {x['modelo']} ({str(x['marca']).strip().title()})"
    if grupo == "manutencao":
        atraso = _num(x["atraso_preventiva"])
        if atraso is None:
            return "Sem manutenção preventiva registrada no período"
        if atraso > 0:
            return f"Manutenção preventiva atrasada há {_plural(atraso, 'dia', 'dias')}"
        return f"Manutenção preventiva em dia (próxima em {_plural(-atraso, 'dia', 'dias')})"
    if grupo == "falhas":
        n90 = _num(x["falhas_90d"]) or 0
        if n90 > 0:
            return f"{_plural(n90, 'falha', 'falhas')} nos últimos 90 dias"
        n180 = _num(x["falhas_180d"]) or 0
        return f"{_plural(n180, 'falha', 'falhas')} nos últimos 180 dias" if n180 else "Nenhuma falha nos últimos 180 dias"
    if grupo == "chuva":
        prev = _num(x["dias_chuva_forte_previstos_7d"]) or 0
        pass_ = _num(x["dias_chuva_forte_7d"]) or 0
        if prev:
            return f"Chuva forte prevista em {_plural(prev, 'dia', 'dias')} da próxima semana"
        if pass_:
            return f"Chuva forte em {_plural(pass_, 'dia', 'dias')} da última semana"
        return "Sem chuva forte na última semana nem prevista"
    if grupo == "calor":
        t = _num(x["tmax_prevista_7d"])
        return f"Temperatura prevista de até {t:.0f} °C nos próximos 7 dias" if t is not None else "Temperatura prevista"
    if grupo == "furtos":
        n = _num(x["furtos_bairro_90d"]) or 0
        return f"{_plural(n, 'furto', 'furtos')} de equipamento no bairro em 90 dias" if n else "Nenhum furto no bairro em 90 dias"
    v = _num(x.get("velocidade_maxima"))
    return f"Via de {v:.0f} km/h, região {x['regiao']}" if v else f"Região {x['regiao']}"


def fatores(m: ModeloP1, df: pd.DataFrame, top: int = 4) -> list[list[dict]]:
    """Para cada linha, os fatores que mais pesaram e quanto cada um somou à probabilidade.

    A diferença entre a probabilidade do equipamento e a de um equipamento típico é repartida entre
    os grupos de fatores na proporção das contribuições SHAP (em log-chance). A soma dos efeitos de
    todos os grupos dá exatamente essa diferença.
    """
    contrib, ref = m.contribuicoes(df)
    idx = {c: i for i, c in enumerate(COLUNAS)}
    z = np.column_stack([contrib[:, [idx[c] for c in cols]].sum(axis=1) for cols in GRUPOS.values()])
    nomes = list(GRUPOS)
    base_p = float(m.calibrador.predict([1 / (1 + np.exp(-ref))])[0])
    p = m.prever(df)
    total = z.sum(axis=1)
    inclinacao = np.where(np.abs(total) > 1e-3, (p - base_p) / np.where(np.abs(total) > 1e-3, total, 1), p * (1 - p))
    efeitos = z * inclinacao[:, None]
    saida = []
    for i, x in enumerate(df[COLUNAS].to_dict("records")):
        ordem = np.argsort(-np.abs(efeitos[i]))[:top]
        saida.append([{"descricao": frase(nomes[j], x), "efeito": round(float(efeitos[i, j]), 3), "grupo": nomes[j]}
                      for j in ordem])
    return saida


def importancia_global(m: ModeloP1, df: pd.DataFrame) -> dict[str, float]:
    """Peso médio de cada grupo de fatores (média do |SHAP|), para a tela de confiança e a descoberta de padrões."""
    contrib, _ = m.contribuicoes(df)
    idx = {c: i for i, c in enumerate(COLUNAS)}
    tot = {g: float(np.abs(contrib[:, [idx[c] for c in cols]].sum(axis=1)).mean()) for g, cols in GRUPOS.items()}
    s = sum(tot.values()) or 1
    return {g: round(v / s, 4) for g, v in sorted(tot.items(), key=lambda kv: -kv[1])}


AMOSTRA_FAIXA = 300


def faixa(p: float, n: int = AMOSTRA_FAIXA, z: float = 1.645) -> tuple[float, float]:
    """Faixa de 90% (Wilson) para a probabilidade p: entre quantos de cada 100 equipamentos com essa
    previsão devem de fato falhar, considerando a incerteza de uma amostra de `n` casos parecidos."""
    centro = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    margem = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return max(0.0, centro - margem), min(1.0, centro + margem)


def nivel(p: float, limites_nivel: list[float]) -> str:
    moderado, alto, muito_alto = limites_nivel
    if p >= muito_alto:
        return "MUITO_ALTO"
    if p >= alto:
        return "ALTO"
    if p >= moderado:
        return "MODERADO"
    return "BAIXO"


COMO_AJUDA = {
    "RAD": "Antecipar a manutenção evita perder a fiscalização de velocidade neste trecho",
    "CAM": "Antecipar a manutenção evita um ponto cego no monitoramento da região",
    "TOT": "Antecipar a manutenção evita o rotativo sem pagamento nesta zona",
    "BAL": "Antecipar a manutenção evita perder a pesagem de veículos pesados neste ponto",
    "CAN": "Antecipar a manutenção evita o acesso controlado travado ou aberto",
}


def acao(p: float, niv: str, prefixo: str, codigo: str, eid: int, hoje: date) -> dict:
    if niv in ("ALTO", "MUITO_ALTO"):
        prazo = hoje + timedelta(days=2 if niv == "MUITO_ALTO" else 5)
        return {"texto": f"Abrir ordem de serviço preventiva para {codigo} até {prazo:%d/%m}", "tipo": "ABRIR_ORDEM_SERVICO",
                "parametros": {"equipamento_id": eid, "prioridade": "alta" if niv == "MUITO_ALTO" else "media",
                               "prazo": prazo.isoformat()}}
    if niv == "MODERADO":
        return {"texto": f"Incluir {codigo} na próxima rota de manutenção preventiva", "tipo": "INCLUIR_ROTA_MANUTENCAO",
                "parametros": {"equipamento_id": eid}}
    return {"texto": "Nenhuma ação extra: manter a manutenção programada", "tipo": "NENHUMA", "parametros": {}}
