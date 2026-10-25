"""Máquina de estados do equipamento e as automações de cada mudança.

A tabela TRANSICOES é a regra completa: qualquer transição fora dela é recusada.
Toda mudança grava histórico (com motivo e responsável) na mesma transação.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain import derivados
from app.models import (
    Equipamento,
    HistoricoSituacao,
    OrdemServico,
    PlanoManutencao,
    RegistroManutencao,
)
from app.models.enums import (
    PrioridadeOS,
    Situacao,
    StatusOS,
    TipoPlano,
)

S = Situacao

TRANSICOES: dict[Situacao, set[Situacao]] = {
    S.nao_instalado: {S.operacional, S.desativado},
    S.operacional: {S.mau_funcionamento, S.em_manutencao, S.furtado, S.desativado},
    S.mau_funcionamento: {S.em_manutencao, S.furtado, S.desativado},
    S.em_manutencao: {S.operacional, S.furtado, S.desativado},
    S.furtado: {S.em_manutencao, S.desativado},
    S.desativado: {S.em_manutencao},
}


class RegraViolada(Exception):
    """Erro de regra de negócio, devolvido ao cliente como 422 com código."""

    def __init__(self, codigo: str, mensagem: str, detalhes: list | None = None, status: int = 422):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem
        self.detalhes = detalhes or []
        self.status = status


def transicao_valida(atual: Situacao, nova: Situacao) -> bool:
    return nova in TRANSICOES[atual]


def mudar_situacao(
    db: Session,
    equip: Equipamento,
    nova: Situacao,
    motivo: str,
    usuario: str,
    agora: datetime | None = None,
    recalcular: bool = True,
) -> list[dict]:
    """Aplica a transição e as automações. Devolve eventos para publicar após o commit."""
    agora = agora or datetime.now(timezone.utc)
    atual = equip.situacao
    if not motivo or not motivo.strip():
        raise RegraViolada("motivo_obrigatorio", "Toda mudança de situação exige um motivo.")
    if not usuario or not usuario.strip():
        raise RegraViolada("usuario_obrigatorio", "Toda mudança de situação exige o responsável.")
    if not transicao_valida(atual, nova):
        permitidas = ", ".join(sorted(s.value for s in TRANSICOES[atual]))
        raise RegraViolada(
            "transicao_invalida",
            f"Não é possível ir de '{atual.value}' para '{nova.value}'. Permitidas: {permitidas}.",
        )

    db.add(
        HistoricoSituacao(
            equipamento_id=equip.id,
            situacao_anterior=atual,
            situacao_nova=nova,
            motivo=motivo.strip(),
            usuario=usuario.strip(),
            em=agora,
        )
    )
    equip.situacao = nova
    acoes: list[str] = []

    if atual == S.nao_instalado and nova == S.operacional and equip.data_instalacao is None:
        equip.data_instalacao = agora.date()

    if nova == S.mau_funcionamento:
        db.add(
            PlanoManutencao(
                equipamento_id=equip.id,
                tipo=TipoPlano.imediata,
                proxima_data=agora.date(),
                descricao=f"Manutenção imediata: {motivo.strip()}",
            )
        )
        db.add(
            OrdemServico(
                equipamento_id=equip.id,
                motivo=f"Mau funcionamento: {motivo.strip()}",
                prioridade=PrioridadeOS.alta,
                aberta_em=agora,
            )
        )
        acoes += ["plano_manutencao_imediata_criado", "ordem_servico_aberta"]

    if nova == S.desativado:
        db.execute(
            update(PlanoManutencao)
            .where(PlanoManutencao.equipamento_id == equip.id, PlanoManutencao.ativo.is_(True))
            .values(ativo=False)
        )
        _fechar_ordens(db, equip.id, agora)
        acoes += ["planos_suspensos", "fora_da_disponibilidade"]

    if nova == S.operacional:
        _fechar_ordens(db, equip.id, agora)
        if _garantir_plano_periodico(db, equip, agora.date()):
            acoes.append("plano_periodico_criado")

    db.flush()
    # Parte 2: o motor de interpretação cria ou resolve os alertas desta mudança.
    from app.services import motor

    acoes += motor.ao_mudar_situacao(db, equip, atual, nova, motivo.strip(), usuario.strip(), agora)
    if recalcular:
        derivados.recalcular(db, [equip.id], agora)
        db.refresh(equip)
        acoes.append("score_recalculado")

    evento = {
        "evento": "situacao_alterada",
        "equipamento_id": equip.id,
        "codigo_interno": equip.codigo_interno,
        "dispositivo_iot_id": equip.dispositivo_iot_id,
        "orgao": equip.orgao.sigla if equip.orgao else None,
        "situacao_anterior": atual.value,
        "situacao_nova": nova.value,
        "motivo": motivo.strip(),
        "usuario": usuario.strip(),
        "em": agora.isoformat(),
        "acoes": acoes,
    }
    return [evento]


def registrar_manutencao(
    db: Session,
    equip: Equipamento,
    tecnico: str,
    executada_em: datetime | None = None,
    plano_id: int | None = None,
    descricao: str | None = None,
    resultado: str = "concluida",
    lon: float | None = None,
    lat: float | None = None,
) -> tuple[RegistroManutencao, list[dict]]:
    """Registra o que foi feito e aplica as automações.

    Concluída: volta a operacional (passando por "em manutenção" se veio de falha)
    e calcula a próxima data do plano periódico. Sem conserto: desativa.
    """
    executada_em = executada_em or datetime.now(timezone.utc)
    if resultado not in ("concluida", "sem_conserto"):
        raise RegraViolada("resultado_invalido", "Resultado deve ser 'concluida' ou 'sem_conserto'.")
    if not tecnico or not tecnico.strip():
        raise RegraViolada("tecnico_obrigatorio", "Informe o técnico responsável.")

    plano = None
    if plano_id is not None:
        plano = db.get(PlanoManutencao, plano_id)
        if plano is None or plano.equipamento_id != equip.id:
            raise RegraViolada("plano_invalido", "Plano não pertence a este equipamento.")

    registro = RegistroManutencao(
        equipamento_id=equip.id,
        plano_id=plano_id,
        executada_em=executada_em,
        tecnico=tecnico.strip(),
        descricao=descricao,
        resultado=resultado,
    )
    if lon is not None and lat is not None:
        registro.geom = f"SRID=4326;POINT({lon} {lat})"
    db.add(registro)

    if resultado == "concluida":
        planos = [plano] if plano else list(
            db.scalars(
                select(PlanoManutencao).where(
                    PlanoManutencao.equipamento_id == equip.id,
                    PlanoManutencao.ativo.is_(True),
                    PlanoManutencao.proxima_data <= executada_em.date(),
                )
            )
        )
        for p in planos:
            _avancar_plano(p, executada_em.date())

    eventos: list[dict] = []
    motivo = f"Manutenção registrada por {tecnico.strip()}" + (f": {descricao}" if descricao else "")
    if resultado == "concluida":
        if equip.situacao == S.mau_funcionamento:
            eventos += mudar_situacao(db, equip, S.em_manutencao, motivo, tecnico, executada_em, recalcular=False)
        if equip.situacao == S.em_manutencao:
            eventos += mudar_situacao(db, equip, S.operacional, motivo, tecnico, executada_em, recalcular=False)
        _fechar_ordens(db, equip.id, executada_em)
    else:
        if equip.situacao in (S.operacional, S.mau_funcionamento):
            eventos += mudar_situacao(db, equip, S.em_manutencao, motivo, tecnico, executada_em, recalcular=False)
        if equip.situacao == S.em_manutencao:
            eventos += mudar_situacao(
                db, equip, S.desativado, f"Sem conserto: {descricao or 'sem detalhes'}", tecnico,
                executada_em, recalcular=False,
            )

    db.flush()
    derivados.recalcular(db, [equip.id], executada_em)
    db.refresh(equip)
    return registro, eventos


def _avancar_plano(plano: PlanoManutencao, feito_em: date) -> None:
    if plano.tipo == TipoPlano.periodica and plano.periodicidade_dias:
        plano.proxima_data = feito_em + timedelta(days=plano.periodicidade_dias)
    else:
        plano.ativo = False


def _garantir_plano_periodico(db: Session, equip: Equipamento, hoje: date) -> bool:
    periodo = equip.tipo.periodicidade_padrao_dias if equip.tipo else None
    if not periodo:
        return False
    existe = db.scalar(
        select(PlanoManutencao.id).where(
            PlanoManutencao.equipamento_id == equip.id,
            PlanoManutencao.tipo == TipoPlano.periodica,
            PlanoManutencao.ativo.is_(True),
        )
    )
    if existe:
        return False
    db.add(
        PlanoManutencao(
            equipamento_id=equip.id,
            tipo=TipoPlano.periodica,
            proxima_data=hoje + timedelta(days=periodo),
            periodicidade_dias=periodo,
            descricao="Manutenção preventiva periódica",
        )
    )
    return True


def _fechar_ordens(db: Session, equipamento_id: int, agora: datetime) -> None:
    db.execute(
        update(OrdemServico)
        .where(OrdemServico.equipamento_id == equipamento_id, OrdemServico.status == StatusOS.aberta)
        .values(status=StatusOS.fechada, fechada_em=agora)
    )
