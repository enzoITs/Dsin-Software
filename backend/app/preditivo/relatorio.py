"""X5: relatório semanal do gestor, em Markdown, no mesmo formato do briefing diário.

O briefing olha para o dia; o relatório olha para a semana que passou e as próximas: quanto as
previsões acertaram, o que foi decidido e o que aconteceu depois, alertas preventivos e anomalias,
e as tendências (disponibilidade, manutenção, furtos, fim de vida útil, saúde dos modelos). Montado
só com dados do sistema, sem IA. Gerado sob demanda (`GET /relatorio/semanal`).
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.preditivo import acertometro, monitor, prever, retorno, vida_util
from app.preditivo.briefing import MESES, _item, markdown
from app.preditivo.consultas import _fmt
from app.preditivo.variaveis import FUSO

NOME_ALERTA = {"previsao_risco_regiao": "risco alto na região", "previsao_falha_equipamento": "falha de equipamento",
               "previsao_falta_agentes": "falta de agentes", "previsao_disponibilidade": "disponibilidade abaixo da meta",
               "anomalia_equipamento": "anomalia de equipamento", "anomalia_regiao": "anomalia de região"}


def _pct(v: float) -> str:
    return f"{_fmt(v * 100, 1)}%"


def montar(db: Session, fim: date | None = None) -> dict:
    fim = fim or prever.hoje_local()
    ini = fim - timedelta(days=7)
    a = datetime.combine(ini, datetime.min.time(), ZoneInfo(FUSO))
    b = datetime.combine(fim, datetime.min.time(), ZoneInfo(FUSO))
    agora = datetime.now(timezone.utc)
    secoes = []

    # Acertômetro da semana
    acertometro.conferir(db)
    acerto = []
    p2 = acertometro.resumo_p2(db, agora, 7)
    g = p2.get("geral") or {}
    if g.get("n"):
        comp = "menos" if (g["ganho_pct"] or 0) >= 0 else "mais"
        acerto.append(_item(f"Ocorrências: {g['n']} horas de região conferidas; o modelo errou {_fmt(abs(g['ganho_pct'] or 0), 0)}% "
                            f"{comp} que a média histórica (erro médio {_fmt(g['mae'], 2)} × {_fmt(g['mae_baseline'], 2)}); "
                            f"{_fmt(g['cobertura_intervalo'] * 100, 0)}% dos valores reais dentro da faixa prevista."))
    else:
        acerto.append(_item("Ocorrências: ainda sem horas conferidas nesta semana."))
    for l in [x for x in acertometro.resumo_p1(db, agora).get("lotes", []) if x["encerrado"]][:1]:
        acerto.append(_item(f"Falhas: na semana de {l['inicio'][8:10]}/{l['inicio'][5:7]}, dos {l['apontados']} equipamentos de maior "
                            f"risco, {l['falharam_apontados']} falharam ({_fmt(l['taxa_apontados'] * 100, 0)}%), contra "
                            f"{_fmt(l['taxa_geral'] * 100, 1)}% na frota."))
    secoes.append({"id": "acertometro", "titulo": "Quanto as previsões acertaram", "itens": acerto})

    # Decisões
    r = retorno.resumo(db, 7)
    dec = []
    if r["decididas"]:
        dec.append(_item(f"{r['decididas']} recomendações decididas (aceitação de {_fmt((r['taxa_aceitacao'] or 0) * 100, 0)}%); "
                         f"{r['por_estado'].get('pendente', 0)} pendentes."))
        dec += [_item(f"{t['rotulo']}: {t['aceitas']} aceitas, {t['rejeitadas']} rejeitadas, {t['pendentes']} pendentes.")
                for t in r["por_tipo"] if t["total"]]
        if r["motivos_rejeicao"]:
            dec.append(_item("Motivos de rejeição mais citados: " + "; ".join(f"\"{m['motivo']}\" ({m['vezes']})"
                                                                           for m in r["motivos_rejeicao"][:3]) + "."))
        os_ = r["comparacao"]["os"]
        if os_["aceitas"]["conferidas"] and os_["rejeitadas"]["conferidas"]:
            dec.append(_item(f"OS preventivas: falharam {_fmt(os_['aceitas']['taxa_falha'] * 100, 0)}% das aceitas e "
                             f"{_fmt(os_['rejeitadas']['taxa_falha'] * 100, 0)}% das rejeitadas (comparação observacional)."))
    else:
        dec.append(_item(f"Nenhuma recomendação decidida na semana; {r['por_estado'].get('pendente', 0)} pendentes."))
    secoes.append({"id": "decisoes", "titulo": "Decisões e o que aconteceu depois", "itens": dec})

    # Alertas preventivos e anomalias
    al = db.execute(text("""SELECT tipo::text, count(*) abertos, count(resolvido_em) resolvidos FROM alerta
                            WHERE criado_em >= :a AND criado_em < :b AND (tipo::text LIKE 'previsao_%' OR tipo::text LIKE 'anomalia_%')
                            GROUP BY 1 ORDER BY 2 DESC"""), {"a": a, "b": b}).all()
    secoes.append({"id": "alertas", "titulo": "Alertas preventivos e anomalias", "itens": [
        _item(f"{NOME_ALERTA.get(t, t).capitalize()}: {n} abertos, {rr} já resolvidos.") for t, n, rr in al]
        or [_item("Nenhum alerta preventivo ou anomalia na semana.")]})

    # Tendências
    tend = []
    p6 = db.execute(text("""SELECT detalhe->'alvo'->>'nome' nome, valor, (detalhe->>'atual')::float atual, (detalhe->>'meta')::float meta,
                                   (detalhe->>'seguindo_p1')::float seguindo, id
                            FROM previsao WHERE modulo = 'P6' AND alvo_tipo = 'regiao' AND (detalhe->>'horizonte_dias')::int = 30
                              AND horizonte_inicio = (SELECT max(horizonte_inicio) FROM previsao WHERE modulo = 'P6')
                            ORDER BY valor""")).mappings().all()
    abaixo = [x for x in p6 if x["valor"] < x["meta"]]
    tend += [_item(f"Disponibilidade da região {x['nome']}: {_pct(x['atual'])} hoje, {_pct(x['valor'])} prevista em 30 dias "
                   f"(meta {_pct(x['meta'])}); seguindo o P1, {_pct(x['seguindo'])}.", x["id"]) for x in abaixo]
    if p6 and not abaixo:
        tend.append(_item("Todas as regiões com disponibilidade prevista acima da meta nos próximos 30 dias."))
    p8 = db.execute(text("""SELECT valor, (detalhe->>'normal_tecnicos_dia')::float normal, detalhe->>'rotulo' rotulo, id FROM previsao
                            WHERE modulo = 'P8' AND alvo_tipo = 'cidade'
                              AND detalhe->>'origem' = (SELECT max(detalhe->>'origem') FROM previsao WHERE modulo = 'P8')
                            ORDER BY horizonte_inicio LIMIT 2""")).mappings().all()
    tend += [_item(f"Manutenção na {x['rotulo']}: {_fmt(x['valor'], 0)} técnicos-dia na cidade (normal: {_fmt(x['normal'], 0)}).", x["id"])
             for x in p8]
    furtos_sem = db.scalar(text("SELECT count(*) FROM historico_situacao WHERE situacao_nova = 'furtado' AND em >= :a AND em < :b"),
                           {"a": a, "b": b})
    p7 = db.execute(text("""SELECT detalhe->'alvo'->>'bairro' bairro, sum(valor) esperados FROM previsao
                            WHERE modulo = 'P7' AND horizonte_inicio = (SELECT max(horizonte_inicio) FROM previsao WHERE modulo = 'P7')
                            GROUP BY 1 ORDER BY 2 DESC LIMIT 2""")).all()
    if p7:
        tend.append(_item(f"Furtos de equipamento: {furtos_sem} na semana; nos próximos 30 dias, mais esperados em "
                          + " e ".join(f"{bb} ({_fmt(e, 1)})" for bb, e in p7) + "."))
    vu = vida_util.obter(db)
    if vu.get("resumo"):
        rs = vu["resumo"]
        marca = rs["marcas"][0] if rs["marcas"] else None
        tend.append(_item(f"Fim de vida útil: {rs['recomendados']} equipamentos para trocar ({rs['passou_vida_util']} passaram da vida útil, "
                          f"{rs['desgaste']} por desgaste)" + (f"; mais comum: {marca['marca']} ({marca['n']})" if marca else "") + "."))
    secoes.append({"id": "tendencias", "titulo": "Tendências para as próximas semanas", "itens": tend or [_item("Sem previsões de tendência.")]})

    # Saúde dos modelos
    mon = monitor.avaliar(db, agora)
    itens_m = [_item(f"{mon['texto']}.")]
    for m in mon["modelos"]:
        if m["situacao"] != "ok":
            pior = next(c for c in m["verificacoes"] if c["situacao"] == m["situacao"])
            itens_m.append(_item(f"{m['titulo']}: {pior['texto']}."))
    secoes.append({"id": "modelos", "titulo": "Saúde dos modelos", "itens": itens_m})

    # Resumo no topo
    resumo = [_item(f"Previsões: {secoes[0]['itens'][0]['texto']}"),
              _item(f"Decisões: {dec[0]['texto']}"),
              _item(f"{len(abaixo)} {'região' if len(abaixo) == 1 else 'regiões'} com disponibilidade prevista abaixo da meta; "
                    f"modelos: {mon['texto'].lower()}.")]
    secoes.insert(0, {"id": "resumo", "titulo": "Resumo", "itens": resumo})
    ultimo = fim - timedelta(days=1)
    titulo = (f"Relatório semanal: {ini.day} de {MESES[ini.month - 1]} a {ultimo.day} de {MESES[ultimo.month - 1]} de {ultimo.year}")
    rodape = "As recomendações são sugestões: quem decide é a equipe. Dados sintéticos de demonstração."
    dados = {"data": fim.isoformat(), "inicio": ini.isoformat(), "titulo": titulo, "secoes": secoes, "rodape": rodape,
             "gerado_em": agora.isoformat(), "gerado_por": "sob demanda", "dados_sinteticos": True}
    return {**dados, "markdown": markdown(dados)}
