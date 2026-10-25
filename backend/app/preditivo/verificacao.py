"""Confere, com consultas diretas ao banco, que cada padrão plantado aparece no histórico gerado.

Não é usado pelos modelos. Serve para o teste dos padrões e para `python -m scripts.verificar_padroes`.
Cada verificação devolve a medida obtida e o mínimo esperado (com folga para o ruído).
"""

from datetime import timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.preditivo import padroes as P


def _df(db: Session, sql: str, **params) -> pd.DataFrame:
    r = db.execute(text(sql), params)
    return pd.DataFrame(r.fetchall(), columns=list(r.keys()))


def _item(padrao: int, descricao: str, obtido: float, minimo: float, detalhe: str = "") -> dict:
    return {"padrao": padrao, "descricao": descricao, "obtido": round(float(obtido), 2), "minimo": minimo,
            "ok": bool(obtido >= minimo), "detalhe": detalhe}


def periodo(db: Session) -> tuple:
    r = db.execute(text("SELECT valor FROM estado_preditivo WHERE chave = 'cidade'")).scalar()
    return pd.Timestamp(r["inicio"], tz="America/Sao_Paulo"), pd.Timestamp(r["data_referencia"], tz="America/Sao_Paulo")


def p1_centro_noite(db: Session) -> dict:
    df = _df(db, """
        SELECT extract(isodow FROM o.inicio_em AT TIME ZONE 'America/Sao_Paulo') dow, count(*) n
        FROM ocorrencia o JOIN regiao r ON r.id = o.regiao_id
        WHERE r.nome = 'Centro' AND o.origem = 'simulada'
          AND extract(hour FROM o.inicio_em AT TIME ZONE 'America/Sao_Paulo') BETWEEN 18 AND 22
        GROUP BY 1""")
    sexsab = df[df.dow.isin([5, 6])].n.sum() / 2
    outros = df[df.dow.isin([1, 2, 3, 4])].n.sum() / 4
    return _item(1, "Centro, 18 h às 23 h: sexta e sábado ÷ segunda a quinta", sexsab / max(outros, 1), 1.6)


def p2_chuva(db: Session) -> list[dict]:
    df = _df(db, """
        WITH h AS (
            SELECT c.em, c.chuva_mm >= :mm chove FROM clima_hora c
            WHERE NOT c.previsao AND extract(hour FROM c.em AT TIME ZONE 'America/Sao_Paulo') BETWEEN 12 AND 20)
        SELECT h.chove, count(DISTINCT h.em) horas, count(o.id) acidentes
        FROM h LEFT JOIN ocorrencia o ON o.categoria = 'ACIDENTE' AND o.origem = 'simulada'
             AND o.inicio_em >= h.em AND o.inicio_em < h.em + interval '1 hour'
        GROUP BY 1""", mm=P.CHUVA_HORA_MM)
    taxa = {bool(r.chove): r.acidentes / max(r.horas, 1) for r in df.itertuples()}
    alag = _df(db, """
        SELECT b.nome = ANY(:baixos) baixo, count(*) n FROM ocorrencia o JOIN bairro b ON b.id = o.bairro_id
        WHERE o.categoria = 'ALAGAMENTO' AND o.origem = 'simulada' GROUP BY 1""", baixos=list(P.BAIRROS_BAIXOS))
    tot = alag.n.sum()
    frac = alag[alag.baixo].n.sum() / tot if tot else 0
    return [
        _item(2, "Acidentes por hora com chuva ÷ sem chuva (12 h às 20 h)", taxa.get(True, 0) / max(taxa.get(False, 1e-9), 1e-9), 1.25),
        _item(2, f"Fração dos alagamentos nos bairros baixos ({', '.join(P.BAIRROS_BAIXOS)})", frac, 0.7),
    ]


def p3_eventos(db: Session) -> dict:
    df = _df(db, """
        WITH ev AS (
            SELECT id, geom, publico_estimado p, inicio_em - interval '2 hours' a, fim_em + interval '2 hours' b
            FROM evento_cidade WHERE simulado AND fim_em < (SELECT max(inicio_em) FROM ocorrencia))
        SELECT ev.p > :lim grande,
               sum((SELECT count(*) FROM ocorrencia o WHERE o.inicio_em >= ev.a AND o.inicio_em < ev.b
                    AND ST_DWithin(o.geom::geography, ev.geom::geography, :raio))) durante,
               sum((SELECT count(*) FROM ocorrencia o WHERE o.inicio_em >= ev.a - interval '7 days'
                    AND o.inicio_em < ev.b - interval '7 days'
                    AND ST_DWithin(o.geom::geography, ev.geom::geography, :raio))) semana_antes
        FROM ev GROUP BY 1""", lim=P.PUBLICO_GRANDE, raio=P.RAIO_EVENTO_M)
    g = df[df.grande]
    razao = float(g.durante.iloc[0]) / max(float(g.semana_antes.iloc[0]), 1) if len(g) else 0
    p = df[~df.grande]
    peq = float(p.durante.iloc[0]) / max(float(p.semana_antes.iloc[0]), 1) if len(p) else 1
    return _item(3, "Ocorrências a 2 km de eventos > 10 mil ÷ mesma janela 7 dias antes", razao, 1.5,
                 f"eventos menores: {peq:.2f}")


def _falhas_por_equipamento_dia(db: Session, inicio, fim, filtro: str, dias_sql: str) -> tuple[float, float]:
    """(falhas por equipamento-dia nos dias marcados, idem nos demais)."""
    df = _df(db, f"""
        WITH dias AS ({dias_sql}),
        eq AS (SELECT e.id FROM equipamento e JOIN tipo_equipamento t ON t.id = e.tipo_id WHERE {filtro}),
        f AS (SELECT (h.em AT TIME ZONE 'America/Sao_Paulo')::date d, count(*) n FROM historico_situacao h
              JOIN eq ON eq.id = h.equipamento_id
              WHERE h.situacao_nova = 'mau_funcionamento' AND h.em >= :i AND h.em < :f GROUP BY 1)
        SELECT dias.marcado, count(*) dias, coalesce(sum(f.n), 0) falhas, (SELECT count(*) FROM eq) n_eq
        FROM dias LEFT JOIN f ON f.d = dias.d GROUP BY 1""", i=inicio, f=fim)
    t = {bool(r.marcado): r.falhas / max(r.dias * r.n_eq, 1) for r in df.itertuples()}
    return t.get(True, 0), t.get(False, 1e-9)


def p4_marca(db: Session, inicio, fim) -> list[dict]:
    df = _df(db, """
        SELECT lower(trim(e.marca)) = :marca fragil, e.data_instalacao < (:f)::date - 548 velha,
               count(DISTINCT e.id) n,
               count(h.id) FILTER (WHERE h.situacao_nova = 'mau_funcionamento') falhas
        FROM equipamento e JOIN tipo_equipamento t ON t.id = e.tipo_id AND t.prefixo = 'CAM'
        LEFT JOIN historico_situacao h ON h.equipamento_id = e.id AND h.em >= :i AND h.em < :f
        WHERE e.data_instalacao < (:i)::date - 30
        GROUP BY 1, 2""", marca=P.MARCA_FRAGIL, i=inicio, f=fim)
    df["taxa"] = df.falhas / df.n
    t = {(bool(r.fragil), bool(r.velha)): r.taxa for r in df.itertuples()}
    razao = t.get((True, True), 0) / max(t.get((False, True), 1e-9), 1e-9)
    chuva_s, chuva_n = _falhas_por_equipamento_dia(
        db, inicio, fim,
        f"t.prefixo = 'CAM' AND lower(trim(e.marca)) = '{P.MARCA_FRAGIL}' AND e.data_instalacao < (:i)::date - 548",
        f"""SELECT (em AT TIME ZONE 'America/Sao_Paulo')::date + 1 d, sum(chuva_mm) >= {P.CHUVA_FORTE_DIA_MM} marcado
            FROM clima_hora WHERE NOT previsao GROUP BY 1""")
    return [
        _item(4, f"Câmeras {P.MARCA_FRAGIL.title()} com mais de 18 meses: falhas ÷ outras marcas da mesma idade", razao, 2.0),
        _item(4, f"{P.MARCA_FRAGIL.title()} com mais de 18 meses: falhas no dia seguinte a chuva forte ÷ demais dias",
              chuva_s / chuva_n, 1.4),
    ]


def p5_calor(db: Session, inicio, fim) -> dict:
    quente, normal = _falhas_por_equipamento_dia(
        db, inicio, fim,
        f"t.prefixo = 'RAD' AND e.atributos->>'modalidade' = 'velocidade' "
        f"AND (e.atributos->>'velocidade_maxima')::int >= {P.VELOCIDADE_RODOVIA}",
        f"""SELECT (em AT TIME ZONE 'America/Sao_Paulo')::date d, max(temperatura_c) > {P.TEMPERATURA_CALOR} marcado
            FROM clima_hora WHERE NOT previsao GROUP BY 1""")
    return _item(5, "Radares de rodovia: falhas em dias acima de 32 °C ÷ demais dias", quente / normal, 2.0)


def p6_furtos(db: Session, inicio, fim) -> list[dict]:
    df = _df(db, """
        SELECT b.nome = ANY(:bairros) no_bairro,
               extract(hour FROM h.em AT TIME ZONE 'America/Sao_Paulo') < 5 madrugada,
               count(*) n
        FROM historico_situacao h JOIN localizacao l ON l.equipamento_id = h.equipamento_id
        JOIN bairro b ON b.id = l.bairro_id
        WHERE h.situacao_nova = 'furtado' AND h.em >= :i AND h.em < :f GROUP BY 1, 2""",
             bairros=list(P.BAIRROS_FURTO), i=inicio, f=fim)
    tot = df.n.sum()
    no_bairro = df[df.no_bairro].n.sum()
    madrugada = df[df.no_bairro & df.madrugada].n.sum() / max(no_bairro, 1)
    return [
        _item(6, f"Fração dos furtos em {' e '.join(P.BAIRROS_FURTO)} (2 de 28 bairros)", no_bairro / max(tot, 1), 0.3),
        _item(6, "Nesses bairros, fração dos furtos entre 0 h e 5 h", madrugada, 0.8),
    ]


def p7_atraso(db: Session, inicio, fim) -> dict:
    """Reconstrói, dia a dia, o atraso da preventiva de cada equipamento a partir dos registros."""
    eq = _df(db, """
        SELECT e.id, p.periodicidade_dias per, e.data_instalacao inst FROM equipamento e
        JOIN plano_manutencao p ON p.equipamento_id = e.id AND p.tipo = 'periodica'
        JOIN tipo_equipamento t ON t.id = e.tipo_id
        JOIN localizacao l ON l.equipamento_id = e.id
        WHERE t.mobilidade = 'fixo' AND e.data_instalacao < (:i)::date - 400 AND coalesce(l.regiao, '') <> :leste
          AND e.situacao IN ('operacional', 'mau_funcionamento', 'em_manutencao')
          AND NOT EXISTS (SELECT 1 FROM historico_situacao f WHERE f.equipamento_id = e.id
                          AND f.situacao_nova IN ('furtado', 'desativado') AND f.em >= :i)""",
              i=inicio, leste=P.REGIAO_SEM_PREVENTIVA)
    reg = _df(db, """
        SELECT r.equipamento_id id, (r.executada_em AT TIME ZONE 'America/Sao_Paulo')::date d, r.plano_id IS NOT NULL prev
        FROM registro_manutencao r
        WHERE r.executada_em >= (:i)::date - 400 AND r.executada_em < :f""", i=inicio, f=fim)
    fal = _df(db, """
        SELECT h.equipamento_id id, (h.em AT TIME ZONE 'America/Sao_Paulo')::date d FROM historico_situacao h
        WHERE h.situacao_nova = 'mau_funcionamento' AND h.em >= :i AND h.em < :f""", i=inicio, f=fim)
    ini, fim_d = inicio.date(), fim.date()
    prev = reg[reg.prev].groupby("id").d.apply(sorted).to_dict()
    todos = reg.groupby("id").d.apply(sorted).to_dict()
    fals = fal.groupby("id").d.apply(sorted).to_dict()
    exp = {True: 0, False: 0}
    cnt = {True: 0, False: 0}
    for r in eq.itertuples():
        datas = prev.get(r.id, [])
        consertos = todos.get(r.id, [])
        falhas = fals.get(r.id, [])
        k, ultima, kf, parado_ate = 0, None, 0, None
        d = ini
        while d < fim_d:
            while k < len(datas) and datas[k] < d:
                ultima = datas[k]
                k += 1
            if parado_ate is not None and d <= parado_ate:  # quebrado: não está exposto a falhar
                d += timedelta(days=1)
                continue
            falhou = kf < len(falhas) and falhas[kf] == d
            if ultima is not None:
                atrasado = (d - ultima).days - r.per > P.ATRASO_CRITICO_DIAS
                exp[atrasado] += 1
                cnt[atrasado] += falhou
            if falhou:
                kf += 1
                proximo = [c for c in consertos if c > d]
                parado_ate = proximo[0] if proximo else fim_d
            d += timedelta(days=1)
    taxa = {a: cnt[a] / max(exp[a], 1) for a in (True, False)}
    return _item(7, "Falhas por dia com preventiva atrasada > 15 dias ÷ em dia (fora da região abandonada)",
                 taxa[True] / max(taxa[False], 1e-9), 1.5, f"{exp[True]} equipamento-dias atrasados")


def p8_congestionamento(db: Session) -> list[dict]:
    df = _df(db, """
        SELECT c.vespera_feriado vespera, c.feriado OR c.dia_semana >= 5 folga,
               extract(hour FROM o.inicio_em AT TIME ZONE 'America/Sao_Paulo') IN (7, 8, 17, 18) pico,
               count(*) n, count(DISTINCT c.data) dias
        FROM ocorrencia o JOIN calendario c ON c.data = (o.inicio_em AT TIME ZONE 'America/Sao_Paulo')::date
        WHERE o.categoria = 'CONGESTIONAMENTO' AND o.origem = 'simulada' GROUP BY 1, 2, 3""")
    util = df[~df.folga]
    por_hora = {}
    for (v, p), g in util.groupby(["vespera", "pico"]):
        por_hora[(bool(v), bool(p))] = g.n.sum() / (g.dias.sum() * (4 if p else 20))
    pico = por_hora.get((False, True), 0) / max(por_hora.get((False, False), 1e-9), 1e-9)
    vesp = por_hora.get((True, True), 0) / max(por_hora.get((False, True), 1e-9), 1e-9)
    return [
        _item(8, "Congestionamentos por hora nos picos dos dias úteis ÷ demais horas", pico, 2.5),
        _item(8, "No pico: véspera de feriado ÷ dia útil comum", vesp, 1.25),
    ]


def disponibilidade(db: Session, quando) -> pd.DataFrame:
    """Fração dos equipamentos fixos em operação por região numa data (pelo último histórico antes dela)."""
    return _df(db, """
        WITH u AS (
            SELECT DISTINCT ON (h.equipamento_id) h.equipamento_id, h.situacao_nova s
            FROM historico_situacao h WHERE h.em < :q ORDER BY h.equipamento_id, h.em DESC)
        SELECT l.regiao, avg((u.s = 'operacional')::int) disp
        FROM u JOIN localizacao l ON l.equipamento_id = u.equipamento_id
        JOIN equipamento e ON e.id = u.equipamento_id JOIN tipo_equipamento t ON t.id = e.tipo_id
        WHERE t.mobilidade = 'fixo' AND l.regiao IS NOT NULL
          AND u.s IN ('operacional', 'mau_funcionamento', 'em_manutencao')
        GROUP BY 1""", q=quando).set_index("regiao").disp.astype(float)


def p11_regiao(db: Session, inicio, fim) -> dict:
    antes = disponibilidade(db, inicio + timedelta(days=120))
    depois = disponibilidade(db, fim)
    queda = (antes - depois) * 100
    leste = queda[P.REGIAO_SEM_PREVENTIVA]
    outras = queda.drop(P.REGIAO_SEM_PREVENTIVA).median()
    return _item(11, f"Queda da disponibilidade (pontos percentuais) em {P.REGIAO_SEM_PREVENTIVA} menos a mediana das outras",
                 leste - outras, 1.5,
                 f"{P.REGIAO_SEM_PREVENTIVA}: {antes[P.REGIAO_SEM_PREVENTIVA]:.1%} → {depois[P.REGIAO_SEM_PREVENTIVA]:.1%}; "
                 f"outras: queda mediana de {outras:.1f} pontos")


def p12_anomalias(db: Session) -> list[dict]:
    anom = db.execute(text("SELECT valor FROM estado_preditivo WHERE chave = 'anomalias_plantadas'")).scalar() or []
    achadas_r = achadas_c = total_r = total_c = 0
    for a in anom:
        desde = pd.Timestamp(a["desde"], tz="America/Sao_Paulo")
        df = _df(db, """SELECT em AT TIME ZONE 'America/Sao_Paulo' em, valor FROM serie_equipamento_hora
                        WHERE equipamento_id = :e AND metrica = :m ORDER BY em""", e=a["equipamento_id"], m=a["metrica"])
        df["em"] = pd.to_datetime(df.em).dt.tz_localize("America/Sao_Paulo")
        antes, depois = df[df.em < desde], df[df.em >= desde]
        if a["tipo"] == "queda":
            total_r += 1
            achadas_r += depois.valor.mean() < 0.5 * antes.valor.mean()
        else:
            total_c += 1
            noite = depois[depois.em.dt.hour.isin(a["horas"])]
            achadas_c += noite.valor.mean() < 20 and antes[antes.em.dt.hour.isin(a["horas"])].valor.mean() > 50
    return [
        _item(12, "Radares com queda de infrações visível na série", achadas_r / max(total_r, 1), 1.0, f"{achadas_r} de {total_r}"),
        _item(12, "Câmeras que caem toda noite visíveis na série", achadas_c / max(total_c, 1), 1.0, f"{achadas_c} de {total_c}"),
    ]


def verificar(db: Session) -> list[dict]:
    inicio, fim = periodo(db)
    i, f = inicio.to_pydatetime(), fim.to_pydatetime()
    itens = [p1_centro_noite(db), *p2_chuva(db), p3_eventos(db), *p4_marca(db, i, f), p5_calor(db, i, f),
             *p6_furtos(db, i, f), p7_atraso(db, i, f), *p8_congestionamento(db), p11_regiao(db, i, f), *p12_anomalias(db)]
    return itens
