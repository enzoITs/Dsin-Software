"""Treino e avaliação dos modelos da Parte 3.

Uso:
  python -m app.preditivo.treinar --baselines   avalia os baselines no backtest de origem móvel e grava
  python -m app.preditivo.treinar --todos       tudo o que já existe (nesta fase, só os baselines)

Cada avaliação vira uma linha em `modelo_versao` (métricas e período) e uma linha por corte em
`backtest_resultado`. O progresso fica em `estado_preditivo` ("treino"), para a interface mostrar.
"""

import argparse
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.domain import limites
from app.models import BacktestResultado, EstadoPreditivo, ModeloVersao
from app.preditivo import backtest
from app.preditivo import variaveis as V


def fim_dos_dados(db: Session) -> date:
    """Último dia completo com dados: a meia-noite até onde o histórico (ou o modo contínuo) chegou."""
    c = db.get(EstadoPreditivo, "continuo")
    ate = datetime.fromisoformat(c.valor["ate"]) if c else datetime.now(timezone.utc)
    return ate.astimezone(V.corte_local(date.today()).tzinfo).date()


def progresso(db: Session, **valores) -> None:
    atual = db.get(EstadoPreditivo, "treino")
    base = dict(atual.valor) if atual else {}
    base.update(valores, atualizado_em=datetime.now(timezone.utc).isoformat())
    db.merge(EstadoPreditivo(chave="treino", valor=backtest.json_limpo(base)))
    db.commit()


def registrar(db: Session, *, nome: str, modulo: str, fim: date, inicio: date | None, metricas: dict,
              metricas_baseline: dict, por_corte: list[dict], parametros: dict, artefato: str | None = None) -> ModeloVersao:
    """Grava uma versão nova (ativa) e desativa as anteriores com o mesmo nome."""
    n = db.scalar(select(func.count()).select_from(ModeloVersao).where(
        ModeloVersao.nome == nome, ModeloVersao.versao.like(f"{fim.isoformat()}.%"))) or 0
    db.execute(update(ModeloVersao).where(ModeloVersao.nome == nome).values(ativo=False))
    mv = ModeloVersao(nome=nome, versao=f"{fim.isoformat()}.{n + 1}", treino_inicio=inicio, treino_fim=fim,
                      parametros=backtest.json_limpo({"modulo": modulo, **parametros}),
                      metricas=backtest.json_limpo(metricas), metricas_baseline=backtest.json_limpo(metricas_baseline),
                      caminho_artefato=artefato, ativo=True)
    db.add(mv)
    db.flush()
    for c in por_corte:
        c = dict(c)
        d = c.pop("data_corte")
        db.add(BacktestResultado(modulo=modulo, modelo_versao_id=mv.id, data_corte=d, metricas=backtest.json_limpo(c)))
    db.commit()
    return mv


def baselines(db: Session, f: V.Fontes | None = None, log=print) -> dict:
    cfg = limites.carregar(db, forcar=True)
    fim = fim_dos_dados(db)
    f = f or V.carregar(db)
    params = {k: v for k, v in cfg.items() if k.startswith("prev_")}
    inicio_bt = fim - timedelta(days=cfg["prev_backtest_dias"])
    saida = {}

    for janela in (7, 30):
        progresso(db, etapa=f"Baseline P1 ({janela} dias)")
        r = backtest.p1_baseline(f, fim, cfg, janela)
        registrar(db, nome=f"baseline_falha_{janela}d", modulo="P1", fim=fim, inicio=inicio_bt,
                  metricas=r["geral"], metricas_baseline=r["geral"], por_corte=r["por_corte"],
                  parametros={**params, "metodo": "taxa histórica de falha do tipo", "janela_dias": janela})
        saida[f"P1_{janela}d"] = r["geral"]
        g = r["geral"]
        log(f"[treino] baseline P1 {janela} d: AUC {g['auc']:.3f}, Brier {g['brier']:.4f}, "
            f"precisão nos 50 primeiros {g['precisao_50']:.1%} (taxa base {g['taxa_base']:.1%})")

    progresso(db, etapa="Baseline P2 (sazonal ingênuo)")
    r = backtest.p2_baseline(f, fim, cfg)
    registrar(db, nome="baseline_ocorrencias", modulo="P2", fim=fim, inicio=inicio_bt, metricas=r["geral"],
              metricas_baseline=r["geral"], por_corte=r["por_corte"],
              parametros={**params, "metodo": f"média da mesma hora e dia da semana em {cfg['prev_p2_semanas_baseline']} semanas"})
    saida["P2"] = r["geral"]
    g = r["geral"]
    log(f"[treino] baseline P2: MAE por região e hora {g['mae']:.3f} (média real {g['real_medio']:.2f}), "
        f"erro {g['erro_pct']:.1f}%, MAE no pico {g['mae_pico']:.3f}")

    progresso(db, etapa="Baseline P6 (média móvel)")
    r = backtest.p6_baseline(f, fim, cfg)
    registrar(db, nome="baseline_disponibilidade_30d", modulo="P6", fim=fim, inicio=inicio_bt, metricas=r["geral"],
              metricas_baseline=r["geral"], por_corte=r["por_corte"],
              parametros={**params, "metodo": f"última média móvel de {cfg['prev_p6_media_dias']} dias", "horizonte_dias": 30})
    saida["P6"] = r["geral"]
    log(f"[treino] baseline P6 (30 dias): erro médio {r['geral']['mae_pp']:.2f} pontos percentuais")
    return saida


def treinar(todos: bool = True, so_baselines: bool = False, log=print) -> dict:
    t0 = time.time()
    with SessionLocal() as db:
        progresso(db, situacao="rodando", etapa="Carregando dados", inicio=datetime.now(timezone.utc).isoformat(),
                  mensagem=None)
        try:
            f = V.carregar(db)
            res = {"baselines": baselines(db, f, log)}
            progresso(db, situacao="pronto", etapa="Concluído", segundos=round(time.time() - t0, 1))
        except Exception as exc:
            db.rollback()
            progresso(db, situacao="erro", mensagem=f"{type(exc).__name__}: {exc}")
            raise
    log(f"[treino] concluído em {time.time() - t0:.1f}s")
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--todos", action="store_true", help="avalia e treina tudo o que existe")
    ap.add_argument("--baselines", action="store_true", help="só os baselines")
    args = ap.parse_args()
    treinar(todos=args.todos or not args.baselines, so_baselines=args.baselines)


if __name__ == "__main__":
    main()
