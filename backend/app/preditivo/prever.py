"""Previsões em lote, gravadas na tabela `previsao` para a API só ler.

Cada linha já traz tudo o que o Cartão de Previsão mostra: o que se prevê, com que dados, os
fatores, como ajuda, a ação recomendada e a qualidade do modelo contra o baseline.
"""

from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import delete, insert, text
from sqlalchemy.orm import Session

from app.domain import limites
from app.models import Previsao
from app.preditivo import artefatos, avaliacao, p1
from app.preditivo import variaveis as V


def hoje_local(agora: datetime | None = None) -> date:
    agora = agora or datetime.now(timezone.utc)
    return pd.Timestamp(agora).tz_convert(V.FUSO).date()


def qualidade(mv, metrica: str, menor_melhor: bool, cfg: dict) -> dict:
    m, b = (mv.metricas or {}).get(metrica), (mv.metricas_baseline or {}).get(metrica)
    return {"metrica": metrica.upper() if metrica == "auc" else metrica, "modelo": m, "baseline": b,
            "ganho_pct": avaliacao.ganho(m, b, menor_melhor), "avaliado_em": f"backtest de {cfg['prev_backtest_dias']} dias"}


def prever_p1(db: Session, f: V.Fontes | None = None, agora: datetime | None = None) -> int:
    """Probabilidade de falha em 7 e 30 dias de cada equipamento em operação, a partir da meia-noite de hoje."""
    cfg = limites.carregar(db, forcar=True)
    hoje = hoje_local(agora)
    corte = V.corte_local(hoje)
    f = f or V.carregar(db)
    linhas = V.equipamentos(f, [corte], alvo=False)
    if linhas.empty:
        return 0
    codigos = dict(db.execute(text("SELECT id, codigo_interno FROM equipamento")).all())
    reg_ids = dict(zip(f.bairros.regiao, f.bairros.regiao_id))
    total = 0
    for janela in (7, 30):
        mv, modelo = artefatos.ativo(db, f"falha_equipamento_{janela}d")
        if modelo is None:
            continue
        prob = modelo.prever(linhas)
        fat = p1.fatores(modelo, linhas)
        q = qualidade(mv, "auc", False, cfg)
        fim = corte + pd.Timedelta(days=janela)
        db.execute(delete(Previsao).where(Previsao.modulo == "P1", Previsao.horizonte_inicio == corte.to_pydatetime(),
                                          Previsao.horizonte_fim == fim.to_pydatetime()))
        valores = []
        for x, p, fs in zip(linhas.itertuples(), prob, fat):
            p = float(p)
            niv = p1.nivel(p, cfg["prev_p1_limites_nivel" if janela == 7 else "prev_p1_limites_nivel_30d"])
            lo, hi = p1.faixa(p)
            cod = codigos.get(x.id, str(x.id))
            regiao = str(x.regiao) if str(x.regiao) != "?" else None
            valores.append({
                "modulo": "P1", "alvo_tipo": "equipamento", "alvo_id": int(x.id), "regiao_id": reg_ids.get(regiao),
                "horizonte_inicio": corte.to_pydatetime(), "horizonte_fim": fim.to_pydatetime(), "valor": p,
                "faixa_inferior": lo, "faixa_superior": hi, "nivel": niv, "fatores": fs,
                "dados_considerados": p1.DADOS_CONSIDERADOS, "modelo_versao_id": mv.id,
                "detalhe": {
                    "o_que_preve": f"Probabilidade de falha de {cod} nos próximos {janela} dias",
                    "alvo": {"tipo": "equipamento", "id": int(x.id), "nome": cod, "regiao": regiao, "tipo_equipamento": str(x.prefixo)},
                    "como_ajuda": p1.COMO_AJUDA.get(str(x.prefixo), "Antecipar a manutenção evita que o equipamento pare quando mais se precisa dele"),
                    "acao_recomendada": p1.acao(p, niv, str(x.prefixo), cod, int(x.id), hoje),
                    "qualidade_do_modelo": q, "modelo": {"nome": mv.nome, "versao": mv.versao}, "janela_dias": janela,
                },
            })
        for i in range(0, len(valores), 5000):
            db.execute(insert(Previsao), valores[i:i + 5000])
        total += len(valores)
    db.commit()
    return total
