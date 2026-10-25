"""Calendário da cidade: feriados, vésperas, período escolar e dia de pagamento.

Funciona sem internet: os feriados nacionais e estaduais vêm da biblioteca `holidays`;
os municipais de São Paulo e os pontos facultativos que mudam a cidade (Carnaval) estão aqui.
"""

from datetime import date, timedelta

import holidays
from dateutil.easter import easter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Calendario


def _municipais(ano: int) -> dict[date, tuple[str, str]]:
    pascoa = easter(ano)
    return {
        date(ano, 1, 25): ("Aniversário de São Paulo", "municipal"),
        pascoa + timedelta(days=60): ("Corpus Christi", "municipal"),
        pascoa - timedelta(days=48): ("Carnaval (segunda)", "facultativo"),
        pascoa - timedelta(days=47): ("Carnaval (terça)", "facultativo"),
    }


def feriados(anos: list[int]) -> dict[date, tuple[str, str]]:
    """Data -> (nome, esfera). Esfera: nacional, estadual, municipal ou facultativo."""
    nac = holidays.Brazil(years=anos)
    sp = holidays.Brazil(subdiv="SP", years=anos)
    saida: dict[date, tuple[str, str]] = {}
    for d, nome in sp.items():
        saida[d] = (nome, "nacional" if d in nac else "estadual")
    for ano in anos:
        for d, v in _municipais(ano).items():
            saida.setdefault(d, v)
    return saida


def _escolar(d: date) -> bool:
    """Rede pública de SP, aproximado: de fevereiro a meados de julho e de agosto a meados de dezembro."""
    if d.weekday() >= 5:
        return False
    inicio_1 = date(d.year, 2, 1)
    while inicio_1.weekday() != 0:
        inicio_1 += timedelta(days=1)
    return inicio_1 <= d <= date(d.year, 7, 10) or date(d.year, 8, 1) <= d <= date(d.year, 12, 18)


def dias(inicio: date, fim: date) -> list[dict]:
    """Linhas do calendário entre inicio e fim (inclusive). Função pura."""
    anos = list(range(inicio.year - 1, fim.year + 2))
    fer = feriados(anos)

    def util(x: date) -> bool:
        return x.weekday() < 5 and x not in fer

    # 5º dia útil de cada mês (segunda a sexta, sem feriados)
    pagamento: set[date] = set()
    for ano in anos:
        for mes in range(1, 13):
            x, n = date(ano, mes, 1), 0
            while True:
                if util(x):
                    n += 1
                    if n == 5:
                        pagamento.add(x)
                        break
                x += timedelta(days=1)

    linhas = []
    d = inicio
    while d <= fim:
        nome, esfera = fer.get(d, (None, None))
        linhas.append({
            "data": d, "dia_semana": d.weekday(), "feriado": d in fer, "feriado_nome": nome, "feriado_esfera": esfera,
            "vespera_feriado": d not in fer and (d + timedelta(days=1)) in fer,
            "periodo_escolar": _escolar(d) and d not in fer, "dia_pagamento": d in pagamento,
        })
        d += timedelta(days=1)
    return linhas


def garantir(db: Session, inicio: date, fim: date) -> int:
    """Grava (ou atualiza) o calendário no período. Idempotente."""
    linhas = dias(inicio, fim)
    if not linhas:
        return 0
    stmt = insert(Calendario).values(linhas)
    stmt = stmt.on_conflict_do_update(
        index_elements=["data"],
        set_={c: stmt.excluded[c] for c in linhas[0] if c != "data"},
    )
    db.execute(stmt)
    return len(linhas)


def periodo(db: Session, inicio: date, fim: date) -> list[Calendario]:
    existentes = db.scalar(select(Calendario.data).where(Calendario.data == fim))
    if existentes is None or db.get(Calendario, inicio) is None:
        garantir(db, inicio, fim)
        db.flush()
    return list(db.scalars(select(Calendario).where(Calendario.data.between(inicio, fim)).order_by(Calendario.data)))
