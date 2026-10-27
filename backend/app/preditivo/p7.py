"""P7: probabilidade de furto de cada equipamento nos próximos 30 dias.

Prevê sobre lugares e equipamentos, nunca sobre pessoas. As variáveis descrevem o ponto:

- densidade de furtos de equipamento no passado (no bairro e num raio de 500 m);
- vandalismo de madrugada registrado no bairro;
- cobertura de câmeras: distância até a câmera em operação mais próxima no corte;
- agentes na escala de madrugada na região;
- tipo, idade e se o equipamento é móvel.

Modelo: LightGBM com regularização forte (furto é raro: cerca de 20 por mês na cidade), contra o
baseline da taxa histórica de furto do tipo. Mesmo backtest de origem móvel de P1.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.preditivo import avaliacao, backtest
from app.preditivo import variaveis as V

JANELA = 30
RAIO_M = 500
ALCANCE_CAMERA_M = 300
COLUNAS = ["prefixo", "movel", "idade_dias", "furtos_bairro_90d", "furtos_bairro_365d", "furtos_500m_365d",
           "vandalismo_madrugada_bairro_90d", "dist_camera_m", "agentes_madrugada"]
CATEGORICAS = ["prefixo"]
# Restrição monótona: mais furtos e vandalismo por perto e câmera mais longe nunca diminuem o risco. Com
# eventos tão raros, sem ela o modelo aprende degraus sem sentido na distância da câmera, e o contrafactual
# da expansão (C2) sai com o sinal trocado. Custa pouco na AUC do backtest (0,746 sem, 0,733 com).
MONOTONO = {"furtos_bairro_90d": 1, "furtos_bairro_365d": 1, "furtos_500m_365d": 1, "vandalismo_madrugada_bairro_90d": 1,
            "dist_camera_m": 1}
PARAMS_LGBM = dict(n_estimators=200, learning_rate=0.03, num_leaves=8, min_child_samples=400, subsample=0.8,
                   subsample_freq=1, colsample_bytree=0.9, reg_lambda=5.0, verbose=-1, random_state=42, n_jobs=4,
                   monotone_constraints=[MONOTONO.get(c, 0) for c in COLUNAS])
TIPOS_FURTO = ["CAM", "RAD", "TOT", "BAL", "CAN", "PAT", "VAF", "VIA"]
DADOS_CONSIDERADOS = [
    "Furtos de equipamentos no bairro e num raio de 500 m (último ano)",
    "Vandalismo de madrugada registrado no bairro (90 dias)",
    "Distância até a câmera em operação mais próxima",
    "Agentes na escala de madrugada na região",
    "Tipo e idade do equipamento",
]
COMO_AJUDA = ("Mostra quais pontos têm mais chance de sofrer furto, para incluir na ronda de madrugada, "
              "priorizar uma câmera por perto ou reforçar a fixação antes que o equipamento suma")


def _metros(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Coordenadas aproximadas em metros (projeção local, boa o bastante dentro de uma cidade)."""
    return np.column_stack([np.asarray(lon) * 111_320 * math.cos(math.radians(-23.55)), np.asarray(lat) * 110_540])


def posicoes(db: Session) -> pd.DataFrame:
    r = db.execute(text("SELECT equipamento_id id, ST_X(geom) lon, ST_Y(geom) lat FROM localizacao WHERE geom IS NOT NULL"))
    return pd.DataFrame(r.fetchall(), columns=["id", "lon", "lat"])


@dataclass
class Contexto:
    """O que não muda entre cortes: posições e onde cada furto aconteceu."""

    pos: pd.DataFrame          # id, lon, lat, x, y
    furtos: pd.DataFrame       # equipamento_id, em, bairro_id, x, y
    vandalismo: pd.DataFrame   # em, bairro_id (só madrugada)


def contexto(db: Session, f: V.Fontes) -> Contexto:
    pos = posicoes(db)
    xy = _metros(pos.lon, pos.lat)
    pos["x"], pos["y"] = xy[:, 0], xy[:, 1]
    furtos = f.historico[f.historico.nova == "furtado"][["equipamento_id", "em"]].merge(
        f.equipamentos[["id", "bairro_id"]], left_on="equipamento_id", right_on="id").drop(columns="id")
    furtos = furtos.merge(pos[["id", "x", "y"]], left_on="equipamento_id", right_on="id", how="left").drop(columns="id")
    oc = f.ocorrencias
    hora = oc.em.dt.tz_convert(V.FUSO).dt.hour
    vand = oc[(oc.categoria == "VANDALISMO") & (hora < 5)][["em", "bairro_id"]]
    return Contexto(pos, furtos, vand)


def _agentes_madrugada(f: V.Fontes, corte: pd.Timestamp, dias: int = 28) -> dict:
    """Agentes médios em turno entre 0 h e 5 h nas últimas `dias` noites, por região (id)."""
    horas = pd.date_range(corte - pd.Timedelta(days=dias), corte, freq="h", inclusive="left")
    madr = horas[horas.tz_convert(V.FUSO).hour < 5]
    if len(madr) == 0:
        return {}
    por = V._agentes_por_regiao_hora(f, horas)
    sel = np.isin(horas, madr)
    return {r: float(v[sel].mean()) for r, v in por.items()}


def variaveis(f: V.Fontes, ctx: Contexto, cortes: list[pd.Timestamp], alvo: bool = True) -> pd.DataFrame:
    """Uma linha por equipamento em serviço (e não furtado) em cada corte."""
    cam = f.equipamentos[f.equipamentos.prefixo.astype(str) == "CAM"].id
    reg_id = dict(zip(f.bairros.regiao, f.bairros.regiao_id))
    partes = []
    for corte in cortes:
        corte = pd.Timestamp(corte)
        estado = V._estado_em(f.historico, corte)
        ids = estado[estado.isin(["operacional", "mau_funcionamento", "em_manutencao"])].index
        x = f.equipamentos[f.equipamentos.id.isin(ids) & f.equipamentos.prefixo.astype(str).isin(TIPOS_FURTO)].copy()
        x = x[x.data_instalacao.notna() & (x.data_instalacao < corte.tz_localize(None))]
        x = x.merge(ctx.pos[["id", "x", "y"]], on="id", how="inner")
        if x.empty:
            continue
        x["corte"] = corte
        x["idade_dias"] = (corte.tz_localize(None) - x.data_instalacao).dt.days
        passado = ctx.furtos[ctx.furtos.em < corte]
        p90 = passado[passado.em >= corte - pd.Timedelta(days=90)].groupby("bairro_id").size()
        p365 = passado[passado.em >= corte - pd.Timedelta(days=365)]
        x["furtos_bairro_90d"] = x.bairro_id.map(p90).fillna(0)
        x["furtos_bairro_365d"] = x.bairro_id.map(p365.groupby("bairro_id").size()).fillna(0)
        pts = p365.dropna(subset=["x"])
        if len(pts):
            arv = cKDTree(pts[["x", "y"]].to_numpy())
            x["furtos_500m_365d"] = [len(v) for v in arv.query_ball_point(x[["x", "y"]].to_numpy(), RAIO_M)]
        else:
            x["furtos_500m_365d"] = 0
        v = ctx.vandalismo[(ctx.vandalismo.em < corte) & (ctx.vandalismo.em >= corte - pd.Timedelta(days=90))]
        x["vandalismo_madrugada_bairro_90d"] = x.bairro_id.map(v.groupby("bairro_id").size()).fillna(0)
        cam_ok = ctx.pos[ctx.pos.id.isin(cam) & ctx.pos.id.map(estado).eq("operacional")]
        if len(cam_ok) >= 2:
            d, i = cKDTree(cam_ok[["x", "y"]].to_numpy()).query(x[["x", "y"]].to_numpy(), k=2)
            proprio = cam_ok.id.to_numpy()[i[:, 0]] == x.id.to_numpy()   # a própria câmera não se cobre
            x["dist_camera_m"] = np.where(proprio, d[:, 1], d[:, 0]).clip(max=5000)
        else:
            x["dist_camera_m"] = 5000.0
        ag = _agentes_madrugada(f, corte)
        x["agentes_madrugada"] = x.regiao.map(reg_id).map(ag).fillna(0)
        if alvo:
            futuros = ctx.furtos[(ctx.furtos.em >= corte) & (ctx.furtos.em < corte + pd.Timedelta(days=JANELA))]
            x["furto_30d"] = x.id.isin(futuros.equipamento_id).astype(int)
        partes.append(x)
    if not partes:
        return pd.DataFrame()
    df = pd.concat(partes, ignore_index=True)
    df["prefixo"] = df.prefixo.astype(str)
    return df


@dataclass
class ModeloP7:
    lgbm: lgb.LGBMClassifier
    categorias: dict[str, list]
    taxa_treino: float
    treino_cortes: tuple[date, date]

    def matriz(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[COLUNAS].copy()
        for c, cats in self.categorias.items():
            X[c] = pd.Categorical(X[c].astype(str), categories=cats)
        X["movel"] = X.movel.astype(int)
        return X

    def prever(self, df: pd.DataFrame) -> np.ndarray:
        return np.clip(self.lgbm.predict_proba(self.matriz(df))[:, 1], 1e-5, 0.99)

    def contribuicoes(self, df: pd.DataFrame) -> tuple[np.ndarray, float]:
        c = self.lgbm.booster_.predict(self.matriz(df), pred_contrib=True)
        return c[:, :-1], float(np.mean(c[:, -1]))


def ajustar(df: pd.DataFrame) -> ModeloP7:
    cats = {c: sorted(df[c].astype(str).unique()) for c in CATEGORICAS}
    cortes = sorted(df.corte.unique())
    m = ModeloP7(lgb.LGBMClassifier(**PARAMS_LGBM), cats, float(df.furto_30d.mean()),
                 (pd.Timestamp(cortes[0]).date(), pd.Timestamp(cortes[-1]).date()))
    m.lgbm.fit(m.matriz(df), df.furto_30d)
    return m


def baseline(df: pd.DataFrame, ctx: Contexto, f: V.Fontes, dias: int = 365) -> np.ndarray:
    """Taxa histórica de furto do tipo: furtos por equipamento-dia nos `dias` antes do corte, em 30 dias."""
    tipo = dict(zip(f.equipamentos.id, f.equipamentos.prefixo.astype(str)))
    saida = np.zeros(len(df))
    for corte, idx in df.groupby("corte").groups.items():
        fx = ctx.furtos[(ctx.furtos.em < corte) & (ctx.furtos.em >= corte - pd.Timedelta(days=dias))]
        n_tipo = fx.equipamento_id.map(tipo).value_counts()
        base = df.loc[idx, "prefixo"].value_counts()
        taxa = (n_tipo.reindex(base.index, fill_value=0) / (base * dias)).fillna(0)
        r = df.loc[idx, "prefixo"].map(taxa).fillna(0).to_numpy()
        saida[df.index.get_indexer(idx)] = 1 - (1 - r) ** JANELA
    return saida


def cortes_treino(fim: date, cfg: dict) -> list[pd.Timestamp]:
    passo = cfg["prev_backtest_passo_dias"]
    d = fim - timedelta(days=cfg["prev_backtest_dias"]) - timedelta(weeks=cfg["prev_treino_semanas"] + 5)
    saida = []
    while d + timedelta(days=JANELA) <= fim:
        saida.append(V.corte_local(d))
        d += timedelta(days=passo)
    return saida


def avaliar(f: V.Fontes, ctx: Contexto, df: pd.DataFrame, fim: date, cfg: dict) -> dict:
    datas = backtest.cortes(fim, cfg["prev_backtest_dias"], cfg["prev_backtest_passo_dias"], JANELA)
    previsto, por_corte = [], []
    modelo = None
    for k, d in enumerate(datas):
        corte = V.corte_local(d)
        if k % 2 == 0:
            sabido = df[(df.corte + pd.Timedelta(days=JANELA) <= corte)
                        & (df.corte > corte - pd.Timedelta(weeks=cfg["prev_treino_semanas"]))]
            modelo = ajustar(sabido)
        teste = df[df.corte == corte]
        if teste.empty:
            continue
        p = modelo.prever(teste)
        pb = baseline(teste, ctx, f)
        previsto.append(pd.DataFrame({"corte": teste.corte, "y": teste.furto_30d, "p": p, "p_base": pb}))
        m, mb = avaliacao.classificacao(teste.furto_30d, p), avaliacao.classificacao(teste.furto_30d, pb)
        por_corte.append({"data_corte": d, "auc": m["auc"], "brier": m["brier"], "precisao_50": m["precisao_50"],
                          "auc_baseline": mb["auc"], "brier_baseline": mb["brier"],
                          "precisao_50_baseline": mb["precisao_50"], "taxa_base": m["taxa_base"], "n": m["n"]})
    todos = pd.concat(previsto, ignore_index=True)
    return {"modelo": avaliacao.classificacao(todos.y, todos.p, todos.corte),
            "baseline": avaliacao.classificacao(todos.y, todos.p_base, todos.corte), "por_corte": por_corte}


# ---------------------------------------------------------------- explicação

GRUPOS = {
    "historico_local": ["furtos_bairro_90d", "furtos_bairro_365d", "furtos_500m_365d"],
    "vandalismo": ["vandalismo_madrugada_bairro_90d"],
    "cobertura": ["dist_camera_m"],
    "agentes": ["agentes_madrugada"],
    "equipamento": ["prefixo", "movel", "idade_dias"],
}
NOME_TIPO = {"CAM": "câmera", "RAD": "radar", "TOT": "totem", "BAL": "balança", "CAN": "cancela", "PAT": "patinete",
             "VAF": "painel", "VIA": "equipamento"}


def frase(grupo: str, x: dict) -> str:
    if grupo == "historico_local":
        n500, nb = int(x["furtos_500m_365d"]), int(x["furtos_bairro_365d"])
        if n500:
            return f"{n500} {'furto' if n500 == 1 else 'furtos'} de equipamento a menos de 500 m no último ano"
        return f"{nb} furtos de equipamento no bairro no último ano" if nb else "Nenhum furto no bairro no último ano"
    if grupo == "vandalismo":
        n = int(x["vandalismo_madrugada_bairro_90d"])
        return f"{n} registros de vandalismo de madrugada no bairro em 90 dias" if n else "Sem vandalismo de madrugada no bairro"
    if grupo == "cobertura":
        d = float(x["dist_camera_m"])
        if d >= 5000:
            return "Nenhuma câmera em operação por perto"
        return (f"Sem câmera em operação a menos de {ALCANCE_CAMERA_M} m (a mais próxima está a {d:.0f} m)"
                if d > ALCANCE_CAMERA_M else f"Câmera em operação a {d:.0f} m")
    if grupo == "agentes":
        return f"{x['agentes_madrugada']:.0f} agentes em média na escala de madrugada da região"
    return f"Tipo: {NOME_TIPO.get(str(x['prefixo']), str(x['prefixo']))}" + (" (móvel)" if x["movel"] else "")


def fatores(m: ModeloP7, df: pd.DataFrame, top: int = 4) -> list[list[dict]]:
    """Mesma repartição de P1: a diferença para um equipamento típico, dividida pelos grupos na proporção do SHAP."""
    contrib, ref = m.contribuicoes(df)
    idx = {c: i for i, c in enumerate(COLUNAS)}
    z = np.column_stack([contrib[:, [idx[c] for c in cols]].sum(axis=1) for cols in GRUPOS.values()])
    nomes = list(GRUPOS)
    base_p = 1 / (1 + math.exp(-ref))
    p = m.prever(df)
    total = z.sum(axis=1)
    incl = np.where(np.abs(total) > 1e-3, (p - base_p) / np.where(np.abs(total) > 1e-3, total, 1), p * (1 - p))
    ef = z * incl[:, None]
    saida = []
    for i, x in enumerate(df[COLUNAS].to_dict("records")):
        ordem = np.argsort(-np.abs(ef[i]))[:top]
        saida.append([{"descricao": frase(nomes[j], x), "efeito": round(float(ef[i, j]), 4), "grupo": nomes[j]} for j in ordem])
    return saida


def importancia_global(m: ModeloP7, df: pd.DataFrame) -> dict[str, float]:
    contrib, _ = m.contribuicoes(df)
    idx = {c: i for i, c in enumerate(COLUNAS)}
    tot = {g: float(np.abs(contrib[:, [idx[c] for c in cols]].sum(axis=1)).mean()) for g, cols in GRUPOS.items()}
    s = sum(tot.values()) or 1
    return {g: round(v / s, 4) for g, v in sorted(tot.items(), key=lambda kv: -kv[1])}


def nivel(p: float, limites_nivel: list[float]) -> str:
    moderado, alto, muito_alto = limites_nivel
    return "MUITO_ALTO" if p >= muito_alto else "ALTO" if p >= alto else "MODERADO" if p >= moderado else "BAIXO"


def acao(niv: str, codigo: str, eid: int, dist_camera: float, regiao: str | None) -> dict:
    if niv not in ("ALTO", "MUITO_ALTO"):
        return {"texto": "Nenhuma ação extra", "tipo": "NENHUMA", "parametros": {}}
    sem_camera = dist_camera > ALCANCE_CAMERA_M
    texto = (f"Incluir {codigo} na ronda de madrugada da região {regiao or ''}".strip()
             + (" e avaliar uma câmera por perto (ver Expansão)" if sem_camera else ""))
    return {"texto": texto, "tipo": "INCLUIR_RONDA_NOTURNA",
            "parametros": {"equipamento_id": eid, "regiao": regiao, "avaliar_camera": sem_camera}}
