"""Treino e avaliação dos modelos da Parte 3.

Uso:
  python -m app.preditivo.treinar --baselines   avalia os baselines no backtest de origem móvel e grava
  python -m app.preditivo.treinar --todos       baselines, P1 (risco de falha), P2 (ocorrências), P3 (índice), P4 (equipes),
                                                P6 (disponibilidade), P7 (furto), P8 (carga de manutenção) e as previsões em lote

Cada avaliação vira uma linha em `modelo_versao` (métricas e período) e uma linha por corte em
`backtest_resultado`. O progresso fica em `estado_preditivo` ("treino"), para a interface mostrar.
"""

import argparse
import os
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.domain import limites
from app.models import BacktestResultado, EstadoPreditivo, ModeloVersao
from app.preditivo import artefatos, backtest, diarias, p1, p2, p6, p7, planejamento, prever
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


def treinar_p1(db: Session, f: V.Fontes, log=print) -> dict:
    """Backtest, modelo final (treinado até hoje), artefato e registro, para 7 e 30 dias."""
    cfg = limites.carregar(db, forcar=True)
    fim = fim_dos_dados(db)
    saida = {}
    for janela in (7, 30):
        progresso(db, etapa=f"P1: backtest ({janela} dias)")
        df = p1.dados(f, fim, cfg, janela)
        r = p1.avaliar(f, df, fim, cfg, janela, log=lambda m: None)
        progresso(db, etapa=f"P1: modelo final ({janela} dias)")
        recente = df[df.corte > V.corte_local(fim) - pd.Timedelta(weeks=cfg["prev_treino_semanas"])]
        modelo = p1.ajustar(recente, janela)
        modelo.calibracao_backtest = r["modelo"]["calibracao"]
        metricas = {**r["modelo"], "logistica": r["logistica"],
                    "importancia": p1.importancia_global(modelo, recente.sample(min(len(recente), 20_000), random_state=0))}
        nome = f"falha_equipamento_{janela}d"
        mv = registrar(db, nome=nome, modulo="P1", fim=fim, inicio=modelo.treino_cortes[0], metricas=metricas,
                       metricas_baseline=r["baseline"], por_corte=r["por_corte"],
                       parametros={"lgbm": p1.PARAMS_LGBM, "calibracao": "isotônica", "janela_dias": janela,
                                   "variaveis": p1.COLUNAS, "linhas_treino": len(recente)})
        mv.caminho_artefato = artefatos.salvar(modelo, nome, mv.versao)
        db.commit()
        m, b, lg = r["modelo"], r["baseline"], r["logistica"]
        log(f"[treino] P1 {janela} d: AUC {m['auc']:.3f} (baseline {b['auc']:.3f}, logística {lg['auc']:.3f}); "
            f"Brier {m['brier']:.4f} (baseline {b['brier']:.4f}); precisão nos 50 primeiros {m['precisao_50']:.1%} "
            f"(baseline {b['precisao_50']:.1%})")
        saida[f"P1_{janela}d"] = {"modelo": {k: v for k, v in m.items() if k != "calibracao"},
                                  "baseline": {k: v for k, v in b.items() if k != "calibracao"}}
        if janela == 30:
            r8 = diarias.avaliar_p8(r["previsoes"])
            registrar(db, nome="carga_manutencao", modulo="P8", fim=fim, inicio=modelo.treino_cortes[0], metricas=r8["modelo"],
                      metricas_baseline=r8["baseline"], por_corte=r8["por_corte"],
                      parametros={"metodo": "soma das probabilidades de falha de P1 por tipo e região, mais as preventivas do plano",
                                  "horas": {k: v for k, v in cfg.items() if k.startswith("prev_p8_")}})
            log(f"[treino] P8: falhas em 30 dias por tipo e região, erro médio {r8['modelo']['mae']:.2f} "
                f"(média histórica do tipo {r8['baseline']['mae']:.2f})")
            saida["P8"] = r8["modelo"]
    return saida


def treinar_p2(db: Session, f: V.Fontes, log=print) -> dict:
    """Backtest, modelo final, artefato e registro de P2 (o índice P3 usa o P2 e não tem modelo próprio)."""
    cfg = limites.carregar(db, forcar=True)
    fim = fim_dos_dados(db)
    progresso(db, etapa="P2: variáveis por bairro e hora")
    df = p2.dados(f, fim, cfg)
    progresso(db, etapa="P2: backtest")
    r = p2.avaliar(df, fim, cfg, log=lambda m: None)
    progresso(db, etapa="P2: modelo final")
    recente = df[df.origem > V.corte_local(fim) - pd.Timedelta(days=cfg["prev_treino_origens_dias"])]
    modelo = p2.ajustar(recente)
    m, b = r["modelo"], r["baseline"]
    metricas = {**m, "importancia": p2.importancia_global(modelo, recente.sample(min(len(recente), 30_000), random_state=0)),
                "q_conformal": modelo.q}
    mv = registrar(db, nome="ocorrencias_regiao_hora", modulo="P2", fim=fim, inicio=modelo.treino_origens[0], metricas=metricas,
                   metricas_baseline=b, por_corte=r["por_corte"],
                   parametros={"lgbm": p2.PARAMS_LGBM, "intervalo": "conformal normalizado, 90%", "variaveis": p2.COLUNAS,
                               "linhas_treino": len(recente)})
    mv.caminho_artefato = artefatos.salvar(modelo, mv.nome, mv.versao)
    db.commit()
    log(f"[treino] P2: MAE por região e hora {m['mae']:.3f} (baseline {b['mae']:.3f}); erro {m['erro_pct']:.1f}% "
        f"(baseline {b['erro_pct']:.1f}%); pico {m['mae_pico']:.3f} (baseline {b['mae_pico']:.3f}); "
        f"cobertura do intervalo de 90%: {m['cobertura_90']:.0%}")
    return {"modelo": {k: v for k, v in m.items() if k != "por_regiao"}, "baseline": {k: v for k, v in b.items() if k != "por_regiao"}}


def treinar_p6(db: Session, f: V.Fontes, log=print) -> dict:
    """Backtest do ETS de disponibilidade (30 e 90 dias). Não há artefato: o ETS é ajustado na hora da previsão."""
    cfg = limites.carregar(db, forcar=True)
    fim = fim_dos_dados(db)
    progresso(db, etapa="P6: tendência de disponibilidade")
    serie = V.disponibilidade_diaria(f, fim - timedelta(days=cfg["prev_backtest_dias"] + 90 + p6.DIAS_HISTORICO), fim)
    r = p6.avaliar(serie, fim, cfg)
    m, b = r["modelo"], r["baseline"]
    registrar(db, nome="disponibilidade_regiao", modulo="P6", fim=fim, inicio=fim - timedelta(days=p6.DIAS_HISTORICO),
              metricas={**m, "q90": r["q90"], "por_regiao": r["por_regiao"]}, metricas_baseline=b, por_corte=r["por_corte"],
              parametros={"metodo": "ETS com tendência amortecida sobre médias semanais", "semanas": p6.SEMANAS,
                          "horizontes_dias": list(p6.HORIZONTES)})
    log(f"[treino] P6: erro médio em 30 dias {m['mae_pp']:.2f} pp (baseline {b['mae_pp']:.2f}); "
        f"em 90 dias {m['mae_pp_90']:.2f} pp (baseline {b['mae_pp_90']:.2f})")
    return {"modelo": m, "baseline": b}


def treinar_p7(db: Session, f: V.Fontes, log=print) -> dict:
    cfg = limites.carregar(db, forcar=True)
    fim = fim_dos_dados(db)
    progresso(db, etapa="P7: variáveis de furto")
    ctx = p7.contexto(db, f)
    df = p7.variaveis(f, ctx, p7.cortes_treino(fim, cfg))
    progresso(db, etapa="P7: backtest")
    r = p7.avaliar(f, ctx, df, fim, cfg)
    progresso(db, etapa="P7: modelo final")
    recente = df[df.corte > V.corte_local(fim) - pd.Timedelta(weeks=cfg["prev_treino_semanas"])]
    modelo = p7.ajustar(recente)
    m, b = r["modelo"], r["baseline"]
    metricas = {**m, "importancia": p7.importancia_global(modelo, recente.sample(min(len(recente), 20_000), random_state=0))}
    mv = registrar(db, nome="furto_equipamento_30d", modulo="P7", fim=fim, inicio=modelo.treino_cortes[0], metricas=metricas,
                   metricas_baseline=b, por_corte=r["por_corte"],
                   parametros={"lgbm": p7.PARAMS_LGBM, "janela_dias": p7.JANELA, "variaveis": p7.COLUNAS,
                               "linhas_treino": len(recente)})
    mv.caminho_artefato = artefatos.salvar(modelo, mv.nome, mv.versao)
    db.commit()
    def f3(v):
        return "—" if v is None else f"{v:.3f}"  # sem nenhum furto no período, a AUC fica indefinida
    log(f"[treino] P7: AUC {f3(m['auc'])} (baseline {f3(b['auc'])}); precisão nos 50 primeiros {m['precisao_50']:.1%} "
        f"(baseline {b['precisao_50']:.1%}, taxa base {m['taxa_base']:.2%})")
    return {"modelo": {k: v for k, v in m.items() if k != "calibracao"}, "baseline": {k: v for k, v in b.items() if k != "calibracao"}}


def treinar(todos: bool = True, so_baselines: bool = False, log=print) -> dict:
    t0 = time.time()
    with SessionLocal() as db:
        progresso(db, situacao="rodando", etapa="Carregando dados", inicio=datetime.now(timezone.utc).isoformat(),
                  mensagem=None, pid=os.getpid())
        try:
            f = V.carregar(db)
            res = {"baselines": baselines(db, f, log)}
            if not so_baselines:
                res["P1"] = treinar_p1(db, f, log)
                res["P2"] = treinar_p2(db, f, log)
                res["P6"] = treinar_p6(db, f, log)
                res["P7"] = treinar_p7(db, f, log)
                progresso(db, etapa="Previsões em lote")
                n = prever.prever_p1(db, f)
                n678 = diarias.lote(db, f)
                log(f"[treino] previsões diárias: {n678['p6']} de P6, {n678['p7']} de P7 e {n678['p8']} de P8")
                n23 = prever.prever_p2_p3(db, f)
                log(f"[treino] {n} previsões de P1, {n23['p2']} de P2 e {n23['p3']} de P3 gravadas")
                progresso(db, etapa="Planejamento de equipes")
                n4 = planejamento.prever_p4(db)
                res["P4"] = n4
                log(f"[treino] P4: {n4['recomendacoes']} recomendações de reforço; risco não coberto nas próximas 72 h "
                    f"{n4['nao_coberto_antes']:.0f} → {n4['nao_coberto_depois']:.0f} ({n4['reducao_pct'] or 0:.0f}% menor)")
            progresso(db, situacao="pronto", etapa="Concluído", segundos=round(time.time() - t0, 1))
        except Exception as exc:
            db.rollback()
            progresso(db, situacao="erro", mensagem=f"{type(exc).__name__}: {exc}")
            raise
    log(f"[treino] concluído em {time.time() - t0:.1f}s")
    return res


NOVOS = ("disponibilidade_regiao", "furto_equipamento_30d", "carga_manutencao")


def faltando(db: Session) -> list[str]:
    """Modelos da fase 12 que ainda não existem num banco treinado antes dela."""
    tem = set(db.scalars(select(ModeloVersao.nome).where(ModeloVersao.ativo, ModeloVersao.nome.in_(NOVOS))))
    return [n for n in NOVOS if n not in tem]


def treinar_novos(log=print) -> dict:
    """Treina só o que falta (P6, P7 e o P8, que vem do backtest de P1) e refaz as previsões diárias."""
    t0 = time.time()
    with SessionLocal() as db:
        falta = faltando(db)
        if not falta:
            return {}
        progresso(db, situacao="rodando", etapa="Carregando dados", inicio=datetime.now(timezone.utc).isoformat(),
                  mensagem=None, pid=os.getpid())
        try:
            f = V.carregar(db)
            res = {}
            if "disponibilidade_regiao" in falta:
                res["P6"] = treinar_p6(db, f, log)
            if "furto_equipamento_30d" in falta:
                res["P7"] = treinar_p7(db, f, log)
            if "carga_manutencao" in falta:
                res["P1"] = treinar_p1(db, f, log)
                prever.prever_p1(db, f)
            progresso(db, etapa="Previsões em lote")
            res["lote"] = diarias.lote(db, f)
            progresso(db, situacao="pronto", etapa="Concluído", segundos=round(time.time() - t0, 1))
        except Exception as exc:
            db.rollback()
            progresso(db, situacao="erro", mensagem=f"{type(exc).__name__}: {exc}")
            raise
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--todos", action="store_true", help="avalia e treina tudo o que existe")
    ap.add_argument("--baselines", action="store_true", help="só os baselines")
    args = ap.parse_args()
    treinar(todos=args.todos or not args.baselines, so_baselines=args.baselines)


if __name__ == "__main__":
    main()
