"""Histórico sintético da Parte 3: geração inicial e modo contínuo.

- `gerar`: depois do seed (que já simulou a vida dos equipamentos), cria clima, calendário,
  eventos, escala, ocorrências e séries dos 18 meses até a data de referência, mais eventos e
  escala futuros.
- `avancar`: modo contínuo. Gera as ocorrências e as séries das horas que passaram desde a última
  vez, com os mesmos padrões, usando o clima e os eventos que estão no banco (inclusive os
  editados pelo operador). Assim as previsões de amanhã podem ser conferidas depois.
- `acoes_equipamentos`: falhas, furtos e consertos da hora para o simulador aplicar pela API,
  para o motor da Parte 2 reagir como reagiria a um equipamento de verdade.
"""

import time
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import EscalaAgente, EstadoPreditivo
from app.preditivo import calendario, clima
from app.preditivo import gerador_cidade as G
from app.preditivo import padroes as P

FUSO = clima.FUSO
DIAS_HISTORICO = 540
DIAS_SERIES = 60
DIAS_EVENTOS_FUTUROS = 30
DIAS_ESCALA_FUTURA = 14
USUARIO = "gerador"


def _estado(db: Session, chave: str):
    e = db.get(EstadoPreditivo, chave)
    return e.valor if e else None


def _gravar_estado(db: Session, chave: str, valor) -> None:
    db.merge(EstadoPreditivo(chave=chave, valor=valor))


def _meia_noite(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=FUSO)


def referencia(db: Session) -> dict:
    """Semente e data de referência gravadas pelo seed (ou padrão para bancos antigos)."""
    h = _estado(db, "historico")
    if h:
        return {"semente": int(h["semente"]), "data_referencia": date.fromisoformat(h["data_referencia"]),
                "inicio": date.fromisoformat(h["inicio"])}
    hoje = datetime.now(timezone.utc).astimezone(FUSO).date()
    return {"semente": 42, "data_referencia": hoje, "inicio": hoje - timedelta(days=DIAS_HISTORICO)}


def limpar(db: Session) -> None:
    db.execute(text("DELETE FROM ocorrencia WHERE origem = 'simulada'"))
    db.execute(text("DELETE FROM evento_cidade WHERE simulado"))
    db.execute(text("DELETE FROM escala_agente WHERE origem = 'escala'"))
    db.execute(text("DELETE FROM serie_equipamento_hora"))
    db.execute(text("DELETE FROM estado_preditivo WHERE chave IN ('cidade', 'anomalias_plantadas', 'continuo')"))


def gerar(db: Session, forcar: bool = False, log=print) -> dict:
    if _estado(db, "cidade") and not forcar:
        log("[historico] já gerado; nada a fazer (use --forcar para refazer)")
        return {}
    t0 = time.time()
    if forcar:
        limpar(db)
    ref = referencia(db)
    semente, d_ref, inicio = ref["semente"], ref["data_referencia"], ref["inicio"]
    ctx = G.carregar(db, semente)
    if not ctx.bairros or not ctx.regioes:
        raise RuntimeError("Sem bairros ou regiões: rode o seed e o preparar_central antes.")

    calendario.garantir(db, inicio - timedelta(days=1), d_ref + timedelta(days=365))
    cal = {c["data"]: c for c in calendario.dias(inicio - timedelta(days=1), d_ref + timedelta(days=DIAS_EVENTOS_FUTUROS + 1))}

    # Clima passado (o futuro é previsão, preenchida por clima.garantir_previsao)
    d = inicio
    while d < d_ref:
        lote = []
        for _ in range(31):
            if d >= d_ref:
                break
            lote += clima.dia(d, semente)
            d += timedelta(days=1)
        clima.gravar(db, ctx.cidade_id, lote, previsao=False)

    # Eventos do período e dos próximos 30 dias, mais o show da demonstração
    fim_eventos = d_ref + timedelta(days=DIAS_EVENTOS_FUTUROS)
    eventos = []
    for k in range((fim_eventos - inicio).days):
        eventos += G.eventos_dia(inicio + timedelta(days=k), semente)
    eventos.append(G.evento_demo(d_ref))
    G.gravar_eventos(db, eventos)

    # Escala do período e das próximas 2 semanas
    fim_escala = d_ref + timedelta(days=DIAS_ESCALA_FUTURA)
    turnos = []
    for k in range(-1, (fim_escala - inicio).days):
        turnos += G.escala_dia(ctx, inicio + timedelta(days=k))
    G.gravar_escala(db, turnos)
    db.flush()
    log(f"[historico] clima, {len(eventos)} eventos e {len(turnos)} turnos em {time.time() - t0:.1f}s")

    # Ocorrências
    media = G.media_agentes(ctx)
    total, lote = 0, []
    for k in range((d_ref - inicio).days):
        d = inicio + timedelta(days=k)
        chuva = np.array([h["chuva_mm"] for h in clima.dia(d, semente)])
        ini, fim = _meia_noite(d) - timedelta(hours=3), _meia_noite(d) + timedelta(hours=27)
        evs = [e for e in eventos if e["fim_em"] >= ini and e["inicio_em"] <= fim]
        lote += G.ocorrencias_dia(ctx, d, chuva, cal[d], evs, G.agentes_por_hora(ctx, d), media)
        if len(lote) > 20_000:
            total += G.copiar_ocorrencias(db, lote)
            lote = []
    total += G.copiar_ocorrencias(db, lote)
    furtos = furtos_viram_ocorrencia(db, _meia_noite(inicio), _meia_noite(d_ref))
    log(f"[historico] {total} ocorrências simuladas e {furtos} de furto em {time.time() - t0:.1f}s")

    # Séries dos últimos 60 dias (padrão 12)
    series = G.escolher_series(db, semente)
    anomalias = G.anomalias_plantadas(series, d_ref)
    n_series = 0
    for k in range(DIAS_SERIES, 0, -1):
        n_series += G.copiar_series(db, G.series_dia(semente, series, anomalias, d_ref - timedelta(days=k)))

    ate = _meia_noite(d_ref).astimezone(timezone.utc)
    _gravar_estado(db, "cidade", {
        "gerado_em": datetime.now(timezone.utc).isoformat(), "inicio": inicio.isoformat(), "data_referencia": d_ref.isoformat(),
        "eventos_ate": fim_eventos.isoformat(), "escala_ate": fim_escala.isoformat(), "series": series,
    })
    # Só para os testes e para conferir a descoberta (Q2): os modelos nunca leem isto.
    _gravar_estado(db, "anomalias_plantadas", anomalias)
    _gravar_estado(db, "continuo", {"ate": ate.isoformat()})
    db.commit()
    db.execute(text("ANALYZE ocorrencia; ANALYZE serie_equipamento_hora; ANALYZE escala_agente"))
    db.commit()
    resumo = {"ocorrencias": total + furtos, "eventos": len(eventos), "turnos": len(turnos), "series": n_series,
              "segundos": round(time.time() - t0, 1)}
    log(f"[historico] pronto: {resumo}")
    return resumo


def furtos_viram_ocorrencia(db: Session, desde: datetime, ate: datetime) -> int:
    """Cada furto do histórico dos equipamentos vira uma ocorrência FURTO_EQUIPAMENTO no local."""
    r = db.execute(text("""
        INSERT INTO ocorrencia (categoria, gravidade, inicio_em, fim_em, geom, regiao_id, bairro_id, origem,
                                equipamento_id, agentes_presentes_regiao, descricao)
        SELECT 'FURTO_EQUIPAMENTO', 4, h.em, h.em + interval '2 hours', l.geom, r.id, b.id, 'simulada', h.equipamento_id,
               (SELECT coalesce(sum(s.agentes), 0) FROM escala_agente s
                 WHERE s.regiao_id = r.id AND s.inicio_em <= h.em AND s.fim_em > h.em),
               h.motivo
        FROM historico_situacao h
        JOIN localizacao l ON l.equipamento_id = h.equipamento_id AND l.geom IS NOT NULL
        LEFT JOIN bairro b ON ST_Contains(b.geom, l.geom)
        LEFT JOIN regiao r ON r.nome = b.regiao AND r.cidade_id = b.cidade_id
        WHERE h.situacao_nova = 'furtado' AND h.em >= :desde AND h.em < :ate AND b.id IS NOT NULL
    """), {"desde": desde, "ate": ate})
    return r.rowcount or 0


# ---------------------------------------------------------------- modo contínuo


def _agentes_do_banco(db: Session, ctx: G.Contexto, d: date) -> np.ndarray:
    """Agentes em turno por bairro (pela região) e hora local, lendo a escala do banco (inclui reforços aceitos)."""
    ini = _meia_noite(d)
    turnos = db.execute(select(EscalaAgente.regiao_id, EscalaAgente.inicio_em, EscalaAgente.fim_em, EscalaAgente.agentes)
                        .where(EscalaAgente.fim_em > ini, EscalaAgente.inicio_em < ini + timedelta(days=1))).all()
    por_reg = {rid: np.zeros(24) for rid in ctx.regioes.values()}
    for rid, a, b, n in turnos:
        for h in range(24):
            t = (ini + timedelta(hours=h)).astimezone(timezone.utc)
            if a <= t < b and rid in por_reg:
                por_reg[rid][h] += n
    return np.array([por_reg.get(b["regiao_id"], np.zeros(24)) for b in ctx.bairros])


def avancar(db: Session, agora: datetime | None = None, log=print) -> dict:
    """Gera o que aconteceu desde a última vez até a última hora cheia. Idempotente."""
    est = _estado(db, "cidade")
    cont = _estado(db, "continuo")
    if not est or not cont:
        return {}
    agora = agora or datetime.now(timezone.utc)
    desde = datetime.fromisoformat(cont["ate"])
    ate = agora.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    ref = referencia(db)
    semente = ref["semente"]
    ctx = G.carregar(db, semente)
    resumo = {"ocorrencias": 0, "series": 0, "eventos": 0, "turnos": 0}

    # Futuro: eventos e escala sempre cobrindo as próximas semanas
    hoje = agora.astimezone(FUSO).date()
    ev_ate = date.fromisoformat(est["eventos_ate"])
    novo_ev = hoje + timedelta(days=DIAS_EVENTOS_FUTUROS)
    while ev_ate < novo_ev:
        resumo["eventos"] += G.gravar_eventos(db, G.eventos_dia(ev_ate, semente))
        ev_ate += timedelta(days=1)
    esc_ate = date.fromisoformat(est["escala_ate"])
    nova_esc = hoje + timedelta(days=DIAS_ESCALA_FUTURA)
    while esc_ate < nova_esc:
        resumo["turnos"] += G.gravar_escala(db, G.escala_dia(ctx, esc_ate))
        esc_ate += timedelta(days=1)
    est = {**est, "eventos_ate": ev_ate.isoformat(), "escala_ate": esc_ate.isoformat()}
    _gravar_estado(db, "cidade", est)
    db.flush()

    if ate > desde:
        # O que estava previsto para as horas que passaram vira histórico (com as edições do operador).
        clima.garantir_previsao(db, ctx.cidade_id, desde, int((ate - desde).total_seconds() // 3600) + 1, semente)
        db.execute(text("UPDATE clima_hora SET previsao = false WHERE previsao AND em < :ate"), {"ate": ate})
        media = G.media_agentes(ctx)
        anomalias = _estado(db, "anomalias_plantadas") or []
        d = desde.astimezone(FUSO).date()
        while _meia_noite(d) < ate:
            chuva = G.chuva_do_banco(db, ctx.cidade_id, d, semente)
            ocs = G.ocorrencias_dia(ctx, d, chuva, G.calendario_dia(d), G.eventos_do_banco(db, d),
                                    _agentes_do_banco(db, ctx, d), media)
            resumo["ocorrencias"] += G.copiar_ocorrencias(db, [o for o in ocs if desde <= o["inicio_em"] < ate])
            sr = G.series_dia(semente, est["series"], anomalias, d)
            resumo["series"] += G.copiar_series(db, [s for s in sr if desde <= s[2] < ate])
            d += timedelta(days=1)
        _gravar_estado(db, "continuo", {"ate": ate.isoformat()})
    db.commit()
    if any(resumo.values()):
        log(f"[historico] contínuo até {ate.astimezone(FUSO):%d/%m %H:%M}: {resumo}")
    return resumo


def acoes_equipamentos(db: Session, agora: datetime | None = None) -> list[dict]:
    """Falhas, furtos e consertos de uma hora, com os mesmos padrões do histórico.

    Devolve [{id, codigo, situacao, motivo}] para o simulador aplicar pela API. Os consertos só
    mexem em equipamentos que o próprio gerador derrubou, para não atrapalhar a demonstração.
    """
    if not _estado(db, "cidade"):
        return []
    agora = agora or datetime.now(timezone.utc)
    ref = referencia(db)
    hora = agora.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    r = np.random.default_rng(P.chave("continuo-equipamentos", ref["semente"], hora.isoformat()))
    hoje = agora.astimezone(FUSO).date()
    horas_hoje = clima.dia(hoje, ref["semente"])
    horas_ontem = clima.dia(hoje - timedelta(days=1), ref["semente"])
    tmax = max(h["temperatura_c"] for h in horas_hoje)
    chuva_ontem = sum(h["chuva_mm"] for h in horas_ontem)

    linhas = db.execute(text("""
        SELECT e.id, e.codigo_interno, t.prefixo, e.marca, e.atributos, e.data_instalacao, e.situacao::text,
               l.regiao, b.nome bairro, t.mobilidade::text = 'movel' movel,
               (SELECT min(p.proxima_data) FROM plano_manutencao p
                 WHERE p.equipamento_id = e.id AND p.ativo AND p.tipo = 'periodica') vence,
               (b.nome = ANY(:bairros) AND EXISTS (
                   SELECT 1 FROM equipamento c JOIN tipo_equipamento tc ON tc.id = c.tipo_id AND tc.prefixo = 'CAM'
                   JOIN localizacao lc ON lc.equipamento_id = c.id
                   WHERE c.id <> e.id AND ST_DWithin(lc.geom, l.geom, :graus))) cam_perto
        FROM equipamento e JOIN tipo_equipamento t ON t.id = e.tipo_id
        LEFT JOIN localizacao l ON l.equipamento_id = e.id
        LEFT JOIN bairro b ON b.id = l.bairro_id
        WHERE e.situacao IN ('operacional', 'mau_funcionamento') ORDER BY e.id
    """), {"bairros": list(P.BAIRROS_FURTO), "graus": P.RAIO_CAMERA_M / 111_000}).all()
    if not linhas:
        return []
    n = len(linhas)
    op = np.array([x.situacao == "operacional" for x in linhas])
    base = np.array([P.FALHA_BASE_DIA.get(x.prefixo, 0.0025) for x in linhas])
    idade = np.array([(hoje - x.data_instalacao).days if x.data_instalacao else 0 for x in linhas])
    fragil = np.array([x.prefixo == "CAM" and x.marca.strip().lower() == P.MARCA_FRAGIL for x in linhas])
    rodovia = np.array([x.prefixo == "RAD" and (x.atributos or {}).get("modalidade") == "velocidade"
                        and (x.atributos or {}).get("velocidade_maxima", 0) >= P.VELOCIDADE_RODOVIA for x in linhas])
    atraso = np.array([(hoje - x.vence).days if x.vence else 0 for x in linhas])
    fragilidade = np.array([np.random.default_rng(P.chave("fragilidade", x.id)).lognormal(0, 0.35) for x in linhas])
    h_dia = P.risco_falha_dia(base, idade, fragil, rodovia, atraso, fragilidade, chuva_ontem, tmax)
    falha = op & (r.random(n) < h_dia / 24)

    furtavel = np.array([x.prefixo in P.TIPOS_FURTAVEIS for x in linhas])
    bairro_furto = np.array([x.bairro in P.BAIRROS_FURTO and not x.movel for x in linhas])
    cam_perto = np.array([bool(x.cam_perto) for x in linhas])
    hf = P.risco_furto_dia(furtavel, bairro_furto, cam_perto)
    hora_local = agora.astimezone(FUSO).hour
    # Nos bairros do padrão 6, o furto do dia acontece de madrugada; nos demais, a qualquer hora.
    hf_hora = np.where(bairro_furto, np.where(hora_local in P.HORAS_MADRUGADA, hf / len(P.HORAS_MADRUGADA), 0.0), hf / 24)
    furto = ~falha & ~np.array([x.movel for x in linhas]) & (r.random(n) < hf_hora)

    acoes = []
    for i in np.flatnonzero(falha):
        x = linhas[i]
        motivos = ["Falha de comunicação", "Leitura inconsistente", "Queda de energia recorrente"]
        if x.prefixo == "CAM":
            motivos = ["Lente danificada", "Imagem sem foco", "Falha de comunicação"]
        acoes.append({"id": x.id, "codigo": x.codigo_interno, "situacao": "mau_funcionamento",
                      "motivo": str(r.choice(motivos))})
    for i in np.flatnonzero(furto):
        x = linhas[i]
        acoes.append({"id": x.id, "codigo": x.codigo_interno, "situacao": "furtado",
                      "motivo": "Equipamento não encontrado no local"})

    # Consertos do que o gerador derrubou: abre manutenção depois de alguns dias e conclui no dia seguinte.
    for eid, cod, sit, desde, regiao in db.execute(text("""
        SELECT DISTINCT ON (h.equipamento_id) h.equipamento_id, e.codigo_interno, e.situacao::text, h.em, l.regiao
        FROM historico_situacao h JOIN equipamento e ON e.id = h.equipamento_id
        LEFT JOIN localizacao l ON l.equipamento_id = e.id
        WHERE h.usuario = :u AND e.situacao IN ('mau_funcionamento', 'em_manutencao')
        ORDER BY h.equipamento_id, h.em DESC
    """), {"u": USUARIO}).all():
        dias = (agora - desde).total_seconds() / 86400
        espera = P.ESPERA_CONSERTO_ABANDONO_MAX if regiao == P.REGIAO_SEM_PREVENTIVA else P.ESPERA_CONSERTO_DIAS
        if sit == "mau_funcionamento" and dias >= espera:
            acoes.append({"id": eid, "codigo": cod, "situacao": "em_manutencao", "motivo": "Ordem de serviço aberta"})
        elif sit == "em_manutencao" and dias >= 1:
            acoes.append({"id": eid, "codigo": cod, "situacao": "operacional", "motivo": "Manutenção concluída"})
    return acoes


def pendente(db: Session) -> bool:
    return _estado(db, "cidade") is None


def ultima_hora_gerada(db: Session) -> datetime | None:
    c = _estado(db, "continuo")
    return datetime.fromisoformat(c["ate"]) if c else None
