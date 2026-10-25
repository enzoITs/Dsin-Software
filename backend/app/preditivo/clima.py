"""Clima por hora: histórico sintético coerente com a estação e previsão editável.

O clima de cada dia é sorteado com uma semente que depende só da data (e da semente geral),
então o histórico gerado e a previsão "padrão" de um dia futuro são o mesmo dia: quando o
gerador em modo contínuo chegar lá, o tempo que "acontece" é o que estava previsto, a menos
que o operador tenha editado a previsão.
"""

import math
import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import ClimaHora

FUSO = ZoneInfo("America/Sao_Paulo")

# Normais aproximadas de São Paulo por mês: temperatura média (°C) e chuva do mês (mm).
TEMP_MEDIA = [23.0, 23.3, 22.6, 20.8, 18.4, 17.4, 16.9, 18.0, 18.8, 20.0, 21.0, 22.2]
CHUVA_MES = [290, 250, 210, 90, 75, 55, 45, 40, 85, 125, 145, 200]
DIAS_CHUVA = [18, 15, 14, 9, 8, 6, 5, 5, 8, 11, 13, 16]


def _rng(d: date, semente: int) -> random.Random:
    return random.Random(semente * 1_000_003 + d.toordinal())


def dia(d: date, semente: int = 42) -> list[dict]:
    """24 horas do dia `d` (hora local), em UTC. Função pura e determinística."""
    r = _rng(d, semente)
    m = d.month - 1
    media = TEMP_MEDIA[m] + r.gauss(0, 2.2)
    # Ondas de calor de vez em quando no verão e na primavera (radares sofrem acima de 32 °C).
    if m in (0, 1, 9, 10, 11) and r.random() < 0.12:
        media += r.uniform(4, 7)
    amplitude = r.uniform(3.5, 6.0)
    chove = r.random() < DIAS_CHUVA[m] / 30
    total = r.gammavariate(1.6, CHUVA_MES[m] / max(1, DIAS_CHUVA[m]) / 1.6) if chove else 0.0
    # Verão: pancada de fim de tarde. Inverno: chuva espalhada.
    pico = r.choice([15, 16, 17, 18]) if m in (0, 1, 2, 9, 10, 11) else r.randint(6, 20)
    duracao = r.randint(2, 4) if m in (0, 1, 2, 9, 10, 11) else r.randint(3, 8)
    tempestade = chove and total > 35
    horas = []
    for h in range(24):
        temp = media + amplitude * math.cos((h - 15) / 24 * 2 * math.pi) + r.gauss(0, 0.4)
        chuva = 0.0
        if chove and pico <= h < pico + duracao:
            chuva = total / duracao * r.uniform(0.6, 1.4)
            temp -= min(4, chuva / 4)
        local = datetime(d.year, d.month, d.day, h, tzinfo=FUSO)
        horas.append({
            "em": local.astimezone(timezone.utc), "temperatura_c": round(temp, 1), "chuva_mm": round(chuva, 1),
            "alerta_tempestade": bool(tempestade and chuva > 0),
        })
    return horas


def hora_cheia(t: datetime) -> datetime:
    return t.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def gravar(db: Session, cidade_id: int, linhas: list[dict], previsao: bool, sobrescrever_editadas: bool = False,
           editado_por: str | None = None) -> int:
    if not linhas:
        return 0
    valores = [{"cidade_id": cidade_id, "previsao": previsao, "editado_por": editado_por, **x} for x in linhas]
    stmt = insert(ClimaHora).values(valores)
    campos = {c: stmt.excluded[c] for c in ("temperatura_c", "chuva_mm", "alerta_tempestade", "previsao", "editado_por")}
    where = None if sobrescrever_editadas else ClimaHora.editado_por.is_(None)
    stmt = stmt.on_conflict_do_update(index_elements=["cidade_id", "em"], set_=campos, where=where)
    db.execute(stmt)
    return len(valores)


def garantir_previsao(db: Session, cidade_id: int, agora: datetime, horas: int = 72, semente: int = 42) -> int:
    """Preenche as próximas horas que ainda não têm previsão com o clima padrão do dia."""
    inicio = hora_cheia(agora)
    fim = inicio + timedelta(hours=horas)
    tem = set(db.scalars(select(ClimaHora.em).where(ClimaHora.cidade_id == cidade_id, ClimaHora.em.between(inicio, fim))))
    linhas = []
    d = inicio.astimezone(FUSO).date()
    while datetime(d.year, d.month, d.day, tzinfo=FUSO) <= fim:
        linhas += [x for x in dia(d, semente) if inicio <= x["em"] <= fim and x["em"] not in tem]
        d += timedelta(days=1)
    return gravar(db, cidade_id, linhas, previsao=True)


def previsao(db: Session, cidade_id: int, agora: datetime, horas: int = 72) -> list[ClimaHora]:
    garantir_previsao(db, cidade_id, agora, horas)
    db.flush()
    inicio = hora_cheia(agora)
    return list(db.scalars(
        select(ClimaHora).where(ClimaHora.cidade_id == cidade_id, ClimaHora.em >= inicio,
                                ClimaHora.em <= inicio + timedelta(hours=horas)).order_by(ClimaHora.em)
    ))


def editar(db: Session, cidade_id: int, inicio: datetime, fim: datetime, usuario: str, *,
           chuva_mm: float | None = None, temperatura_c: float | None = None,
           alerta_tempestade: bool | None = None) -> int:
    """Muda a previsão de todas as horas entre inicio e fim ("amanhã: chuva forte à tarde")."""
    garantir_previsao(db, cidade_id, inicio, int((fim - inicio).total_seconds() // 3600) + 1)
    db.flush()
    linhas = list(db.scalars(select(ClimaHora).where(
        ClimaHora.cidade_id == cidade_id, ClimaHora.em >= hora_cheia(inicio), ClimaHora.em < fim)))
    for c in linhas:
        if chuva_mm is not None:
            c.chuva_mm = chuva_mm
        if temperatura_c is not None:
            c.temperatura_c = temperatura_c
        if alerta_tempestade is not None:
            c.alerta_tempestade = alerta_tempestade
        c.previsao = True
        c.editado_por = usuario
    return len(linhas)
