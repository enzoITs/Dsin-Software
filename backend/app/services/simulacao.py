"""Simular incidente: o jurado provoca o problema e vê a central perceber.

Nada aqui cria alerta direto. Cada simulação gera o sinal (ou a falta dele) que um
equipamento real geraria, e o motor de interpretação faz o resto:

- furto: o radar manda posição a centenas de metros do ponto de instalação;
- falha: o equipamento manda sinal de erro;
- silencio: o equipamento para de mandar sinal (o simulador deixa de enviar);
- queda_energia: vários equipamentos próximos param juntos -> incidente correlacionado;
- degradado: a câmera manda métrica de qualidade baixa;
- sem_agentes: os agentes da região entram em pausa -> região descoberta.

`restaurar` desfaz tudo o que foi simulado e o motor resolve os alertas sozinho.
"""

import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.domain import limites
from app.domain.estados import RegraViolada
from app.models import Agente, Alerta, Equipamento, Localizacao, Regiao, TipoEquipamento
from app.models.enums import Situacao, SituacaoAgente
from app.services import central, motor

ARQUIVO = Path(__file__).resolve().parent.parent.parent / "simulacao_estado.json"
VAZIO = {"parados": [], "sem_metrica": [], "agentes_pausados": [], "deslocados": []}


def ler_estado() -> dict:
    try:
        return {**VAZIO, **json.loads(ARQUIVO.read_text())}
    except (FileNotFoundError, ValueError):
        return dict(VAZIO)


def _gravar(estado: dict) -> None:
    ARQUIVO.write_text(json.dumps({k: sorted(set(v)) for k, v in estado.items()}))


def _candidatos(db: Session, regiao: str, prefixos: list[str] | None, n: int = 1, perto_de: tuple | None = None) -> list[Equipamento]:
    com_problema = select(Alerta.equipamento_id).where(Alerta.resolvido_em.is_(None), Alerta.equipamento_id.is_not(None),
                                                       Alerta.nivel.in_(central.NIVEIS_VISIVEIS))
    stmt = (
        select(Equipamento.id)
        .join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
        .join(Localizacao, Localizacao.equipamento_id == Equipamento.id)
        .where(Localizacao.regiao == regiao, Equipamento.situacao == Situacao.operacional,
               Equipamento.dispositivo_iot_id.is_not(None), Localizacao.geom.is_not(None),
               TipoEquipamento.mobilidade == "fixo", Equipamento.id.not_in(com_problema))
    )
    if prefixos:
        stmt = stmt.where(TipoEquipamento.prefixo.in_(prefixos))
    if perto_de is not None:
        ponto = func.ST_SetSRID(func.ST_MakePoint(*perto_de), 4326)
        stmt = stmt.order_by(Localizacao.geom.op("<->")(ponto))
    else:
        stmt = stmt.order_by(func.random())
    ids = list(db.scalars(stmt.limit(n)))
    return [db.get(Equipamento, i) for i in ids]


def _xy(db: Session, e: Equipamento) -> tuple[float, float]:
    return db.execute(select(func.ST_X(Localizacao.geom), func.ST_Y(Localizacao.geom))
                      .where(Localizacao.equipamento_id == e.id)).one()


def _silenciar(db: Session, equips: list[Equipamento], estado: dict, agora: datetime) -> dict:
    cfg = limites.carregar(db)
    for e in equips:
        estado["parados"].append(e.codigo_interno)
        e.ultimo_sinal_em = agora - timedelta(minutes=e.tipo.intervalo_sinal_esperado_min * cfg["silencio_fator"] + 1)
    db.flush()
    _gravar(estado)
    return motor.verificar_equipamentos(db, [e.id for e in equips], agora, cache={"simulado": True})


def simular(db: Session, tipo: str, regiao: str, quantidade: int = 5, agora: datetime | None = None) -> dict:
    agora = agora or central.agora_utc()
    if db.scalar(select(Regiao.id).where(Regiao.nome == regiao)) is None:
        raise RegraViolada("regiao_invalida", f"Região {regiao} não existe.")
    estado = ler_estado()
    afetados: list[str] = []

    if tipo == "furto":
        eqs = _candidatos(db, regiao, ["RAD"]) or _candidatos(db, regiao, None)
        if not eqs:
            raise RegraViolada("sem_candidato", f"Nenhum equipamento operacional disponível {central_regiao(regiao)}.")
        e = eqs[0]
        x, y = _xy(db, e)
        dist = random.uniform(250, 700)
        ang = random.uniform(0, 2 * math.pi)
        lon = x + dist * math.cos(ang) / (111320 * math.cos(math.radians(y)))
        lat = y + dist * math.sin(ang) / 110540
        estado["deslocados"].append(e.id)
        _gravar(estado)
        motor.processar_sinais(db, [motor.Sinal(e.dispositivo_iot_id, agora, "posicao", lon, lat, {"simulado": True})], agora)
        afetados.append(e.codigo_interno)
    elif tipo == "falha":
        eqs = _candidatos(db, regiao, ["CAM", "RAD"]) or _candidatos(db, regiao, None)
        if not eqs:
            raise RegraViolada("sem_candidato", f"Nenhum equipamento operacional disponível {central_regiao(regiao)}.")
        e = eqs[0]
        motor.processar_sinais(db, [motor.Sinal(e.dispositivo_iot_id, agora, "erro", valores={
            "codigo": random.choice(["E-17 falha de leitura", "E-31 sensor sem resposta", "E-08 tensão instável"]),
            "simulado": True})], agora)
        afetados.append(e.codigo_interno)
    elif tipo == "silencio":
        eqs = _candidatos(db, regiao, ["CAM"]) or _candidatos(db, regiao, None)
        if not eqs:
            raise RegraViolada("sem_candidato", f"Nenhum equipamento operacional disponível {central_regiao(regiao)}.")
        _silenciar(db, eqs[:1], estado, agora)
        afetados.append(eqs[0].codigo_interno)
    elif tipo == "queda_energia":
        semente = _candidatos(db, regiao, ["CAM"]) or _candidatos(db, regiao, None)
        if not semente:
            raise RegraViolada("sem_candidato", f"Nenhum equipamento operacional disponível {central_regiao(regiao)}.")
        eqs = _candidatos(db, regiao, ["CAM", "RAD", "TOT", "CAN"], n=quantidade, perto_de=_xy(db, semente[0]))
        _silenciar(db, eqs, estado, agora)
        afetados += [e.codigo_interno for e in eqs]
    elif tipo == "degradado":
        eqs = _candidatos(db, regiao, ["CAM"])
        if not eqs:
            raise RegraViolada("sem_candidato", f"Nenhuma câmera operacional disponível {central_regiao(regiao)}.")
        e = eqs[0]
        estado["sem_metrica"].append(e.codigo_interno)
        _gravar(estado)
        motor.processar_sinais(db, [motor.Sinal(e.dispositivo_iot_id, agora, "metrica", valores={
            "qualidade": random.choice([22, 31, 38, 44]), "simulado": True})], agora)
        afetados.append(e.codigo_interno)
    elif tipo == "sem_agentes":
        ids = list(db.scalars(select(Agente.id).where(Agente.regiao == regiao,
                                                      Agente.situacao == SituacaoAgente.em_atividade)))
        db.execute(update(Agente).where(Agente.id.in_(ids)).values(situacao=SituacaoAgente.em_pausa))
        estado["agentes_pausados"] += ids
        _gravar(estado)
        db.flush()
        motor.verificar_agentes(db, agora, {"simulado": True})
        afetados.append(f"{len(ids)} agentes")
    else:
        raise RegraViolada("tipo_invalido", "Tipo de incidente desconhecido.")

    alertas = list(db.scalars(select(Alerta).where(Alerta.criado_em >= agora - timedelta(seconds=2),
                                                   Alerta.resolvido_em.is_(None))).unique())
    return {"tipo": tipo, "regiao": regiao, "afetados": afetados,
            "alertas": [central.alerta_json(a) for a in alertas]}


def central_regiao(nome: str) -> str:
    return "no Centro" if nome == "Centro" else f"na região {nome}"


def restaurar(db: Session, agora: datetime | None = None) -> dict:
    agora = agora or central.agora_utc()
    estado = ler_estado()
    codigos = set(estado["parados"]) | set(estado["sem_metrica"])
    if codigos:
        db.execute(update(Equipamento).where(Equipamento.codigo_interno.in_(codigos)).values(ultimo_sinal_em=agora))
    if estado["deslocados"]:
        db.execute(update(Equipamento).where(Equipamento.id.in_(estado["deslocados"])).values(posicao=None, posicao_em=None))
    if estado["agentes_pausados"]:
        db.execute(update(Agente).where(Agente.id.in_(estado["agentes_pausados"]))
                   .values(situacao=SituacaoAgente.em_atividade, posicao_em=agora))
    db.flush()
    n = 0
    for a in db.scalars(select(Alerta).where(Alerta.resolvido_em.is_(None), Alerta.dados["simulado"].astext == "true")).unique():
        if a.resolvido_em is None:
            motor.resolver(db, a, "simulação", "Simulação encerrada", agora)
            n += 1
    for eid in estado["deslocados"]:
        motor.tocar(db, eid)
    if estado["agentes_pausados"]:
        motor.verificar_agentes(db, agora, {})
    _gravar(dict(VAZIO))
    return {"alertas_resolvidos": n, "equipamentos": sorted(codigos), "agentes": len(estado["agentes_pausados"])}
