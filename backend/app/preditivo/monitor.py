"""X4: monitor dos modelos em operação.

O backtest diz como o modelo ia no passado; o monitor diz se continua indo bem agora. Para cada
modelo ativo, três verificações, cada uma com o valor, a referência e o que fazer:

- Idade: dias desde o fim dos dados de treino. Muito velho, pede retreino.
- Desempenho na operação: as previsões já conferidas (acertômetro) contra o baseline, comparadas com
  o ganho medido no backtest. Se o ganho some, algo mudou.
- Deriva dos dados: o que entra no modelo hoje (ocorrências por hora, taxa de falha, furtos por mês)
  contra o período de treino. Mudança grande = o mundo mudou e o modelo pode não saber.

Situação: "ok", "atencao" ou "retreinar". Nada é retreinado sozinho: o gestor decide (botão na tela
de confiança, `POST /modelos/treinar`).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain import limites
from app.models import ModeloVersao
from app.preditivo import acertometro, avaliacao

AMOSTRA_MIN_P2 = 5 * 24 * 3  # três dias de horas conferidas nas 5 regiões
ORDEM = {"ok": 0, "sem_dados": 0, "atencao": 1, "retreinar": 2}
TITULOS = {"falha_equipamento_7d": "Risco de falha em 7 dias (P1)", "falha_equipamento_30d": "Risco de falha em 30 dias (P1)",
           "ocorrencias_regiao_hora": "Ocorrências por região e hora (P2)", "disponibilidade_regiao": "Tendência de disponibilidade (P6)",
           "furto_equipamento_30d": "Risco de furto (P7)"}


def _fmt(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def _check(nome: str, situacao: str, texto: str, valor=None, referencia=None) -> dict:
    return {"verificacao": nome, "situacao": situacao, "texto": texto, "valor": valor, "referencia": referencia}


def _idade(mv: ModeloVersao, hoje, maximo: int) -> dict:
    dias = (hoje - mv.treino_fim).days if mv.treino_fim else None
    if dias is None:
        return _check("idade", "sem_dados", "Sem data de treino")
    sit = "retreinar" if dias > maximo else "atencao" if dias > maximo * 0.7 else "ok"
    return _check("idade", sit, f"Treinado com dados até {mv.treino_fim:%d/%m/%Y} ({'hoje' if dias == 0 else f'{dias} dia atrás' if dias == 1 else f'{dias} dias atrás'}; retreinar depois de {maximo} dias)",
                  dias, maximo)


def _razao(atual: float, ref: float, o_que: str, unidade: str) -> dict:
    if not ref:
        return _check("deriva", "sem_dados", f"Sem referência de {o_que} no treino")
    r = atual / ref
    sit = "retreinar" if r < 0.6 or r > 1.6 else "atencao" if r < 0.8 or r > 1.25 else "ok"
    return _check("deriva", sit, f"{o_que.capitalize()}: {_fmt(atual, 2)} {unidade} agora contra {_fmt(ref, 2)} no treino "
                                 f"({_fmt(r, 2)}×)", round(atual, 4), round(ref, 4))


def _taxa_falha(db: Session, ini, fim) -> float | None:
    """Falhas por equipamento em operação por dia, no intervalo."""
    n = db.scalar(text("""SELECT count(*) FROM historico_situacao WHERE situacao_nova = 'mau_funcionamento' AND em >= :a AND em < :b"""),
                  {"a": ini, "b": fim})
    eq = db.scalar(text("SELECT count(*) FROM equipamento WHERE situacao IN ('operacional', 'mau_funcionamento', 'em_manutencao')"))
    dias = max((fim - ini).total_seconds() / 86400, 1)
    return n / eq / dias if eq else None


def avaliar(db: Session, agora: datetime | None = None) -> dict:
    cfg = limites.carregar(db)
    agora = agora or datetime.now(timezone.utc)
    hoje = agora.date()
    queda = cfg["prev_x4_queda_ganho_pp"]
    modelos = []
    ativos = {mv.nome: mv for mv in db.scalars(select(ModeloVersao).where(ModeloVersao.ativo, ModeloVersao.nome.in_(TITULOS)))}
    acertometro.conferir(db)

    for nome, mv in ativos.items():
        m, b = mv.metricas or {}, mv.metricas_baseline or {}
        checks = [_idade(mv, hoje, cfg["prev_x4_idade_max_dias"])]
        inicio_treino = datetime.combine(mv.treino_inicio or hoje - timedelta(days=365), datetime.min.time(), timezone.utc)
        fim_treino = datetime.combine(mv.treino_fim or hoje, datetime.min.time(), timezone.utc)

        if nome == "ocorrencias_regiao_hora":
            bt = avaliacao.ganho(m.get("mae"), b.get("mae"), menor_melhor=True)
            r = acertometro.resumo_p2(db, agora, 7)["geral"] if db.scalar(text(
                "SELECT count(*) FROM previsao WHERE modulo = 'P2' AND valor_real IS NOT NULL")) else None
            if r and r.get("n"):
                g = r["ganho_pct"]
                sit = "retreinar" if g is not None and g < 0 else "atencao" if g is not None and bt is not None and g < bt - queda else "ok"
                pouco = r["n"] < AMOSTRA_MIN_P2
                if pouco and sit == "retreinar":
                    sit = "atencao"  # poucas horas conferidas: pode ser acaso, ainda não justifica retreinar
                comp = f"erra {_fmt(abs(g or 0), 0)}% {'menos' if (g or 0) >= 0 else 'mais'} que a média histórica"
                checks.append(_check("desempenho", sit,
                                     f"Últimos 7 dias ({r['n']} horas de região conferidas): {comp}; no backtest, {_fmt(bt or 0, 0)}% menos. "
                                     f"Real dentro da faixa: {_fmt(r['cobertura_intervalo'] * 100, 0)}% (esperado: 90%)"
                                     + (". Amostra pequena: conferir de novo em alguns dias" if pouco else ""), g, bt))
            else:
                checks.append(_check("desempenho", "sem_dados", "Ainda sem horas conferidas na operação"))
            por_h = lambda a, z: (db.scalar(text("SELECT count(*) FROM ocorrencia WHERE inicio_em >= :a AND inicio_em < :b"),
                                            {"a": a, "b": z}) or 0) / max((z - a).total_seconds() / 3600, 1)
            checks.append(_razao(por_h(agora - timedelta(days=14), agora), por_h(fim_treino - timedelta(days=90), fim_treino),
                                 "ocorrências registradas por hora", "por hora"))

        elif nome.startswith("falha_equipamento"):
            janela = 7 if nome.endswith("7d") else 30
            lift_bt = (m.get("precisao_50") or 0) / m["taxa_base"] if m.get("taxa_base") else None
            lotes = [l for l in acertometro.resumo_p1(db, agora).get("lotes", []) if l["encerrado"]]
            if janela == 7 and lotes and lotes[0]["taxa_geral"]:
                l = lotes[0]
                lift = l["taxa_apontados"] / l["taxa_geral"]
                sit = "retreinar" if lift < 1.2 else "atencao" if lift_bt and lift < lift_bt / 2 else "ok"
                checks.append(_check("desempenho", sit,
                                     f"Semana encerrada em {l['fim'][8:10]}/{l['fim'][5:7]}: os {l['apontados']} apontados falharam "
                                     f"{_fmt(lift)}× mais que a média; no backtest, {_fmt(lift_bt or 0)}×", round(lift, 2),
                                     round(lift_bt, 2) if lift_bt else None))
            else:
                checks.append(_check("desempenho", "sem_dados", "Nenhuma semana prevista encerrada ainda para conferir"
                                     if janela == 7 else "O lote de 30 dias ainda não terminou"))
            atual = _taxa_falha(db, agora - timedelta(days=28), agora)
            ref = _taxa_falha(db, fim_treino - timedelta(days=90), fim_treino)
            if atual is not None and ref:
                checks.append(_razao(atual * 1000, ref * 1000, "falhas por mil equipamentos por dia", "por mil por dia"))

        elif nome == "furto_equipamento_30d":
            mes = lambda a, z: (db.scalar(text("""SELECT count(*) FROM historico_situacao WHERE situacao_nova = 'furtado'
                                                   AND em >= :a AND em < :b"""), {"a": a, "b": z}) or 0) / max((z - a).days / 30, 1)
            checks.append(_razao(mes(agora - timedelta(days=60), agora), mes(inicio_treino, fim_treino), "furtos por mês", "por mês"))

        elif nome == "disponibilidade_regiao":
            bt = avaliacao.ganho(m.get("mae_pp_90"), b.get("mae_pp_90"), menor_melhor=True)
            checks.append(_check("desempenho", "ok" if bt is not None and bt > 0 else "atencao",
                                 f"Backtest: erra {_fmt(bt or 0, 0)}% menos que a média móvel em 90 dias. A conferência na operação "
                                 "começa quando as primeiras previsões de 30 dias vencerem", bt, None))

        pior = max(checks, key=lambda c: ORDEM[c["situacao"]])["situacao"]
        modelos.append({"nome": nome, "titulo": TITULOS[nome], "versao": mv.versao, "situacao": pior if pior != "sem_dados" else "ok",
                        "verificacoes": checks})
    modelos.sort(key=lambda x: list(TITULOS).index(x["nome"]))
    geral = max((x["situacao"] for x in modelos), key=lambda s: ORDEM[s], default="ok")
    textos = {"ok": "Todos os modelos dentro do esperado", "atencao": "Algum modelo pede atenção",
              "retreinar": "Algum modelo deve ser retreinado"}
    return {"gerado_em": agora.isoformat(), "situacao": geral, "texto": textos[geral], "modelos": modelos,
            "como_funciona": ("Idade do treino, desempenho das previsões já conferidas contra o baseline (comparado com o "
                              "backtest) e deriva dos dados de entrada contra o período de treino. Nada é retreinado sozinho: "
                              "o gestor decide.")}
