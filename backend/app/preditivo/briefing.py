"""Briefing diário (C4): o que o gestor precisa saber às 6 h, em uma página.

Montado só com dados do sistema (funciona sem IA e sem internet), em seções curtas: resumo, onde e
quando o risco é maior hoje, reforços para decidir, manutenções preventivas, anomalias, contexto do
dia e o acertômetro de ontem (previsto × aconteceu). Cada item que vem de uma previsão leva o id do
cartão. Gerado pelo agendador às 6 h e guardado na tabela `briefing`; sob demanda pela API.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Briefing
from app.preditivo import acertometro, consultas, prever
from app.preditivo.consultas import _fmt
from app.preditivo.variaveis import FUSO

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _item(texto: str, previsao_id: int | None = None) -> dict:
    return {"texto": texto, "previsao_id": previsao_id}


def montar(db: Session, dia: date | None = None) -> dict:
    dia = dia or prever.hoje_local()
    ontem = dia - timedelta(days=1)
    secoes = []

    risco = consultas.risco(db, dia=dia, limite=6)
    oc = consultas.ocorrencias_previstas(db, dia)
    alertas = consultas.alertas_preventivos(db)
    fim_do_dia = datetime.combine(dia + timedelta(days=1), datetime.min.time(), ZoneInfo(FUSO))
    reforcos = consultas.reforcos(db, horas=max(1, int((fim_do_dia - datetime.now(timezone.utc)).total_seconds() // 3600)))
    equip = consultas.equipamentos(db, 7, limite=6)
    anom = consultas.anomalias(db)
    ctx = consultas.contexto(db, dia)

    # Resumo
    resumo = []
    if risco["periodos"]:
        p = risco["periodos"][0]
        resumo.append(_item(f"Momento mais crítico do dia: {p['regiao']}, {p['quando'].split(', ', 1)[-1]}, risco {p['nivel_nome']} "
                            f"(índice {p['indice']}). {p['motivo']}.", p["previsao_id"]))
    if oc.get("disponivel"):
        razao = oc["previsto"] / oc["normal"] if oc["normal"] else None
        resumo.append(_item(f"Ocorrências previstas para o dia: {_fmt(oc['previsto'], 0)}"
                            + (f" ({_fmt(abs(razao * 100 - 100), 0)}% {'acima' if razao >= 1 else 'abaixo'} do normal)" if razao else "")
                            + (f"; mais na região {oc['por_regiao'][0]['regiao']}" if oc["por_regiao"] else "") + "."))
    altos = sum(1 for p in risco["periodos"] if p["nivel"] in ("ALTO", "MUITO_ALTO"))
    resumo.append(_item(f"{altos} {'período' if altos == 1 else 'períodos'} com risco alto ou muito alto; "
                        f"{len(reforcos['itens'])} {'reforço' if len(reforcos['itens']) == 1 else 'reforços'} de equipes para decidir; "
                        f"{len(alertas['itens'])} alertas preventivos abertos; {len(anom['itens'])} anomalias."))
    if not risco["disponivel"]:
        resumo = [_item("Ainda não há previsões: o treino dos modelos roda sozinho no primeiro start.")]
    secoes.append({"id": "resumo", "titulo": "Resumo", "itens": resumo})

    secoes.append({"id": "risco", "titulo": "Onde e quando o risco é maior hoje", "itens": [
        _item(f"{p['regiao']}, {p['quando'].split(', ', 1)[-1]}: {p['nivel_nome']} ({p['indice']}). {p['motivo']}.", p["previsao_id"])
        for p in risco["periodos"]] or [_item("Sem previsão de risco para hoje.")]})

    secoes.append({"id": "reforcos", "titulo": "Reforços de equipes para decidir", "itens": [
        _item(x["texto"], x["previsao_id"]) for x in reforcos["itens"][:6]] or [_item("Nenhum reforço pendente: a escala cobre a demanda prevista.")]})

    sem_os = [x for x in equip.get("itens", []) if not x["os_aberta"] and not x["decisao"]]
    tot = equip.get("totais_por_nivel", {})
    itens_eq = [_item(f"{x['codigo']} ({x['regiao'] or 'sem região'}): {_fmt(x['probabilidade'] * 100, 0)}% de chance de falhar "
                      f"em 7 dias. {x['principal_fator'] or ''}", x["previsao_id"]) for x in sem_os[:5]]
    if tot:
        itens_eq.insert(0, _item(f"{tot.get('MUITO_ALTO', 0)} equipamentos em risco muito alto e {tot.get('ALTO', 0)} em alto. "
                                 f"Os de maior risco sem OS:"))
    secoes.append({"id": "manutencao", "titulo": "Manutenção preventiva", "itens": itens_eq or [_item("Sem previsão de falha disponível.")]})

    secoes.append({"id": "anomalias", "titulo": "Anomalias abertas", "itens": [
        _item(x["mensagem"]) for x in anom["itens"]] or [_item("Nenhuma: equipamentos e regiões dentro do padrão.")]})

    c = []
    if ctx["feriado"]:
        c.append(_item(f"Feriado: {ctx['feriado']}."))
    elif ctx["vespera_feriado"]:
        c.append(_item("Véspera de feriado: congestionamentos mais fortes nos horários de pico."))
    c += [_item(f"Evento: {e['nome']}{' em ' + e['local'] if e['local'] else ''}, {e['hora']}, cerca de "
                f"{_fmt(e['publico'] / 1000, 0)} mil pessoas.") for e in ctx["eventos"][:3]]
    if ctx["chuva_mm"] >= 1:
        h = ctx["horas_chuva"]
        c.append(_item(f"Chuva prevista: {_fmt(ctx['chuva_mm'], 0)} mm no dia" + (f", entre {min(h)} h e {max(h) + 1} h" if h else "")
                       + (" (alerta de tempestade)" if ctx["tempestade"] else "") + f". Máxima de {ctx['temp_max']:.0f} °C."))
    else:
        c.append(_item(f"Tempo seco previsto, máxima de {ctx['temp_max']:.0f} °C."))
    secoes.append({"id": "contexto", "titulo": "Contexto do dia", "itens": c})

    secoes.append({"id": "acertometro", "titulo": "Acertômetro de ontem", "itens": _acertometro_ontem(db, ontem)})

    q = consultas.qualidade(db)
    rodape = (f"Confiança dos modelos: ocorrências {q['P2']['confianca']}, falhas {q['P1']['confianca']}. "
              "As recomendações são sugestões: quem decide é a equipe. Dados sintéticos de demonstração.")
    titulo = f"Briefing de {DIAS[dia.weekday()]}, {dia.day} de {MESES[dia.month - 1]} de {dia.year}"
    dados = {"data": dia.isoformat(), "titulo": titulo, "secoes": secoes, "rodape": rodape, "dados_sinteticos": True}
    return {**dados, "markdown": markdown(dados)}


def _acertometro_ontem(db: Session, ontem: date) -> list[dict]:
    acertometro.conferir(db)
    r = acertometro.resumo_p2(db, datetime.now(timezone.utc), 3)
    itens = []
    d = next((x for x in r.get("por_dia", []) if x["dia"] == ontem.isoformat()), None)
    if d:
        comparacao = "o modelo errou menos que a média" if d["mae"] <= d["mae_baseline"] else "o modelo errou mais que a média"
        itens.append(_item(f"Ocorrências: erro médio de {_fmt(d['mae'], 2)} por região e hora ({d['n']} horas conferidas), contra "
                           f"{_fmt(d['mae_baseline'], 2)} da média histórica: {comparacao}; "
                           f"{_fmt(d['cobertura_intervalo'] * 100, 0)}% dos valores reais dentro da faixa prevista."))
    else:
        itens.append(_item("Ocorrências: ainda sem horas de ontem conferidas."))
    lotes = acertometro.resumo_p1(db, datetime.now(timezone.utc)).get("lotes", [])
    if lotes:
        l = lotes[0]
        itens.append(_item(f"Falhas: dos {l['apontados']} equipamentos de maior risco na semana que começou em "
                           f"{l['inicio'][8:10]}/{l['inicio'][5:7]}, {l['falharam_apontados']} já falharam "
                           f"({_fmt(l['decorrido_pct'], 0)}% da semana); entre todos, a taxa é de {_fmt(l['taxa_geral'] * 100, 1)}%."))
    dec = db.execute(text("""SELECT estado::text, count(*) FROM recomendacao
                             WHERE decidido_em >= :a AND decidido_em < :b GROUP BY 1"""),
                     {"a": datetime.combine(ontem, datetime.min.time(), ZoneInfo(FUSO)),
                      "b": datetime.combine(ontem + timedelta(days=1), datetime.min.time(), ZoneInfo(FUSO))}).all()
    if dec:
        d2 = dict(dec)
        itens.append(_item(f"Decisões de ontem: {d2.get('aceita', 0) + d2.get('ajustada', 0)} recomendações aceitas e "
                           f"{d2.get('rejeitada', 0)} rejeitadas."))
    return itens


def markdown(d: dict) -> str:
    linhas = [f"# {d['titulo']}", ""]
    for s in d["secoes"]:
        linhas += [f"## {s['titulo']}", ""]
        linhas += [f"- {i['texto']}" + (f" (cartão prev_{i['previsao_id']})" if i.get("previsao_id") else "") for i in s["itens"]]
        linhas.append("")
    linhas += [f"_{d['rodape']}_", ""]
    return "\n".join(linhas)


def gerar(db: Session, dia: date | None = None, por: str = "agendador") -> Briefing:
    """Gera (ou refaz) o briefing do dia e guarda."""
    d = montar(db, dia)
    data = date.fromisoformat(d["data"])
    b = db.scalar(select(Briefing).where(Briefing.data == data))
    if b is None:
        b = Briefing(data=data)
        db.add(b)
    b.conteudo_md, b.dados, b.gerado_por, b.gerado_em = d["markdown"], {k: v for k, v in d.items() if k != "markdown"}, por, \
        datetime.now(timezone.utc)
    db.commit()
    return b


def hoje(db: Session) -> Briefing:
    b = db.scalar(select(Briefing).where(Briefing.data == prever.hoje_local()))
    return b if b is not None else gerar(db, por="sob demanda")
