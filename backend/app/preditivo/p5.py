"""P5: detecção de anomalias.

- Equipamento: para cada série por hora (infrações de radar, minutos online de câmera), uma
  decomposição sazonal robusta (STL, período de 24 h) na janela de referência (60 a 3 dias atrás)
  dá o nível e o padrão do dia (medianas) e a dispersão normal dos resíduos. Nas últimas 72 h, o escore
  robusto (observado − esperado) ÷ dispersão aponta:
    * queda sustentada: escore das últimas 24 h somadas ≤ −4 e menos da metade do esperado;
    * queda recorrente: horas com escore ≤ −4 no mesmo horário em dias diferentes ("cai toda noite").
  Um Isolation Forest sobre o perfil diário (forma das 24 h, volume do dia e horas abaixo do normal)
  de todos os equipamentos da mesma métrica dá uma segunda opinião, mostrada junto da anomalia.
- Região: ocorrências observadas acima do limite superior do intervalo de P2 por N horas seguidas.
- Operação: fora do plano enxuto (Fase 0).

Toda anomalia leva o gráfico esperado × observado com a faixa normal.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from statsmodels.tsa.seasonal import STL

FUSO = "America/Sao_Paulo"
DIAS_REFERENCIA = 60
DIAS_RECENTES = 3
Z_QUEDA_24H = -4.0
RAZAO_QUEDA = 0.5
Z_FORA = -4.0


def _mad(x: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def esperado(serie: pd.Series, agora: pd.Timestamp, metrica: str) -> tuple[pd.DataFrame, dict] | None:
    """Esperado, faixa e escore das últimas 72 h a partir da STL na janela de referência."""
    serie = serie.sort_index()
    ref = serie[(serie.index >= agora - pd.Timedelta(days=DIAS_REFERENCIA)) & (serie.index < agora - pd.Timedelta(days=DIAS_RECENTES))]
    rec = serie[(serie.index >= agora - pd.Timedelta(days=DIAS_RECENTES)) & (serie.index < agora)]
    if len(ref) < 7 * 24 or len(rec) < 24:
        return None
    ref = ref.asfreq("h").interpolate().ffill().bfill()
    stl = STL(ref.to_numpy(dtype=float), period=24, robust=True).fit()
    # Medianas sobre toda a referência: uma mudança só vira "o novo normal" se ocupar mais da metade dela.
    nivel = float(np.median(stl.trend))
    horas_ref = ref.index.tz_convert(FUSO).hour
    sazonal = pd.Series(stl.seasonal, index=horas_ref).groupby(level=0).median()
    horas = rec.index.tz_convert(FUSO).hour
    esp = np.maximum(nivel + sazonal.reindex(horas).fillna(0).to_numpy(), 0)
    disp = max(_mad(stl.resid), 1e-6)
    escala = np.maximum(disp, np.sqrt(np.maximum(esp, 1))) if metrica == "infracoes" else np.maximum(disp, 2.0)
    obs = rec.to_numpy(dtype=float)
    df = pd.DataFrame({"em": rec.index, "hora": horas, "observado": obs, "esperado": esp, "escala": escala,
                       "inferior": np.maximum(esp - 3 * escala, 0), "superior": esp + 3 * escala,
                       "z": (obs - esp) / escala})
    return df, {"nivel": nivel, "dispersao": disp}


def detectar_serie(serie: pd.Series, agora: pd.Timestamp, metrica: str) -> dict | None:
    """Anomalia de uma série (ou None)."""
    r = esperado(serie, agora, metrica)
    if r is None:
        return None
    df, info = r
    ult = df.tail(24)
    razao = float(ult.observado.sum() / max(ult.esperado.sum(), 1e-6))
    z24 = float((ult.observado.sum() - ult.esperado.sum()) / np.sqrt((ult.escala**2).sum()))
    grafico = [{"em": x.em.isoformat(), "observado": round(x.observado, 2), "esperado": round(x.esperado, 2),
                "inferior": round(x.inferior, 2), "superior": round(x.superior, 2)} for x in df.itertuples()]
    if z24 <= Z_QUEDA_24H and razao < RAZAO_QUEDA:
        return {"tipo": "queda", "razao": razao, "z": z24, "grafico": grafico}
    fora = df[(df.z <= Z_FORA) & (df.observado < 0.5 * df.esperado)]
    if len(fora):
        dias = fora.em.dt.tz_convert(FUSO).dt.date
        por_hora = fora.groupby("hora").apply(lambda x: x.em.dt.tz_convert(FUSO).dt.date.nunique(), include_groups=False)
        repetidas = sorted(int(h) for h in por_hora[por_hora >= 2].index)
        if len(repetidas) >= 2 and dias.nunique() >= 2:
            return {"tipo": "queda_recorrente", "horas": repetidas, "dias": int(dias.nunique()), "razao": razao,
                    "z": float(fora.z.min()), "grafico": grafico}
    return None


def perfil_diario(series: dict, agora: pd.Timestamp) -> pd.DataFrame:
    """Uma linha por equipamento e dia: forma das 24 h (fração de cada hora), volume relativo à mediana do
    equipamento e quantas horas ficaram abaixo da metade do normal daquela hora."""
    linhas = []
    for chave, s in series.items():
        s = s[(s.index >= agora - pd.Timedelta(days=DIAS_REFERENCIA)) & (s.index < agora)]
        if s.empty:
            continue
        local = s.copy()
        local.index = s.index.tz_convert(FUSO)
        tab = local.groupby([local.index.date, local.index.hour]).sum().unstack(fill_value=0)
        tab = tab.reindex(columns=range(24), fill_value=0)
        tot = tab.sum(axis=1)
        med = float(tot.median()) or 1.0
        normal_hora = tab.median(axis=0)                      # valor típico de cada hora para este equipamento
        baixas = (tab < 0.5 * normal_hora).where(normal_hora > 0, False).sum(axis=1)
        forma = tab.div(tot.replace(0, 1), axis=0)
        for dia, f in forma.iterrows():
            linhas.append({"chave": chave, "dia": dia, "volume": float(np.log1p(tot[dia]) - np.log1p(med)),
                           "horas_baixas": int(baixas[dia]), **{f"h{h}": f[h] for h in range(24)}})
    return pd.DataFrame(linhas)


def isolation_forest(series: dict, agora: pd.Timestamp) -> dict:
    """Escore do Isolation Forest (mais negativo = mais estranho) dos dias recentes, por série.

    Treina nos dias de referência de todas as séries da métrica; marca como atípico o dia recente
    mais estranho que 95% dos dias de referência. É evidência complementar: a decisão de abrir a
    anomalia é da STL, porque o Isolation Forest isola qualquer dia diferente (até uma queda isolada
    de uma hora) e não mede a intensidade da mudança.
    """
    df = perfil_diario(series, agora)
    if df.empty:
        return {}
    limite_dia = (agora - pd.Timedelta(days=DIAS_RECENTES)).tz_convert(FUSO).date()
    cols = ["volume", "horas_baixas"] + [f"h{h}" for h in range(24)]
    ref, rec = df[df.dia < limite_dia], df[df.dia >= limite_dia]
    if len(ref) < 50 or rec.empty:
        return {}
    modelo = IsolationForest(n_estimators=200, random_state=42).fit(ref[cols])
    corte = float(np.quantile(modelo.score_samples(ref[cols]), 0.05))
    rec = rec.assign(score=modelo.score_samples(rec[cols]))
    saida = {}
    for chave, x in rec.groupby("chave"):
        saida[chave] = {"score_min": round(float(x.score.min()), 4), "limite": round(corte, 4),
                        "dias_atipicos": int((x.score < corte).sum())}
    return saida


def detectar_regiao(observado: pd.Series, previsto: pd.Series, superior: pd.Series, horas_seguidas: int) -> dict | None:
    """Observado acima do limite superior de P2 nas últimas `horas_seguidas` horas (séries alinhadas por hora)."""
    df = pd.DataFrame({"observado": observado, "previsto": previsto, "superior": superior}).dropna().sort_index()
    if len(df) < horas_seguidas:
        return None
    ult = df.tail(horas_seguidas)
    if (ult.observado > ult.superior).all():
        grafico = [{"em": em.isoformat(), "observado": float(x.observado), "esperado": round(float(x.previsto), 2),
                    "inferior": 0.0, "superior": round(float(x.superior), 2)} for em, x in df.tail(24).iterrows()]
        return {"tipo": "acima_do_previsto", "horas": horas_seguidas, "observado": float(ult.observado.sum()),
                "previsto": float(ult.previsto.sum()), "superior": float(ult.superior.sum()), "grafico": grafico}
    return None


def descrever(codigo: str, metrica: str, d: dict) -> str:
    if d["tipo"] == "queda":
        coisa = "infrações registradas" if metrica == "infracoes" else "tempo online"
        return f"{codigo}: {100 * (1 - d['razao']):.0f}% menos {coisa} que o esperado nas últimas 24 h"
    if d["tipo"] == "queda_recorrente":
        h = d["horas"]
        faixa = f"entre {h[0]} h e {h[-1] + 1} h" if h == list(range(h[0], h[-1] + 1)) else "em " + ", ".join(f"{x} h" for x in h)
        o_que = "fora do ar" if metrica == "online_min" else "sem registrar infrações"
        return f"{codigo}: {o_que} todos os dias {faixa} ({d['dias']} dias seguidos)"
    return f"{codigo}: perfil diário fora do padrão"

