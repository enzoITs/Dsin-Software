"""Histórico sintético da cidade: eventos, escala de agentes, ocorrências e séries de equipamentos.

Padrões 1, 2, 3, 6 (vandalismo e furtos viram ocorrência), 8 e 12. Tudo é sorteado dia a dia com
uma semente que depende só da semente geral e da data, então gerar o histórico de uma vez ou
hora a hora no modo contínuo dá o mesmo resultado (com o mesmo clima e os mesmos eventos).
"""

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import numpy as np
import shapely
from shapely import wkb
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Bairro, ClimaHora, EventoCidade, Regiao
from app.models.enums import TipoEvento
from app.preditivo import calendario, clima
from app.preditivo import padroes as P

FUSO = clima.FUSO

# ---------------------------------------------------------------- locais de eventos

# nome, lat, lon, capacidade, tipos possíveis
LOCAIS = [
    ("Estádio do Pacaembu", -23.5475, -46.6650, 40_000, ("jogo", "show")),
    ("Allianz Parque", -23.5275, -46.6783, 43_000, ("jogo", "show")),
    ("Estádio do Morumbi", -23.6000, -46.7200, 66_000, ("jogo", "show")),
    ("Neo Química Arena", -23.5453, -46.4742, 47_000, ("jogo", "show")),
    ("Anhembi", -23.5160, -46.6380, 30_000, ("show", "feira")),
    ("Expo Center Norte", -23.5130, -46.6160, 15_000, ("feira",)),
    ("Vale do Anhangabaú", -23.5450, -46.6370, 25_000, ("show", "manifestacao")),
    ("Avenida Paulista (MASP)", -23.5614, -46.6559, 50_000, ("manifestacao",)),
    ("Parque Ibirapuera", -23.5874, -46.6576, 20_000, ("show", "feira")),
]
ESTADIOS = [i for i, x in enumerate(LOCAIS) if "jogo" in x[4]]
PALCOS = [i for i, x in enumerate(LOCAIS) if "show" in x[4]]
FEIRAS = [i for i, x in enumerate(LOCAIS) if "feira" in x[4]]
ATOS = [i for i, x in enumerate(LOCAIS) if "manifestacao" in x[4]]
TIMES = ["Palmeiras", "Corinthians", "São Paulo", "Santos", "Flamengo", "Grêmio", "Atlético-MG", "Fluminense",
         "Internacional", "Bahia", "Cruzeiro", "Botafogo"]
ARTISTAS = ["Turnê Nacional", "Festival de Verão", "Banda Internacional", "Sertanejo ao Vivo", "Noite do Samba",
            "Festival de Rock", "Show Gospel", "Orquestra na Praça"]


def eventos_dia(d: date, semente: int) -> list[dict]:
    """Eventos programados do dia (determinístico). Horários locais convertidos para UTC."""
    r = np.random.default_rng(P.chave("eventos", semente, d.isoformat()))
    dow = d.weekday()
    saida = []

    def novo(local: int, nome: str, tipo: str, h0: float, horas: float, publico: int) -> None:
        nome_l, lat, lon, cap, _ = LOCAIS[local]
        ini = datetime(d.year, d.month, d.day, int(h0), int(round((h0 % 1) * 60)), tzinfo=FUSO)
        saida.append({"nome": nome, "tipo": TipoEvento(tipo), "local_nome": nome_l, "lon": lon, "lat": lat,
                      "inicio_em": ini.astimezone(timezone.utc), "fim_em": (ini + timedelta(hours=horas)).astimezone(timezone.utc),
                      "publico_estimado": int(min(cap, publico)), "raio_influencia_m": P.RAIO_EVENTO_M})

    if (dow in (2, 3) and r.random() < 0.45) or (dow in (5, 6) and r.random() < 0.8):
        a, b = r.choice(len(TIMES), 2, replace=False)
        h0 = 21.5 if dow in (2, 3) else float(r.choice([16.0, 18.5]))
        novo(int(r.choice(ESTADIOS)), f"{TIMES[a]} x {TIMES[b]}", "jogo", h0, 2.0, int(r.integers(12_000, 46_000)))
    if dow in (4, 5) and r.random() < 0.12:
        novo(int(r.choice(PALCOS)), str(r.choice(ARTISTAS)), "show", 20.0, 3.5, int(r.integers(6_000, 60_000)))
    if r.random() < 0.10:
        novo(int(r.choice(FEIRAS)), str(r.choice(["Feira de Artesanato", "Feira do Livro", "Salão de Negócios",
                                                    "Feira Gastronômica"])), "feira", 10.0, 9.0, int(r.integers(2_000, 9_500)))
    if r.random() < 0.05:
        novo(int(r.choice(ATOS)), "Manifestação", "manifestacao", 14.0, 4.0, int(r.integers(2_000, 30_000)))
    return saida


def evento_demo(data_referencia: date) -> dict:
    """Show grande no Pacaembu (Centro) na primeira sexta depois da data de referência: roteiro da demonstração."""
    d = data_referencia + timedelta(days=1)
    while d.weekday() != 4:
        d += timedelta(days=1)
    nome_l, lat, lon, _, _ = LOCAIS[0]
    ini = datetime(d.year, d.month, d.day, 20, 0, tzinfo=FUSO)
    return {"nome": "Grande show no Pacaembu", "tipo": TipoEvento.show, "local_nome": nome_l, "lon": lon, "lat": lat,
            "inicio_em": ini.astimezone(timezone.utc), "fim_em": (ini + timedelta(hours=3, minutes=30)).astimezone(timezone.utc),
            "publico_estimado": 38_000, "raio_influencia_m": P.RAIO_EVENTO_M}


# ---------------------------------------------------------------- contexto da cidade


@dataclass
class Contexto:
    semente: int
    cidade_id: int
    bairros: list[dict]          # {id, nome, regiao, regiao_id, peso, geom}
    regioes: dict[str, int]      # nome -> id
    pontos: list[np.ndarray]     # pontos sorteados dentro de cada bairro (lon, lat)
    equipes: list[dict]          # {equipe, orgao_id, regiao, regiao_id, agentes, turno, folgas}


TURNOS = {"manha": (6, 8), "tarde": (14, 8), "noite": (22, 8)}


def carregar(db: Session, semente: int) -> Contexto:
    cidade_id = db.scalar(text("SELECT id FROM cidade WHERE tem_lista_bairros ORDER BY id LIMIT 1"))
    regioes = {nome: rid for rid, nome in db.execute(select(Regiao.id, Regiao.nome).where(Regiao.cidade_id == cidade_id))}
    bairros, pontos = [], []
    for bid, nome, reg, g in db.execute(
            select(Bairro.id, Bairro.nome, Bairro.regiao, func.ST_AsBinary(Bairro.geom))
            .where(Bairro.cidade_id == cidade_id, Bairro.geom.is_not(None)).order_by(Bairro.id)):
        geom = wkb.loads(bytes(g))
        bairros.append({"id": bid, "nome": nome, "regiao": reg, "regiao_id": regioes.get(reg),
                        "peso": P.peso_bairro(nome, reg), "geom": geom})
        r = np.random.default_rng(P.chave("pontos", semente, nome))
        x0, y0, x1, y1 = geom.bounds
        pts = np.empty((0, 2))
        while len(pts) < 3000:
            c = np.column_stack([r.uniform(x0, x1, 4000), r.uniform(y0, y1, 4000)])
            pts = np.vstack([pts, c[shapely.contains_xy(geom, c[:, 0], c[:, 1])]])
        pontos.append(pts[:3000])

    # Equipes: agentes agrupados pela equipe; região onde está a maioria; turno e folgas fixos pela equipe.
    linhas = db.execute(text("""
        SELECT a.equipe, mode() WITHIN GROUP (ORDER BY a.orgao_id) orgao_id,
               mode() WITHIN GROUP (ORDER BY a.regiao) regiao, count(*) n
        FROM agente a WHERE a.equipe IS NOT NULL GROUP BY a.equipe ORDER BY a.equipe
    """)).all()
    equipes = []
    nomes_reg = sorted(regioes)
    for eq, org, reg, n in linhas:
        r = np.random.default_rng(P.chave("equipe", semente, eq))
        reg = reg if reg in regioes else (nomes_reg[int(r.integers(len(nomes_reg)))] if nomes_reg else None)
        if reg is None:
            continue
        turno = str(r.choice(list(TURNOS), p=[0.4, 0.35, 0.25]))
        folgas = tuple(int(x) for x in r.choice(7, 2, replace=False))
        equipes.append({"equipe": eq, "orgao_id": org, "regiao": reg, "regiao_id": regioes[reg],
                        "agentes": max(2, int(round(n * 0.7))), "turno": turno, "folgas": folgas})
    return Contexto(semente, cidade_id, bairros, regioes, pontos, equipes)


def escala_dia(ctx: Contexto, d: date) -> list[dict]:
    """Turnos do dia. A escala segue o efetivo de cada região, não a demanda: é isso que P4 corrige."""
    saida = []
    for e in ctx.equipes:
        if d.weekday() in e["folgas"]:
            continue
        h0, dur = TURNOS[e["turno"]]
        ini = datetime(d.year, d.month, d.day, h0, tzinfo=FUSO)
        saida.append({"equipe": e["equipe"], "orgao_id": e["orgao_id"], "regiao_id": e["regiao_id"],
                      "inicio_em": ini.astimezone(timezone.utc), "fim_em": (ini + timedelta(hours=dur)).astimezone(timezone.utc),
                      "agentes": e["agentes"], "origem": "escala"})
    return saida


def agentes_por_hora(ctx: Contexto, d: date) -> np.ndarray:
    """Agentes em turno por região (na ordem de ctx.bairros) e hora local do dia d."""
    por_reg = {rid: np.zeros(24) for rid in ctx.regioes.values()}
    for dia in (d - timedelta(days=1), d):  # turno da noite anterior entra na madrugada
        for t in escala_dia(ctx, dia):
            ini = t["inicio_em"].astimezone(FUSO)
            for k in range(int((t["fim_em"] - t["inicio_em"]).total_seconds() // 3600)):
                h = ini + timedelta(hours=k)
                if h.date() == d:
                    por_reg[t["regiao_id"]][h.hour] += t["agentes"]
    return np.array([por_reg.get(b["regiao_id"], np.zeros(24)) for b in ctx.bairros])


def media_agentes(ctx: Contexto) -> np.ndarray:
    """Média de agentes por hora de cada região numa semana típica (para o viés de registro)."""
    base = date(2024, 1, 1)
    tot = sum(agentes_por_hora(ctx, base + timedelta(days=k)) for k in range(7))
    return tot.mean(axis=1) / 7


# ---------------------------------------------------------------- ocorrências


def _ponto_no_raio(r: np.random.Generator, lon: float, lat: float, raio_m: float) -> tuple[float, float]:
    ang = r.uniform(0, 2 * math.pi)
    dist = raio_m * math.sqrt(r.random())
    return (lon + dist * math.cos(ang) / (111_320 * math.cos(math.radians(lat))), lat + dist * math.sin(ang) / 110_540)


def _bairro_de(ctx: Contexto, lon: float, lat: float) -> int | None:
    for i, b in enumerate(ctx.bairros):
        if shapely.contains_xy(b["geom"], lon, lat):
            return i
    return None


def ocorrencias_dia(ctx: Contexto, d: date, chuva_h: np.ndarray, cal: dict, eventos: list[dict],
                    agentes_h: np.ndarray, agentes_med: np.ndarray) -> list[dict]:
    """Ocorrências simuladas do dia d (todas as 24 horas locais)."""
    r = np.random.default_rng(P.chave("ocorrencias", ctx.semente, d.isoformat()))
    lam = P.intensidade_dia(ctx.bairros, d.weekday(), cal.get("feriado", False), cal.get("vespera_feriado", False),
                            chuva_h, agentes_h, agentes_med)
    lam *= r.gamma(P.FORMA_RUIDO_DIA, 1 / P.FORMA_RUIDO_DIA, size=(len(ctx.bairros), 1, 1))
    n = r.poisson(lam)
    saida = []
    meia_noite = datetime(d.year, d.month, d.day, tzinfo=FUSO)

    def linha(cat: str, ib: int, quando: datetime, lon: float, lat: float, hora: int) -> dict:
        g = int(r.choice(4, p=P.GRAVIDADE[cat])) + 1
        lo, hi = P.DURACAO_MIN[cat]
        b = ctx.bairros[ib]
        return {"categoria": cat, "gravidade": g, "inicio_em": quando.astimezone(timezone.utc),
                "fim_em": (quando + timedelta(minutes=int(r.integers(lo, hi + 1)))).astimezone(timezone.utc),
                "lon": float(lon), "lat": float(lat), "regiao_id": b["regiao_id"], "bairro_id": b["id"],
                "agentes": int(agentes_h[ib, hora])}

    for ib, h, ic in zip(*np.nonzero(n)):
        cat = P.CATEGORIAS[ic]
        pts = ctx.pontos[ib]
        for _ in range(n[ib, h, ic]):
            lon, lat = pts[int(r.integers(len(pts)))]
            quando = meia_noite + timedelta(hours=int(h), minutes=int(r.integers(0, 60)))
            saida.append(linha(cat, int(ib), quando, lon, lat, int(h)))

    # Padrão 3: eventos grandes geram ocorrências num raio de 2 km, de 2 h antes a 2 h depois.
    cats, pesos = list(P.MIX_EVENTO), list(P.MIX_EVENTO.values())
    for ev in eventos:
        extra = P.extra_evento_hora(ev["publico_estimado"])
        if not extra:
            continue
        ini = ev["inicio_em"] - timedelta(hours=P.HORAS_ANTES_DEPOIS)
        fim = ev["fim_em"] + timedelta(hours=P.HORAS_ANTES_DEPOIS)
        minutos = int((fim - ini).total_seconds() // 60)
        for _ in range(r.poisson(extra * minutos / 60)):
            quando = (ini + timedelta(minutes=int(r.integers(0, minutos)))).astimezone(FUSO)
            if quando.date() != d:
                continue
            lon, lat = _ponto_no_raio(r, ev["lon"], ev["lat"], ev["raio_influencia_m"])
            ib = _bairro_de(ctx, lon, lat)
            if ib is None:
                continue
            saida.append(linha(str(r.choice(cats, p=pesos)), ib, quando, lon, lat, quando.hour))
    return saida


# ---------------------------------------------------------------- séries de equipamentos (padrão 12)

N_RADARES_SERIE = 120
N_CAMERAS_SERIE = 120


def escolher_series(db: Session, semente: int) -> dict[str, list[int]]:
    radares = [i for (i,) in db.execute(text("""
        SELECT e.id FROM equipamento e JOIN tipo_equipamento t ON t.id = e.tipo_id
        WHERE t.prefixo = 'RAD' AND e.situacao = 'operacional' AND e.atributos->>'modalidade' = 'velocidade'
        ORDER BY e.id"""))]
    cameras = [i for (i,) in db.execute(text("""
        SELECT e.id FROM equipamento e JOIN tipo_equipamento t ON t.id = e.tipo_id
        WHERE t.prefixo = 'CAM' AND e.situacao = 'operacional' AND e.dispositivo_iot_id IS NOT NULL ORDER BY e.id"""))]
    r = np.random.default_rng(P.chave("series", semente))
    rad = sorted(int(x) for x in r.choice(radares, min(N_RADARES_SERIE, len(radares)), replace=False)) if radares else []
    cam = sorted(int(x) for x in r.choice(cameras, min(N_CAMERAS_SERIE, len(cameras)), replace=False)) if cameras else []
    return {"radares": rad, "cameras": cam}


def anomalias_plantadas(series: dict[str, list[int]], data_referencia: date) -> list[dict]:
    """Padrão 12: radares que passam a registrar 80% menos e câmeras que caem toda noite."""
    saida = []
    for k, dias in enumerate((2, 9, 25)):
        if k < len(series["radares"]):
            saida.append({"equipamento_id": series["radares"][-(k + 1)], "metrica": "infracoes", "tipo": "queda",
                          "desde": (data_referencia - timedelta(days=dias)).isoformat(), "fator": 0.2})
    for k, dias in enumerate((5, 12, 30)):
        if k < len(series["cameras"]):
            saida.append({"equipamento_id": series["cameras"][-(k + 1)], "metrica": "online_min", "tipo": "cai_a_noite",
                          "desde": (data_referencia - timedelta(days=dias)).isoformat(), "horas": [0, 1, 2, 3, 4]})
    return saida


def series_dia(semente: int, series: dict[str, list[int]], anomalias: list[dict], d: date) -> list[tuple]:
    """(equipamento_id, metrica, em, valor) das 24 horas locais do dia d."""
    r = np.random.default_rng(P.chave("serie", semente, d.isoformat()))
    trafego = P.PERFIL_HORA["ACIDENTE"]
    fds = 0.7 if d.weekday() >= 5 else 1.0
    horas = [datetime(d.year, d.month, d.day, h, tzinfo=FUSO).astimezone(timezone.utc) for h in range(24)]
    anom = {(a["equipamento_id"], a["metrica"]): a for a in anomalias if date.fromisoformat(a["desde"]) <= d}
    saida = []
    for eid in series["radares"]:
        nivel = np.random.default_rng(P.chave("radar", semente, eid)).lognormal(math.log(10), 0.5)
        lam = nivel * trafego * fds
        a = anom.get((eid, "infracoes"))
        if a:
            lam = lam * a["fator"]
        v = r.poisson(lam)
        saida += [(eid, "infracoes", horas[h], float(v[h])) for h in range(24)]
    for eid in series["cameras"]:
        v = np.full(24, 60.0)
        quedas = r.random(24) < 0.004
        v[quedas] = r.integers(0, 50, quedas.sum())
        a = anom.get((eid, "online_min"))
        if a:
            v[a["horas"]] = r.integers(0, 6, len(a["horas"]))
        saida += [(eid, "online_min", horas[h], float(v[h])) for h in range(24)]
    return saida


# ---------------------------------------------------------------- gravação


def copiar_ocorrencias(db: Session, linhas: list[dict]) -> int:
    if not linhas:
        return 0
    cur = db.connection().connection.cursor()
    with cur.copy("COPY ocorrencia (categoria, gravidade, inicio_em, fim_em, geom, regiao_id, bairro_id, origem, "
                  "agentes_presentes_regiao) FROM STDIN") as cp:
        for x in linhas:
            cp.write_row((x["categoria"], x["gravidade"], x["inicio_em"], x["fim_em"],
                          f"SRID=4326;POINT({x['lon']:.6f} {x['lat']:.6f})", x["regiao_id"], x["bairro_id"],
                          "simulada", x["agentes"]))
    return len(linhas)


def copiar_series(db: Session, linhas: list[tuple]) -> int:
    if not linhas:
        return 0
    cur = db.connection().connection.cursor()
    with cur.copy("COPY serie_equipamento_hora (equipamento_id, metrica, em, valor) FROM STDIN") as cp:
        for x in linhas:
            cp.write_row(x)
    return len(linhas)


def gravar_eventos(db: Session, eventos: list[dict]) -> int:
    for ev in eventos:
        db.add(EventoCidade(**{k: v for k, v in ev.items() if k not in ("lon", "lat")},
                            geom=f"SRID=4326;POINT({ev['lon']} {ev['lat']})", simulado=True, criado_por="gerador"))
    return len(eventos)


def gravar_escala(db: Session, turnos: list[dict]) -> int:
    if turnos:
        db.execute(text("""INSERT INTO escala_agente (equipe, orgao_id, regiao_id, inicio_em, fim_em, agentes, origem)
                           VALUES (:equipe, :orgao_id, :regiao_id, :inicio_em, :fim_em, :agentes, :origem)"""), turnos)
    return len(turnos)


def eventos_do_banco(db: Session, d: date) -> list[dict]:
    """Eventos (gerados ou cadastrados) que tocam o dia d, com folga de 2 h dos dois lados."""
    ini = datetime(d.year, d.month, d.day, tzinfo=FUSO) - timedelta(hours=P.HORAS_ANTES_DEPOIS + 1)
    fim = ini + timedelta(hours=24 + 2 * (P.HORAS_ANTES_DEPOIS + 1))
    linhas = db.execute(select(EventoCidade.inicio_em, EventoCidade.fim_em, EventoCidade.publico_estimado,
                               EventoCidade.raio_influencia_m, func.ST_X(EventoCidade.geom), func.ST_Y(EventoCidade.geom))
                        .where(EventoCidade.fim_em >= ini, EventoCidade.inicio_em <= fim)).all()
    return [{"inicio_em": a, "fim_em": b, "publico_estimado": p, "raio_influencia_m": rm, "lon": x, "lat": y}
            for a, b, p, rm, x, y in linhas if x is not None]


def chuva_do_banco(db: Session, cidade_id: int, d: date, semente: int) -> np.ndarray:
    """Chuva por hora local do dia d como está no banco (com as edições do operador); sem linha, o clima padrão."""
    padrao = {x["em"]: x["chuva_mm"] for x in clima.dia(d, semente)}
    ini = datetime(d.year, d.month, d.day, tzinfo=FUSO)
    no_banco = dict(db.execute(select(ClimaHora.em, ClimaHora.chuva_mm).where(
        ClimaHora.cidade_id == cidade_id, ClimaHora.em >= ini, ClimaHora.em < ini + timedelta(days=1))).all())
    horas = sorted(padrao)
    return np.array([no_banco.get(h, padrao[h]) for h in horas])


def calendario_dia(d: date) -> dict:
    return calendario.dias(d, d)[0]
