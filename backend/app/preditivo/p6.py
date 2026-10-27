"""P6: tendência de disponibilidade dos equipamentos fixos, 30 e 90 dias à frente.

- Série: disponibilidade (operacionais ÷ em serviço) à meia-noite de cada dia, por região, pela cidade
  inteira e por tipo de equipamento (na cidade).
- Modelo: suavização exponencial (ETS) com tendência amortecida sobre as médias semanais das últimas
  52 semanas. A média semanal tira o ruído do dia a dia; a tendência amortecida segue uma queda lenta
  sem projetá-la para sempre.
- Baseline: última média móvel de 30 dias (`baselines.p6_prever`).
- Faixa de 90%: erro absoluto do próprio modelo no backtest (conformal), em 30 e 90 dias, interpolado
  para os dias intermediários.
- Cenários: "se nada mudar" (a previsão) e "seguindo P1" (as preventivas recomendadas pelo P1 para os
  equipamentos de risco alto são feitas: parte das falhas esperadas não acontece e cada uma deixa de
  tirar o equipamento de serviço pelo tempo médio de conserto da região).
"""

import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from app.preditivo import avaliacao, backtest, baselines
from app.preditivo import variaveis as V

SEMANAS = 52
HORIZONTES = (30, 90)
DIAS_HISTORICO = 365 + 7
DADOS_CONSIDERADOS = [
    "Disponibilidade diária dos equipamentos fixos nas últimas 52 semanas",
    "Falhas esperadas pelo risco de falha (P1) dos equipamentos de risco alto",
    "Tempo médio de conserto nos últimos 90 dias",
    "Manutenções preventivas atrasadas",
]
COMO_AJUDA = ("Mostra semanas antes se a disponibilidade vai cair abaixo da meta, enquanto ainda dá para "
              "priorizar manutenções e evitar a queda, em vez de descobrir no relatório do mês")


def semanal(diaria: np.ndarray) -> np.ndarray:
    """Médias de 7 em 7 dias, alinhadas no fim (a última semana termina no último dia observado)."""
    n = min(SEMANAS, len(diaria) // 7) * 7
    return diaria[len(diaria) - n:].reshape(-1, 7).mean(axis=1)


def prever_serie(diaria: np.ndarray, dias: int) -> np.ndarray:
    """Previsão diária (dia 1 a `dias` depois do último observado) a partir da série diária até o corte."""
    sem = semanal(np.asarray(diaria, dtype=float))
    passos = int(np.ceil(dias / 7)) + 1
    if len(sem) < 8 or np.allclose(sem, sem[0]):
        fut = np.full(passos, sem[-1] if len(sem) else np.nan)
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fut = ExponentialSmoothing(sem, trend="add", damped_trend=True).fit().forecast(passos)
    # Centro de cada semana: a última observada está em -3 (dias); a semana k prevista, em 7k - 3
    centros = np.concatenate([[-3.0], 7 * np.arange(1, passos + 1) - 3.0])
    valores = np.concatenate([[sem[-1]], fut])
    return np.clip(np.interp(np.arange(1, dias + 1), centros, valores), 0, 1)


def _ate(serie: pd.DataFrame, grupo: str, corte: date) -> np.ndarray:
    x = serie[(serie.regiao == grupo) & (serie.dia < corte)].sort_values("dia")
    return x.disponibilidade.to_numpy()[-DIAS_HISTORICO:]


def avaliar(serie: pd.DataFrame, fim: date, cfg: dict) -> dict:
    """Backtest de origem móvel em 30 e 90 dias, modelo × baseline, por região e na cidade."""
    passo = cfg["prev_backtest_passo_dias"]
    grupos = sorted(serie.regiao.unique())
    saida: dict = {"por_corte": [], "q90": {}, "por_regiao": {}}
    for h in HORIZONTES:
        datas = backtest.cortes(fim, cfg["prev_backtest_dias"] + h, passo, h)
        linhas = []
        for d in datas:
            real = serie[serie.dia == d + timedelta(days=h - 1)].set_index("regiao").disponibilidade
            base = baselines.p6_prever(serie, d, h, cfg["prev_p6_media_dias"]).set_index("regiao").previsto
            m_err, b_err = [], []
            for g in grupos:
                x = _ate(serie, g, d)
                if g not in real.index or len(x) < 60 or pd.isna(real[g]):
                    continue
                prev = float(prever_serie(x, h)[-1])
                linhas.append({"regiao": g, "real": real[g], "modelo": prev, "baseline": base.get(g, np.nan)})
                m_err.append(abs(prev - real[g]))
                b_err.append(abs(base.get(g, np.nan) - real[g]))
            if h == 30 and m_err:
                saida["por_corte"].append({"data_corte": d, "mae_pp": float(np.mean(m_err) * 100),
                                           "mae_pp_baseline": float(np.nanmean(b_err) * 100), "n": len(m_err)})
        df = pd.DataFrame(linhas)
        if df.empty:
            continue
        sufixo = "" if h == 30 else f"_{h}"
        saida.setdefault("modelo", {}).update({f"mae_pp{sufixo}": avaliacao.serie(df.real, df.modelo)["mae_pp"], f"n{sufixo}": len(df)})
        saida.setdefault("baseline", {}).update({f"mae_pp{sufixo}": avaliacao.serie(df.real, df.baseline)["mae_pp"],
                                                 f"n{sufixo}": len(df)})
        saida["q90"][h] = float(np.quantile(np.abs(df.modelo - df.real), 0.9))
        for g, x in df.groupby("regiao"):
            r = saida["por_regiao"].setdefault(g, {})
            r[f"modelo{sufixo}"] = float((x.modelo - x.real).abs().mean() * 100)
            r[f"baseline{sufixo}"] = float((x.baseline - x.real).abs().mean() * 100)
    return saida


def faixa(q90: dict, dias: int) -> np.ndarray:
    """Meia largura da faixa de 90% em cada dia: zero hoje, o erro do backtest em 30 e 90 dias, interpolado."""
    pts_x = [0, 30, 90]
    pts_y = [0.0, float(q90.get(30, q90.get("30", 0.01))), float(q90.get(90, q90.get("90", 0.02)))]
    return np.interp(np.arange(1, dias + 1), pts_x, pts_y)


def ganho_seguindo_p1(evitadas_mes: float, dias_conserto: float, em_servico: int, dias: int) -> np.ndarray:
    """Pontos de disponibilidade (fração) ganhos em cada dia se as falhas evitáveis não acontecerem.

    Falhas evitadas por dia × dias que cada uma deixaria o equipamento parado, com rampa: no dia d,
    só as falhas dos últimos min(d, conserto) dias ainda estariam fora de serviço.
    """
    if em_servico <= 0:
        return np.zeros(dias)
    taxa = evitadas_mes / 30
    return taxa * np.minimum(np.arange(1, dias + 1), max(dias_conserto, 1)) / em_servico


def nivel(previsto: float, atual: float, meta: float) -> str:
    if previsto < meta:
        return "ABAIXO_META"
    if previsto < meta + 0.01 or previsto < atual - 0.01:
        return "ATENCAO"
    return "NORMAL"


def _pp(v: float) -> str:
    return f"{v * 100:+.1f}".replace(".", ",")


def fatores(atual: float, previsto: float, risco_alto: int, ganho_p1: float, atrasadas: int, conserto: float,
            conserto_cidade: float) -> list[dict]:
    """Por que a previsão é essa. Só a tendência move o número (é o que o modelo projeta); os outros fatores são o
    contexto que explica a tendência e o que daria para mudar (efeito zero nas barras)."""
    t = previsto - atual
    saida = [{"descricao": (f"Tendência das últimas semanas: {_pp(t)} pontos até o horizonte" if abs(t) >= 0.001
                            else "Disponibilidade estável nas últimas semanas"), "efeito": round(t * 100, 2), "grupo": "tendencia"}]
    if risco_alto:
        txt = f"{risco_alto} equipamentos com risco alto de falha em 30 dias (P1)"
        if ganho_p1 >= 0.0005:
            txt += f"; as preventivas recomendadas recuperariam {_pp(ganho_p1)[1:]} ponto"
        saida.append({"descricao": txt, "efeito": 0.0, "grupo": "risco_p1"})
    if atrasadas:
        saida.append({"descricao": f"{atrasadas} manutenções preventivas atrasadas", "efeito": 0.0, "grupo": "preventivas"})
    if conserto:
        dif = conserto - conserto_cidade
        txt = (f"Conserto leva em média {conserto:.0f} dias (cidade: {conserto_cidade:.0f})" if abs(dif) >= 1
               else f"Conserto leva em média {conserto:.0f} dias, como na cidade")
        saida.append({"descricao": txt, "efeito": 0.0, "grupo": "conserto"})
    return saida


def dias_conserto(f: V.Fontes, ate: pd.Timestamp, dias: int = 90, por: str = "regiao") -> dict[str, float]:
    """Dias médios entre entrar em mau funcionamento e voltar a operar, nas falhas que voltaram nos últimos `dias`."""
    h = f.historico.sort_values("em")
    h = h[h.em < ate]
    falha = h[h.nova == "mau_funcionamento"][["equipamento_id", "em"]].rename(columns={"em": "falhou"})
    volta = h[h.nova == "operacional"][["equipamento_id", "em"]].rename(columns={"em": "voltou"})
    volta = volta[volta.voltou >= ate - pd.Timedelta(days=dias)]
    if falha.empty or volta.empty:
        return {}
    x = pd.merge_asof(volta.sort_values("voltou"), falha.sort_values("falhou"), left_on="voltou", right_on="falhou",
                      by="equipamento_id", direction="backward").dropna()
    x["dias"] = ((x.voltou - x.falhou).dt.total_seconds() / 86400).clip(upper=60)
    eq = f.equipamentos[~f.equipamentos.movel][["id", por]]
    x = x.merge(eq, left_on="equipamento_id", right_on="id")
    saida = {str(k): float(v) for k, v in x.groupby(por).dias.mean().items()}
    saida["Cidade"] = float(x.dias.mean()) if len(x) else 0.0
    return saida
