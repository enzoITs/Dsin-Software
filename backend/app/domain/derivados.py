"""Recalcula o que deriva do cadastro: score e status de manutenção.

Roda para um equipamento (depois de cada evento) ou para todos (job periódico),
com poucas consultas agregadas em vez de uma por equipamento. Os alertas automáticos
(falha silenciosa, manutenção vencida e próxima) são do motor de interpretação (Parte 2):
para poucos equipamentos ele roda aqui mesmo; para todos, no verificador a cada 30 s.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, true, update
from sqlalchemy.orm import Session

from app.domain import limites, saude, silencio
from app.models import (
    Equipamento,
    HistoricoSituacao,
    PlanoManutencao,
    RegistroManutencao,
    TipoEquipamento,
)
from app.models.enums import Situacao, StatusManutencao

DIAS_AVISO_MANUTENCAO = 7


def status_manutencao(proxima: date | None, hoje: date) -> StatusManutencao:
    if proxima is None:
        return StatusManutencao.em_dia
    if proxima < hoje:
        return StatusManutencao.vencida
    if proxima <= hoje + timedelta(days=DIAS_AVISO_MANUTENCAO):
        return StatusManutencao.proxima
    return StatusManutencao.em_dia


def _por_equip(db: Session, stmt) -> dict:
    return dict(db.execute(stmt).all())


def recalcular(db: Session, ids: list[int] | None = None, agora: datetime | None = None) -> dict:
    agora = agora or datetime.now(timezone.utc)
    hoje = agora.date()

    q = select(
        Equipamento.id,
        Equipamento.situacao,
        Equipamento.dispositivo_iot_id,
        Equipamento.ultimo_sinal_em,
        Equipamento.criado_em,
        Equipamento.data_instalacao,
        Equipamento.codigo_interno,
        TipoEquipamento.intervalo_sinal_esperado_min,
    ).join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
    if ids is not None:
        q = q.where(Equipamento.id.in_(ids))
    linhas = db.execute(q.order_by(Equipamento.id)).all()  # ordem fixa: evita deadlock com a telemetria
    if not linhas:
        return {"recalculados": 0}
    alvo = [l.id for l in linhas]

    def filtro(col):
        return col.in_(alvo) if ids is not None else true()

    falhas = _por_equip(
        db,
        select(HistoricoSituacao.equipamento_id, func.count())
        .where(
            HistoricoSituacao.situacao_nova == Situacao.mau_funcionamento,
            HistoricoSituacao.em >= agora - timedelta(days=90),
            filtro(HistoricoSituacao.equipamento_id),
        )
        .group_by(HistoricoSituacao.equipamento_id)
    )
    furtos = _por_equip(
        db,
        select(HistoricoSituacao.equipamento_id, func.count())
        .where(
            HistoricoSituacao.situacao_nova == Situacao.furtado,
            HistoricoSituacao.em >= agora - timedelta(days=365),
            filtro(HistoricoSituacao.equipamento_id),
        )
        .group_by(HistoricoSituacao.equipamento_id)
    )
    fator = limites.carregar(db)["silencio_fator"]
    proximas = _por_equip(
        db,
        select(PlanoManutencao.equipamento_id, func.min(PlanoManutencao.proxima_data))
        .where(PlanoManutencao.ativo.is_(True), filtro(PlanoManutencao.equipamento_id))
        .group_by(PlanoManutencao.equipamento_id)
    )
    ultimas = _por_equip(
        db,
        select(RegistroManutencao.equipamento_id, func.max(RegistroManutencao.executada_em))
        .where(filtro(RegistroManutencao.equipamento_id))
        .group_by(RegistroManutencao.equipamento_id)
    )
    atualizacoes = []
    for l in linhas:
        proxima = proximas.get(l.id)
        ativo = l.situacao not in (Situacao.desativado, Situacao.nao_instalado)
        st_manut = status_manutencao(proxima, hoje) if ativo else StatusManutencao.em_dia
        atraso = (hoje - proxima).days if st_manut == StatusManutencao.vencida else 0
        sem_sinal = silencio.esta_silencioso(
            l.situacao,
            bool(l.dispositivo_iot_id),
            l.ultimo_sinal_em or l.criado_em,
            l.intervalo_sinal_esperado_min,
            agora,
            fator,
        )
        score, motivos = saude.calcular(
            saude.FatosSaude(
                situacao=l.situacao,
                falhas_90d=falhas.get(l.id, 0),
                furtos_365d=furtos.get(l.id, 0),
                dias_manutencao_atrasada=atraso,
                sem_sinal=sem_sinal,
                tem_dispositivo_iot=bool(l.dispositivo_iot_id),
                data_instalacao=l.data_instalacao,
                ultima_manutencao=ultimas.get(l.id),
            ),
            hoje,
        )
        atualizacoes.append(
            {"id": l.id, "score_saude": score, "score_motivos": motivos, "status_manutencao": st_manut}
        )

    db.execute(update(Equipamento), atualizacoes)
    res = {"recalculados": len(atualizacoes)}
    if ids is not None:
        from app.services import motor

        db.flush()
        res.update(motor.verificar_equipamentos(db, alvo, agora))
    return res
