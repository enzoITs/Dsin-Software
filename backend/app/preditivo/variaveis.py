"""Variáveis (features) da Parte 3, reaproveitadas no treino, no backtest e na previsão.

Duas unidades de previsão:
- equipamento × data de corte (P1): o que se sabe de cada equipamento à meia-noite do dia T;
- bairro × hora (P2): o que se sabe na hora de origem `o` sobre cada hora `t = o + h`, h de 1 a 72.
  Os bairros somados dão as regiões.

**Sem vazamento:** toda variável usa só dados anteriores ao corte (ou à origem). As únicas
exceções são as entradas que existem no futuro de verdade: a previsão do tempo, os eventos
programados, a escala de agentes e o calendário. No histórico sintético, a "previsão do tempo"
de um dia passado é o tempo que fez (previsão perfeita); isso está documentado em decisoes.md.
O teste `tests/test_variaveis.py` muda o banco depois do corte e confere que nada muda.

Os modelos não importam nada de `padroes.py`: as variáveis são genéricas (marca, idade,
temperatura...), e cabe ao modelo descobrir quais combinações importam.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import shapely
from shapely import wkb
from sqlalchemy import text
from sqlalchemy.orm import Session

FUSO = "America/Sao_Paulo"
HORIZONTE_H = 72
JANELAS_FALHA = (7, 30, 90, 180)
CATEGORICAS_EQUIPAMENTO = ["prefixo", "marca", "modelo", "regiao"]
CATEGORICAS_BAIRRO = ["bairro", "regiao"]


def _df(db: Session, sql: str, **p) -> pd.DataFrame:
    r = db.execute(text(sql), p)
    return pd.DataFrame(r.fetchall(), columns=list(r.keys()))


def _utc(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True)


@dataclass
class Fontes:
    """Tabelas brutas carregadas uma vez. Nenhuma função abaixo olha depois do corte."""

    equipamentos: pd.DataFrame
    historico: pd.DataFrame
    registros: pd.DataFrame
    clima: pd.DataFrame          # por hora (UTC), com a hora local
    clima_dia: pd.DataFrame      # por dia local: chuva total, temperatura máxima
    ocorrencias: pd.DataFrame
    eventos: pd.DataFrame
    escala: pd.DataFrame
    bairros: pd.DataFrame
    calendario: pd.DataFrame


def carregar(db: Session) -> Fontes:
    eq = _df(db, """
        SELECT e.id, t.prefixo, lower(trim(e.marca)) marca, e.modelo, e.data_instalacao,
               t.mobilidade::text = 'movel' movel, l.regiao, l.bairro_id,
               (e.atributos->>'velocidade_maxima')::float velocidade_maxima,
               e.atributos->>'modalidade' modalidade,
               (SELECT max(p.periodicidade_dias) FROM plano_manutencao p
                 WHERE p.equipamento_id = e.id AND p.tipo = 'periodica') periodicidade
        FROM equipamento e JOIN tipo_equipamento t ON t.id = e.tipo_id
        LEFT JOIN localizacao l ON l.equipamento_id = e.id
        ORDER BY e.id""")
    eq["data_instalacao"] = pd.to_datetime(eq.data_instalacao)
    hist = _df(db, """SELECT equipamento_id, em, situacao_anterior::text anterior, situacao_nova::text nova
                      FROM historico_situacao ORDER BY em, id""")
    hist["em"] = _utc(hist.em)
    reg = _df(db, """SELECT equipamento_id, executada_em em, plano_id IS NOT NULL preventiva
                     FROM registro_manutencao ORDER BY executada_em""")
    reg["em"] = _utc(reg.em)
    clima = _df(db, """SELECT em, temperatura_c, chuva_mm, alerta_tempestade FROM clima_hora
                       WHERE cidade_id = (SELECT id FROM cidade WHERE tem_lista_bairros ORDER BY id LIMIT 1)
                       ORDER BY em""")
    clima["em"] = _utc(clima.em)
    clima["dia"] = clima.em.dt.tz_convert(FUSO).dt.date
    clima_dia = clima.groupby("dia").agg(chuva=("chuva_mm", "sum"), tmax=("temperatura_c", "max")).reset_index()
    oc = _df(db, """SELECT o.inicio_em em, o.bairro_id, o.regiao_id, o.categoria, o.gravidade
                    FROM ocorrencia o WHERE o.bairro_id IS NOT NULL ORDER BY o.inicio_em""")
    oc["em"] = _utc(oc.em)
    ev = _df(db, """SELECT nome, inicio_em, fim_em, publico_estimado publico, raio_influencia_m raio,
                           ST_X(geom) lon, ST_Y(geom) lat FROM evento_cidade WHERE geom IS NOT NULL""")
    ev["inicio_em"], ev["fim_em"] = _utc(ev.inicio_em), _utc(ev.fim_em)
    esc = _df(db, "SELECT regiao_id, inicio_em, fim_em, agentes FROM escala_agente")
    esc["inicio_em"], esc["fim_em"] = _utc(esc.inicio_em), _utc(esc.fim_em)
    b = _df(db, """SELECT b.id, b.nome bairro, b.regiao, r.id regiao_id, ST_AsBinary(b.geom) geom
                   FROM bairro b JOIN cidade c ON c.id = b.cidade_id AND c.tem_lista_bairros
                   LEFT JOIN regiao r ON r.nome = b.regiao AND r.cidade_id = b.cidade_id
                   WHERE b.geom IS NOT NULL ORDER BY b.id""")
    b["geom"] = [wkb.loads(bytes(g)) for g in b.geom]
    cal = _df(db, "SELECT data, feriado, vespera_feriado, periodo_escolar, dia_pagamento FROM calendario")
    return Fontes(eq, hist, reg, clima, clima_dia, oc, ev, esc, b, cal)


def corte_local(d: date) -> pd.Timestamp:
    """Meia-noite local do dia d: o momento em que a previsão diária é feita."""
    return pd.Timestamp(datetime(d.year, d.month, d.day)).tz_localize(FUSO)


# ---------------------------------------------------------------- equipamento × corte (P1)


def _estado_em(hist: pd.DataFrame, corte: pd.Timestamp) -> pd.Series:
    antes = hist[hist.em < corte]
    return antes.groupby("equipamento_id").nova.last()


def _contar(df: pd.DataFrame, desde: pd.Timestamp, ate: pd.Timestamp) -> pd.Series:
    x = df[(df.em >= desde) & (df.em < ate)]
    return x.groupby("equipamento_id").size()


def equipamentos(f: Fontes, cortes: list[pd.Timestamp], alvo: bool = True) -> pd.DataFrame:
    """Uma linha por equipamento em operação em cada corte, com as variáveis e (se alvo) o que aconteceu depois.

    Alvos: `falha_7d` e `falha_30d` (entrou em mau funcionamento no período a partir do corte).
    """
    falhas = f.historico[f.historico.nova == "mau_funcionamento"][["equipamento_id", "em"]]
    furtos = f.historico[f.historico.nova == "furtado"][["equipamento_id", "em"]].merge(
        f.equipamentos[["id", "bairro_id"]], left_on="equipamento_id", right_on="id")
    prev = f.registros[f.registros.preventiva]
    clima_dia = f.clima_dia.set_index("dia")
    partes = []
    for corte in cortes:
        corte = pd.Timestamp(corte).tz_convert(FUSO) if pd.Timestamp(corte).tzinfo else pd.Timestamp(corte).tz_localize(FUSO)
        estado = _estado_em(f.historico, corte)
        ids = estado[estado == "operacional"].index
        x = f.equipamentos[f.equipamentos.id.isin(ids)].copy()
        x = x[x.data_instalacao.notna() & (x.data_instalacao < corte.tz_localize(None))]
        if x.empty:
            continue
        x["corte"] = corte
        x["idade_dias"] = (corte.tz_localize(None) - x.data_instalacao).dt.days
        for w in JANELAS_FALHA:
            x[f"falhas_{w}d"] = x.id.map(_contar(falhas, corte - pd.Timedelta(days=w), corte)).fillna(0)
        ult_man = f.registros[f.registros.em < corte].groupby("equipamento_id").em.max()
        ult_prev = prev[prev.em < corte].groupby("equipamento_id").em.max()
        x["dias_desde_manutencao"] = (corte - x.id.map(ult_man)).dt.days
        x["dias_desde_preventiva"] = (corte - x.id.map(ult_prev)).dt.days
        x["atraso_preventiva"] = x.dias_desde_preventiva - x.periodicidade
        ult_falha = falhas[falhas.em < corte].groupby("equipamento_id").em.max()
        x["dias_desde_falha"] = (corte - x.id.map(ult_falha)).dt.days

        # Clima: passado observado e próximos 7 dias previstos
        d0 = corte.date()
        passado = clima_dia.loc[[d0 - timedelta(days=k) for k in range(1, 8) if d0 - timedelta(days=k) in clima_dia.index]]
        futuro = clima_dia.loc[[d0 + timedelta(days=k) for k in range(0, 7) if d0 + timedelta(days=k) in clima_dia.index]]
        ontem = clima_dia.chuva.get(d0 - timedelta(days=1), 0.0)
        x["chuva_ontem"] = ontem
        x["chuva_7d"] = passado.chuva.sum()
        x["dias_chuva_forte_7d"] = int((passado.chuva >= 10).sum())
        x["tmax_7d"] = passado.tmax.max() if len(passado) else np.nan
        x["chuva_prevista_7d"] = futuro.chuva.sum()
        x["dias_chuva_forte_previstos_7d"] = int((futuro.chuva >= 10).sum())
        x["tmax_prevista_7d"] = futuro.tmax.max() if len(futuro) else np.nan
        x["dias_calor_previstos_7d"] = int((futuro.tmax > 32).sum())

        fb = furtos[(furtos.em < corte) & (furtos.em >= corte - pd.Timedelta(days=90))].groupby("bairro_id").size()
        x["furtos_bairro_90d"] = x.bairro_id.map(fb).fillna(0)

        if alvo:
            for w in (7, 30):
                x[f"falha_{w}d"] = x.id.map(_contar(falhas, corte, corte + pd.Timedelta(days=w))).fillna(0).gt(0).astype(int)
        partes.append(x)
    if not partes:
        return pd.DataFrame()
    df = pd.concat(partes, ignore_index=True)
    for c in CATEGORICAS_EQUIPAMENTO:
        df[c] = df[c].fillna("?").astype("category")
    return df


COLUNAS_EQUIPAMENTO = [
    "prefixo", "marca", "modelo", "regiao", "movel", "velocidade_maxima", "idade_dias",
    *[f"falhas_{w}d" for w in JANELAS_FALHA], "dias_desde_manutencao", "dias_desde_preventiva",
    "atraso_preventiva", "periodicidade", "dias_desde_falha", "chuva_ontem", "chuva_7d", "dias_chuva_forte_7d",
    "tmax_7d", "chuva_prevista_7d", "dias_chuva_forte_previstos_7d", "tmax_prevista_7d",
    "dias_calor_previstos_7d", "furtos_bairro_90d",
]


# ---------------------------------------------------------------- bairro × hora (P2)


@dataclass
class GradeHoras:
    """Contagens por bairro e hora numa grade contínua de horas (UTC)."""

    inicio: pd.Timestamp
    horas: pd.DatetimeIndex
    contagem: np.ndarray        # bairros × horas
    gravidade: np.ndarray       # soma das gravidades
    bairros: pd.DataFrame


def grade(f: Fontes, inicio: pd.Timestamp, fim: pd.Timestamp) -> GradeHoras:
    horas = pd.date_range(inicio.tz_convert("UTC").floor("h"), fim.tz_convert("UTC").ceil("h"), freq="h")
    pos_b = {bid: i for i, bid in enumerate(f.bairros.id)}
    cont = np.zeros((len(pos_b), len(horas)))
    grav = np.zeros_like(cont)
    oc = f.ocorrencias[(f.ocorrencias.em >= horas[0]) & (f.ocorrencias.em < horas[-1] + pd.Timedelta(hours=1))]
    oc = oc[oc.bairro_id.isin(pos_b)]
    ib = oc.bairro_id.map(pos_b).to_numpy()
    ih = ((oc.em.dt.floor("h") - horas[0]) / pd.Timedelta(hours=1)).astype(int).to_numpy()
    np.add.at(cont, (ib, ih), 1)
    np.add.at(grav, (ib, ih), oc.gravidade.to_numpy())
    return GradeHoras(horas[0], horas, cont, grav, f.bairros)


def _indisponiveis_por_bairro(f: Fontes, origem: pd.Timestamp) -> pd.Series:
    estado = _estado_em(f.historico, origem)
    fixos = f.equipamentos[~f.equipamentos.movel & f.equipamentos.bairro_id.notna()]
    est = fixos.id.map(estado)
    fora = est.isin(["mau_funcionamento", "em_manutencao", "furtado"])
    return fixos[fora].groupby("bairro_id").size()


def _influencia_eventos(f: Fontes, horas: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Público máximo e menor distância (km) de eventos ativos por bairro × hora (janela de 2 h antes e depois)."""
    nb = len(f.bairros)
    publico = np.zeros((nb, len(horas)))
    dist = np.full((nb, len(horas)), 99.0)
    if f.eventos.empty:
        return publico, dist
    for ev in f.eventos.itertuples():
        a = ev.inicio_em - pd.Timedelta(hours=2)
        b = ev.fim_em + pd.Timedelta(hours=2)
        sel = (horas + pd.Timedelta(hours=1) > a) & (horas < b)
        if not sel.any():
            continue
        p = shapely.Point(ev.lon, ev.lat)
        for i, g in enumerate(f.bairros.geom):
            dx = g.distance(p) * 105.0  # graus -> km (aproximado na latitude de São Paulo)
            if dx * 1000 <= ev.raio:
                publico[i, sel] = np.maximum(publico[i, sel], ev.publico)
                dist[i, sel] = np.minimum(dist[i, sel], dx)
    return publico, dist


def _agentes_por_regiao_hora(f: Fontes, horas: pd.DatetimeIndex) -> dict[int, np.ndarray]:
    saida: dict[int, np.ndarray] = {}
    h0 = horas[0]
    for r in f.escala.itertuples():
        i0 = int(np.ceil((r.inicio_em - h0) / pd.Timedelta(hours=1)))
        i1 = int(np.ceil((r.fim_em - h0) / pd.Timedelta(hours=1)))
        i0, i1 = max(i0, 0), min(i1, len(horas))
        if i1 <= i0:
            continue
        arr = saida.setdefault(r.regiao_id, np.zeros(len(horas)))
        arr[i0:i1] += r.agentes
    return saida


def bairro_hora(f: Fontes, origens: list[pd.Timestamp], horizonte: int = HORIZONTE_H, alvo: bool = True,
                g: GradeHoras | None = None, semanas: int = 8) -> pd.DataFrame:
    """Uma linha por bairro × hora prevista, para cada origem. Lags medidos a partir da origem.

    `media_mesma_hora`: média da mesma hora e dia da semana nas `semanas` anteriores (é o baseline de P2).
    Com horizonte de até 72 h, a semana anterior a qualquer hora prevista já passou na origem.
    """
    if horizonte > 168:
        raise ValueError("Horizonte acima de uma semana usaria a semana anterior ainda não observada.")
    origens = [pd.Timestamp(o).tz_convert("UTC").floor("h") for o in origens]
    inicio = min(origens) - pd.Timedelta(days=7 * semanas + 1)
    fim = max(origens) + pd.Timedelta(hours=horizonte + 1)
    g = g or grade(f, inicio, fim)
    nb = len(g.bairros)
    publico, dist = _influencia_eventos(f, g.horas)
    agentes_reg = _agentes_por_regiao_hora(f, g.horas)
    agentes = np.array([agentes_reg.get(r, np.zeros(len(g.horas))) for r in g.bairros.regiao_id])
    clima = f.clima.set_index("em").reindex(g.horas)
    chuva = clima.chuva_mm.to_numpy()
    temp = clima.temperatura_c.to_numpy()
    cal = f.calendario.set_index("data")
    local = g.horas.tz_convert(FUSO)
    datas = local.date
    feriado = np.array([bool(cal.feriado.get(d, False)) for d in datas])
    vespera = np.array([bool(cal.vespera_feriado.get(d, False)) for d in datas])
    hora_local, dow = local.hour.to_numpy(), local.day_of_week.to_numpy()
    acum = np.concatenate([np.zeros((nb, 1)), np.cumsum(g.contagem, axis=1)], axis=1)

    partes = []
    for o in origens:
        io = int((o - g.inicio) / pd.Timedelta(hours=1))
        if io < 168 * semanas:
            raise ValueError(f"Origem precisa de {semanas} semanas de histórico antes dela.")
        it = io + np.arange(horizonte)            # horas previstas: o, o+1h, ... (a hora que começa em o)
        it = it[it < len(g.horas)]
        ind = _indisponiveis_por_bairro(f, o)
        B, T = np.meshgrid(np.arange(nb), it, indexing="ij")
        B, T = B.ravel(), T.ravel()
        anteriores = np.stack([g.contagem[B, T - 168 * k] for k in range(1, semanas + 1)])
        d = {
            "origem": o, "em": g.horas[T], "horizonte_h": T - io + 1,
            "bairro_id": g.bairros.id.to_numpy()[B], "bairro": g.bairros.bairro.to_numpy()[B],
            "regiao": g.bairros.regiao.to_numpy()[B], "regiao_id": g.bairros.regiao_id.to_numpy()[B],
            "hora": hora_local[T], "dia_semana": dow[T], "feriado": feriado[T], "vespera": vespera[T],
            "chuva_mm": chuva[T], "temperatura_c": temp[T],
            "evento_publico": publico[B, T], "evento_dist_km": dist[B, T], "agentes": agentes[B, T],
            "oc_1h_origem": g.contagem[B, io - 1], "oc_24h_origem": acum[B, io] - acum[B, io - 24],
            "oc_168h_origem": acum[B, io] - acum[B, io - 168],
            "oc_semana_anterior": g.contagem[B, T - 168], "media_mesma_hora": anteriores.mean(axis=0),
            "indisponiveis_origem": g.bairros.id.map(ind).fillna(0).to_numpy()[B],
        }
        if alvo:
            d["ocorrencias"] = g.contagem[B, T]
            d["gravidade"] = g.gravidade[B, T]
        partes.append(pd.DataFrame(d))
    df = pd.concat(partes, ignore_index=True)
    for c in CATEGORICAS_BAIRRO:
        df[c] = df[c].fillna("?").astype("category")
    return df


COLUNAS_BAIRRO = [
    "bairro", "regiao", "horizonte_h", "hora", "dia_semana", "feriado", "vespera", "chuva_mm", "temperatura_c",
    "evento_publico", "evento_dist_km", "agentes", "oc_1h_origem", "oc_24h_origem", "oc_168h_origem",
    "oc_semana_anterior", "media_mesma_hora", "indisponiveis_origem",
]


# ---------------------------------------------------------------- disponibilidade diária (P6)


def disponibilidade_diaria(f: Fontes, inicio: date, fim: date) -> pd.DataFrame:
    """Disponibilidade dos equipamentos fixos (operacionais ÷ em serviço) à meia-noite de cada dia, por região.

    Em serviço: operacional, mau funcionamento, em manutenção ou furtado (instalado e não desativado).
    """
    em_servico = {"operacional", "mau_funcionamento", "em_manutencao", "furtado"}
    h = f.historico.merge(f.equipamentos[["id", "regiao", "movel"]], left_on="equipamento_id", right_on="id")
    h = h[~h.movel & h.regiao.notna()]
    h = h.assign(
        d_op=(h.nova == "operacional").astype(int) - (h.anterior == "operacional").astype(int),
        d_serv=h.nova.isin(em_servico).astype(int) - h.anterior.isin(em_servico).astype(int),
        # mudança no dia d vale a partir da meia-noite seguinte
        dia=h.em.dt.tz_convert(FUSO).dt.date + timedelta(days=1),
    )
    dias = pd.date_range(inicio, fim, freq="D").date
    saida = []
    for reg, x in h.groupby("regiao"):
        por_dia = x.groupby("dia")[["d_op", "d_serv"]].sum()
        idx = sorted(set(por_dia.index) | set(dias))
        acum = por_dia.reindex(idx, fill_value=0).cumsum()
        acum = acum.loc[list(dias)]
        saida.append(pd.DataFrame({"dia": list(dias), "regiao": reg, "operacionais": acum.d_op.to_numpy(),
                                   "em_servico": acum.d_serv.to_numpy()}))
    df = pd.concat(saida, ignore_index=True)
    cidade = df.groupby("dia")[["operacionais", "em_servico"]].sum().reset_index().assign(regiao="Cidade")
    df = pd.concat([df, cidade], ignore_index=True)
    df["disponibilidade"] = df.operacionais / df.em_servico.replace(0, np.nan)
    return df
