"""X3: equipamentos em fim de vida útil, onde trocar vale mais que continuar consertando.

Para cada equipamento fixo em serviço, junta o que o histórico mostra (falhas e dias parado no último
ano, idade contra a vida útil do tipo) com o que o modelo de falha (P1, 30 dias) diz: a probabilidade
de falhar como está hoje e a de um equipamento igual, novo, no mesmo lugar (contrafactual: idade de
um mês, sem falhas anteriores, preventiva em dia). A diferença é o que a troca compraria.

Recomenda trocar quando o equipamento passou da vida útil do tipo ou quando a troca reduziria muito o
risco e ele já parou bastante no último ano. É uma lista para o planejamento de compras, não uma ordem.
"""

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain import limites
from app.preditivo import artefatos
from app.preditivo import variaveis as V
from app.preditivo.prever import hoje_local

NOME_TIPO = {"CAM": "câmera", "RAD": "radar", "TOT": "totem", "BAL": "balança", "CAN": "cancela", "VIA": "sensor de via",
             "VAF": "painel"}
_cache: dict = {}


def dias_parado(f: V.Fontes, ate: pd.Timestamp, dias: int = 365) -> pd.Series:
    """Dias fora de operação (mau funcionamento ou em manutenção) no último ano, por equipamento."""
    ini = ate - pd.Timedelta(days=dias)
    h = f.historico[f.historico.em < ate].sort_values(["equipamento_id", "em"])
    h = h.assign(prox=h.groupby("equipamento_id").em.shift(-1).fillna(ate))
    fora = h[h.nova.isin(["mau_funcionamento", "em_manutencao"]) & (h.prox > ini)]
    dur = (fora.prox.clip(upper=ate) - fora.em.clip(lower=ini)).dt.total_seconds() / 86400
    return dur.groupby(fora.equipamento_id).sum()


def _fmt(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def calcular(db: Session, f: V.Fontes | None = None, limite: int = 100) -> dict:
    cfg = limites.carregar(db)
    vida = cfg["prev_x3_vida_util_anos"]
    mv, modelo = artefatos.ativo(db, "falha_equipamento_30d")
    if modelo is None:
        return {"itens": [], "resumo": None, "mensagem": "Sem modelo de falha treinado."}
    f = f or V.carregar(db)
    corte = V.corte_local(hoje_local())
    eq = V.equipamentos(f, [corte], alvo=False)
    eq = eq[~eq.movel.astype(bool)].reset_index(drop=True)
    if eq.empty:
        return {"itens": [], "resumo": None, "mensagem": "Nenhum equipamento fixo em operação."}
    atual = modelo.prever(eq)
    novo = eq.copy()
    novo["idade_dias"] = 30
    for c in ("falhas_7d", "falhas_30d", "falhas_90d", "falhas_180d"):
        novo[c] = 0
    novo["dias_desde_falha"] = np.nan
    novo["atraso_preventiva"] = -novo.periodicidade.fillna(90) / 2
    p_novo = modelo.prever(novo)
    parado = dias_parado(f, corte)
    falhas = f.historico[(f.historico.nova == "mau_funcionamento") & (f.historico.em < corte)
                         & (f.historico.em >= corte - pd.Timedelta(days=365))].groupby("equipamento_id").size()
    eq = eq.assign(p30=atual, p30_novo=p_novo, ganho=atual - p_novo, prefixo=eq.prefixo.astype(str),
                   anos=eq.idade_dias / 365.25, falhas_ano=eq.id.map(falhas).fillna(0).astype(int),
                   dias_parado=eq.id.map(parado).fillna(0.0))
    eq["vida"] = eq.prefixo.map(lambda t: float(vida.get(t, vida["padrao"])))
    eq["uso_vida"] = eq.anos / eq.vida
    passou = eq.uso_vida >= 1
    desgaste = (eq.ganho >= cfg["prev_x3_ganho_min"]) & (eq.dias_parado >= cfg["prev_x3_dias_parado_min"])
    cand = eq[passou | desgaste].copy()
    # Ordem: quanto a troca reduz o risco, mais o peso de já ter passado da vida útil e de ter ficado parado
    cand["pontuacao"] = cand.ganho * 100 + np.clip(cand.uso_vida - 0.8, 0, 1) * 10 + cand.dias_parado / 10
    cand = cand.sort_values("pontuacao", ascending=False)
    codigos = dict(db.execute(text("SELECT id, codigo_interno FROM equipamento")).all())
    itens = []
    for x in cand.head(limite).itertuples():
        motivos = []
        if x.uso_vida >= 1:
            motivos.append(f"Instalado há {_fmt(x.anos)} anos; a vida útil de {NOME_TIPO.get(x.prefixo, 'equipamento')} é de "
                           f"{x.vida:.0f} anos")
        else:
            motivos.append(f"Instalado há {_fmt(x.anos)} anos ({int(x.uso_vida * 100)}% da vida útil do tipo)")
        if x.falhas_ano:
            motivos.append(f"{x.falhas_ano} {'falha' if x.falhas_ano == 1 else 'falhas'} e {x.dias_parado:.0f} dias parado no último ano")
        motivos.append(f"Chance de falhar em 30 dias: {x.p30 * 100:.0f}% como está; {x.p30_novo * 100:.0f}% se fosse novo (modelo P1)")
        itens.append({
            "equipamento_id": int(x.id), "codigo": codigos.get(x.id, str(x.id)), "tipo": x.prefixo,
            "marca": str(x.marca).strip().title(), "modelo": str(x.modelo), "regiao": None if str(x.regiao) == "?" else str(x.regiao),
            "idade_anos": round(float(x.anos), 1), "vida_util_anos": x.vida, "uso_vida_pct": round(float(x.uso_vida) * 100),
            "falhas_ano": int(x.falhas_ano), "dias_parado_ano": round(float(x.dias_parado)),
            "p30": round(float(x.p30), 4), "p30_novo": round(float(x.p30_novo), 4), "reducao_pp": round(float(x.ganho) * 100, 1),
            "motivo_principal": "passou da vida útil" if x.uso_vida >= 1 else "desgaste: troca reduz muito o risco",
            "motivos": motivos,
        })
    por_tipo = (cand.groupby("prefixo").agg(n=("id", "size"), parado=("dias_parado", "sum")).reset_index()
                .sort_values("n", ascending=False))
    por_marca = (cand.assign(marca=cand.marca.astype(str).str.strip().str.title()).groupby(["prefixo", "marca"]).size()
                 .sort_values(ascending=False).head(5))
    return {
        "o_que_preve": "Quais equipamentos vale trocar em vez de continuar consertando",
        "como_ajuda": ("Separa o que é azar do que é desgaste: entra no planejamento de compras o equipamento que já passou "
                       "da vida útil ou que, novo, falharia bem menos no mesmo lugar"),
        "dados_considerados": ["Idade e vida útil típica do tipo", "Falhas e dias parado no último ano",
                               "Risco de falha em 30 dias (P1), como está e como se fosse novo"],
        "criterio": (f"Passou da vida útil do tipo, ou a troca reduziria o risco de falhar em 30 dias em pelo menos "
                     f"{cfg['prev_x3_ganho_min'] * 100:.0f} pontos e ele ficou {cfg['prev_x3_dias_parado_min']} dias ou mais parado no ano"),
        "resumo": {"avaliados": int(len(eq)), "recomendados": int(len(cand)), "passou_vida_util": int(passou.sum()),
                   "desgaste": int((desgaste & ~passou).sum()), "dias_parado_total": round(float(cand.dias_parado.sum())),
                   "falhas_evitaveis_mes": round(float(cand.ganho.sum()), 1),
                   "por_tipo": [{"tipo": r.prefixo, "n": int(r.n), "dias_parado": round(float(r.parado))} for r in por_tipo.itertuples()],
                   "marcas": [{"tipo": t, "marca": m, "n": int(n)} for (t, m), n in por_marca.items()]},
        "itens": itens, "modelo": {"nome": mv.nome, "versao": mv.versao}, "dados_sinteticos": True,
    }


def obter(db: Session, limite: int = 100) -> dict:
    chave = (hoje_local().isoformat(), db.scalar(text("SELECT max(id) FROM modelo_versao WHERE nome = 'falha_equipamento_30d'")), limite)
    if _cache.get("chave") != chave:
        _cache["valor"], _cache["chave"] = calcular(db, limite=limite), chave
    return _cache["valor"]
