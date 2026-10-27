"""C2: onde instalar as próximas câmeras.

A cidade é dividida numa grade (células de 400 m). Para cada célula sem câmera em operação a menos
de 300 m, conta-se o que uma câmera no centro dela passaria a cobrir:

- ocorrências dos últimos 90 dias a menos de 300 m, ponderadas pela gravidade (por mês);
- furtos de equipamento esperados nos próximos 30 dias que a câmera evitaria: o modelo de furto (P7)
  é refeito para os equipamentos a menos de 300 m como se a câmera já estivesse lá (contrafactual).

A pontuação combina as duas coisas, cada uma em relação às melhores células da cidade (o gestor pode
escolher só uma delas). As sugestões saem da maior para a menor, com distância mínima entre elas, e
cada uma diz por quê.
É uma sugestão para o gestor avaliar no local, não uma decisão.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain import limites
from app.preditivo import artefatos, p7
from app.preditivo import variaveis as V
from app.preditivo.prever import hoje_local

ALCANCE_M = p7.ALCANCE_CAMERA_M
NOME_CATEGORIA = {
    "ACIDENTE": "acidentes", "CONGESTIONAMENTO": "congestionamentos", "ESTACIONAMENTO_IRREGULAR": "estacionamento irregular",
    "VEICULO_QUEBRADO": "veículos quebrados", "ALAGAMENTO": "alagamentos", "SEMAFORO_APAGADO": "semáforos apagados",
    "FURTO_EQUIPAMENTO": "furtos de equipamento", "VANDALISMO": "vandalismo", "PERTURBACAO": "perturbação", "OUTROS": "outros",
}
_cache: dict = {}


def _df(db: Session, sql: str, **p) -> pd.DataFrame:
    r = db.execute(text(sql), p)
    return pd.DataFrame(r.fetchall(), columns=list(r.keys()))


def _fmt(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


CRITERIOS = {"combinado": "metade ocorrências, metade furtos evitados", "ocorrencias": "só ocorrências cobertas",
             "furtos": "só furtos de equipamento evitados"}


def calcular(db: Session, f: V.Fontes | None = None, n: int | None = None, criterio: str = "combinado") -> dict:
    cfg = limites.carregar(db)
    n = n or cfg["prev_c2_sugestoes"]
    passo, dmin = cfg["prev_c2_celula_m"], cfg["prev_c2_distancia_min_m"]
    ate = db.scalar(text("SELECT max(inicio_em) FROM ocorrencia"))
    if ate is None:
        return {"sugestoes": [], "resumo": None, "mensagem": "Sem ocorrências registradas para calcular a expansão."}
    oc = _df(db, """SELECT ST_X(geom) lon, ST_Y(geom) lat, gravidade, categoria FROM ocorrencia
                    WHERE geom IS NOT NULL AND inicio_em > :a""", a=ate - timedelta(days=90))
    cam = _df(db, """SELECT ST_X(l.geom) lon, ST_Y(l.geom) lat FROM equipamento e
                     JOIN tipo_equipamento t ON t.id = e.tipo_id JOIN localizacao l ON l.equipamento_id = e.id
                     WHERE t.prefixo = 'CAM' AND e.situacao = 'operacional' AND l.geom IS NOT NULL""")
    f = f or V.carregar(db)
    bairros = f.bairros

    # Grade sobre os bairros
    xmin, ymin, xmax, ymax = shapely.union_all(bairros.geom.to_list()).bounds
    graus_x = passo / (p7._metros(np.array([1.0]), np.array([0.0]))[0][0])
    graus_y = passo / 110_540
    lons = np.arange(xmin + graus_x / 2, xmax, graus_x)
    lats = np.arange(ymin + graus_y / 2, ymax, graus_y)
    LO, LA = np.meshgrid(lons, lats)
    pts = shapely.points(LO.ravel(), LA.ravel())
    cel = pd.DataFrame({"lon": LO.ravel(), "lat": LA.ravel(), "bairro": None, "regiao": None})
    for b in bairros.itertuples():
        dentro = shapely.contains(b.geom, pts)
        cel.loc[dentro, "bairro"] = b.bairro
        cel.loc[dentro, "regiao"] = b.regiao
    cel = cel[cel.bairro.notna()].reset_index(drop=True)
    xy = p7._metros(cel.lon, cel.lat)

    # Cobertura atual
    if len(cam):
        dcam, _ = cKDTree(p7._metros(cam.lon, cam.lat)).query(xy)
    else:
        dcam = np.full(len(cel), 99_999.0)
    cel["camera_m"] = dcam

    # Ocorrências a menos do alcance
    oc_xy = p7._metros(oc.lon, oc.lat)
    arv_oc = cKDTree(oc_xy)
    perto = arv_oc.query_ball_point(xy, ALCANCE_M)
    peso = (oc.gravidade.to_numpy() / 2.0)
    cel["ocorrencias_mes"] = [len(v) / 3 for v in perto]
    cel["ponderadas_mes"] = [peso[v].sum() / 3 if v else 0.0 for v in perto]
    oc_cam = cKDTree(p7._metros(cam.lon, cam.lat)).query(oc_xy)[0] if len(cam) else np.full(len(oc), 99_999.0)
    coberta_hoje = oc_cam <= ALCANCE_M

    # Furtos evitados (contrafactual de P7)
    cel["furtos_evitados"] = 0.0
    cel["equipamentos_perto"] = 0
    mv, modelo = artefatos.ativo(db, "furto_equipamento_30d")
    if modelo is not None:
        ctx = p7.contexto(db, f)
        eq = p7.variaveis(f, ctx, [V.corte_local(hoje_local())], alvo=False)
        if len(eq):
            base = modelo.prever(eq)
            arv_eq = cKDTree(eq[["x", "y"]].to_numpy())
            for i, viz in enumerate(arv_eq.query_ball_point(xy, ALCANCE_M)):
                if not viz or cel.camera_m.iat[i] <= ALCANCE_M:
                    continue
                sub = eq.iloc[viz].copy()
                d = np.hypot(sub.x - xy[i, 0], sub.y - xy[i, 1])
                sub["dist_camera_m"] = np.minimum(sub.dist_camera_m, d)
                cel.at[i, "furtos_evitados"] = float(np.clip(base[viz] - modelo.prever(sub), 0, None).sum())
                cel.at[i, "equipamentos_perto"] = len(viz)
    sem = cel.camera_m > ALCANCE_M
    # Cada critério dividido pelo valor das 5% melhores células sem câmera (entre as que têm algum valor): os dois
    # passam a valer de 0 a cerca de 1
    def escala(v: pd.Series) -> float:
        v = v[sem & (v > 0)]
        return max(float(v.quantile(0.95)), 1e-9) if len(v) else 1.0

    esc_oc, esc_fu = escala(cel.ponderadas_mes), escala(cel.furtos_evitados)
    pesos = {"ocorrencias": (1.0, 0.0), "furtos": (0.0, 1.0)}.get(criterio, (0.5, 0.5))
    cel["pontuacao"] = 100 * (pesos[0] * cel.ponderadas_mes / esc_oc + pesos[1] * cel.furtos_evitados / esc_fu)

    cand = cel[sem].sort_values("pontuacao", ascending=False)
    topo = max(float(cand.pontuacao.max()), 1e-9) if len(cand) else 1.0
    escolhidas: list[int] = []
    for i in cand.index:
        if len(escolhidas) >= n:
            break
        if all(np.hypot(*(xy[i] - xy[j])) >= dmin for j in escolhidas):
            escolhidas.append(i)

    sugestoes, novas = [], np.zeros(len(oc), dtype=bool)
    for k, i in enumerate(escolhidas, start=1):
        c = cel.loc[i]
        viz = perto[i]
        novas[viz] = True
        cats = oc.categoria.iloc[viz].value_counts().head(3)
        top = [{"categoria": cat, "nome": NOME_CATEGORIA.get(cat, cat.lower()), "por_mes": round(q / 3, 1)} for cat, q in cats.items()]
        motivos = [f"{_fmt(c.ocorrencias_mes)} ocorrências por mês a menos de {ALCANCE_M} m, hoje sem câmera "
                   f"(a mais próxima está a {c.camera_m:.0f} m)"]
        if top:
            motivos.append("Principalmente " + ", ".join(f"{t['nome']} ({_fmt(t['por_mes'])}/mês)" for t in top))
        if c.furtos_evitados >= 0.002:
            n_eq = int(c.equipamentos_perto)
            motivos.append(f"Evitaria cerca de {_fmt(c.furtos_evitados * 12, 2)} furto de equipamento por ano entre "
                           f"{'o equipamento' if n_eq == 1 else f'os {n_eq} equipamentos'} por perto (modelo de furto refeito com a câmera)")
        sugestoes.append({
            "ordem": k, "lon": round(float(c.lon), 6), "lat": round(float(c.lat), 6), "bairro": c.bairro, "regiao": c.regiao,
            "camera_mais_proxima_m": round(float(c.camera_m)), "ocorrencias_mes": round(float(c.ocorrencias_mes), 1),
            "ponderadas_mes": round(float(c.ponderadas_mes), 1), "por_categoria": top,
            "furtos_evitados_30d": round(float(c.furtos_evitados), 3), "equipamentos_perto": int(c.equipamentos_perto),
            "furtos_evitados_ano": round(float(c.furtos_evitados * 12), 2),
            "pontuacao": round(float(c.pontuacao / topo * 100), 1), "motivos": motivos,
        })
    total = max(len(oc), 1)
    resumo = {
        "ocorrencias_90d": int(len(oc)), "cameras_operando": int(len(cam)), "alcance_m": ALCANCE_M,
        "cobertura_hoje_pct": round(float(coberta_hoje.mean() * 100), 1) if len(oc) else None,
        "cobertura_com_sugestoes_pct": round(float((coberta_hoje | novas).mean() * 100), 1) if len(oc) else None,
        "novas_cobertas_mes": round(float((novas & ~coberta_hoje).sum() / 3), 1),
        "furtos_evitados_30d": round(float(sum(s["furtos_evitados_30d"] for s in sugestoes)), 2),
        "furtos_evitados_ano": round(float(sum(s["furtos_evitados_30d"] for s in sugestoes)) * 12, 1),
        "celula_m": passo, "celulas_avaliadas": int(len(cel)), "celulas_sem_camera": int((cel.camera_m > ALCANCE_M).sum()),
        "total_ocorrencias": total,
    }
    return {
        "o_que_preve": "Onde uma câmera nova cobriria mais ocorrências e evitaria mais furtos de equipamento",
        "como_ajuda": ("Direciona o orçamento de expansão para os pontos sem cobertura com mais ocorrências e mais risco de "
                       "furto, com o motivo de cada sugestão. O gestor confere no local antes de decidir"),
        "dados_considerados": ["Ocorrências dos últimos 90 dias com local", "Câmeras em operação hoje",
                               "Risco de furto dos equipamentos (P7), refeito com a câmera nova"],
        "metodo": (f"Grade de {passo} m; alcance de {ALCANCE_M} m por câmera; pontuação de 0 a 100, a melhor célula = 100 ({CRITERIOS[criterio]}): "
                   "ocorrências por mês ponderadas pela gravidade e furtos evitados em 30 dias, cada um em relação às "
                   f"melhores células da cidade; no mínimo {dmin} m entre sugestões"),
        "criterio": criterio, "criterios": CRITERIOS,
        "sugestoes": sugestoes, "resumo": resumo, "dados_sinteticos": True,
        "modelo_furto": {"nome": mv.nome, "versao": mv.versao} if mv else None,
    }


def obter(db: Session, n: int | None = None, criterio: str = "combinado", refazer: bool = False) -> dict:
    """Em cache por dia e versão do modelo de furto (o cálculo leva alguns segundos)."""
    chave = (hoje_local().isoformat(), db.scalar(text("SELECT max(id) FROM modelo_versao WHERE nome = 'furto_equipamento_30d'")),
             db.scalar(text("SELECT count(*) FROM equipamento WHERE situacao = 'operacional'")), n, criterio)
    if refazer or _cache.get("chave") != chave:
        _cache["valor"] = calcular(db, n=n, criterio=criterio if criterio in CRITERIOS else "combinado")
        _cache["chave"] = chave
    return _cache["valor"]
