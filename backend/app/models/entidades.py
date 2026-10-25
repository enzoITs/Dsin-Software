from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.models import enums as e


class Base(DeclarativeBase):
    pass


def pg_enum(cls: type, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda x: [m.value for m in x])


class Timestamps:
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Orgao(Timestamps, Base):
    __tablename__ = "orgao"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    sigla: Mapped[str] = mapped_column(String(20), unique=True)


class TipoEquipamento(Timestamps, Base):
    __tablename__ = "tipo_equipamento"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), unique=True)
    # Prefixo do código interno: RAD, CAM, ...
    prefixo: Mapped[str] = mapped_column(String(6), unique=True)
    categoria: Mapped[str] = mapped_column(String(60))
    mobilidade: Mapped[e.Mobilidade] = mapped_column(pg_enum(e.Mobilidade, "mobilidade"))
    icone: Mapped[str] = mapped_column(String(40), default="box")
    schema_atributos: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Silêncio maior que isso, com equipamento operacional, vira alerta.
    intervalo_sinal_esperado_min: Mapped[int] = mapped_column(Integer, default=60)
    # Periodicidade padrão sugerida para o plano de manutenção.
    periodicidade_padrao_dias: Mapped[int | None] = mapped_column(Integer)


class Cidade(Timestamps, Base):
    __tablename__ = "cidade"
    __table_args__ = (UniqueConstraint("nome", "uf"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    uf: Mapped[str] = mapped_column(String(2))
    tem_lista_bairros: Mapped[bool] = mapped_column(Boolean, default=False)
    centro = mapped_column(Geometry("POINT", srid=4326), nullable=True)


class Bairro(Timestamps, Base):
    __tablename__ = "bairro"
    id: Mapped[int] = mapped_column(primary_key=True)
    cidade_id: Mapped[int] = mapped_column(ForeignKey("cidade.id"), index=True)
    nome: Mapped[str] = mapped_column(String(120))
    regiao: Mapped[str | None] = mapped_column(String(60))
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True), nullable=True)
    cidade: Mapped[Cidade] = relationship()


class BaseOperacional(Timestamps, Base):
    __tablename__ = "base"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    orgao_id: Mapped[int] = mapped_column(ForeignKey("orgao.id"))
    cidade_id: Mapped[int] = mapped_column(ForeignKey("cidade.id"))
    endereco: Mapped[str | None] = mapped_column(String(200))
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=True)


class Equipamento(Timestamps, Base):
    __tablename__ = "equipamento"
    __table_args__ = (
        UniqueConstraint("marca", "numero_serie", name="uq_equipamento_marca_serie"),
        Index("ix_equipamento_atributos", "atributos", postgresql_using="gin"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo_interno: Mapped[str] = mapped_column(String(20), unique=True)
    tipo_id: Mapped[int] = mapped_column(ForeignKey("tipo_equipamento.id"), index=True)
    numero_serie: Mapped[str] = mapped_column(String(80))
    marca: Mapped[str] = mapped_column(String(80))
    modelo: Mapped[str] = mapped_column(String(80))
    orgao_id: Mapped[int] = mapped_column(ForeignKey("orgao.id"), index=True)
    dispositivo_iot_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    ultimo_sinal_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    situacao: Mapped[e.Situacao] = mapped_column(
        pg_enum(e.Situacao, "situacao"), default=e.Situacao.nao_instalado, index=True
    )
    data_instalacao: Mapped[date | None] = mapped_column(Date)
    atributos: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    score_saude: Mapped[int] = mapped_column(Integer, default=100, index=True)
    score_motivos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status_manutencao: Mapped[e.StatusManutencao] = mapped_column(
        pg_enum(e.StatusManutencao, "status_manutencao"), default=e.StatusManutencao.em_dia
    )
    # Estado atual vindo da telemetria (Parte 2). A localização do cadastro fica em Localizacao:
    # para fixos é o ponto de instalação; para móveis, a base.
    posicao = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=True)
    posicao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metricas: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    metricas_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tipo: Mapped[TipoEquipamento] = relationship(lazy="joined")
    orgao: Mapped[Orgao] = relationship(lazy="joined")
    localizacao: Mapped["Localizacao | None"] = relationship(
        back_populates="equipamento", uselist=False, lazy="joined", cascade="all, delete-orphan"
    )


class Localizacao(Timestamps, Base):
    __tablename__ = "localizacao"
    equipamento_id: Mapped[int] = mapped_column(
        ForeignKey("equipamento.id", ondelete="CASCADE"), primary_key=True
    )
    cidade_id: Mapped[int] = mapped_column(ForeignKey("cidade.id"))
    rua: Mapped[str] = mapped_column(String(200))
    cep: Mapped[str | None] = mapped_column(String(9))
    bairro_id: Mapped[int | None] = mapped_column(ForeignKey("bairro.id"), index=True)
    referencia: Mapped[str | None] = mapped_column(String(200))
    regiao: Mapped[str | None] = mapped_column(String(60), index=True)
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=True)

    equipamento: Mapped[Equipamento] = relationship(back_populates="localizacao")
    cidade: Mapped[Cidade] = relationship(lazy="joined")
    bairro: Mapped[Bairro | None] = relationship(lazy="joined")


class PlanoManutencao(Timestamps, Base):
    __tablename__ = "plano_manutencao"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipamento_id: Mapped[int] = mapped_column(
        ForeignKey("equipamento.id", ondelete="CASCADE"), index=True
    )
    tipo: Mapped[e.TipoPlano] = mapped_column(pg_enum(e.TipoPlano, "tipo_plano"))
    proxima_data: Mapped[date | None] = mapped_column(Date, index=True)
    periodicidade_dias: Mapped[int | None] = mapped_column(Integer)
    descricao: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class RegistroManutencao(Timestamps, Base):
    __tablename__ = "registro_manutencao"
    id: Mapped[int] = mapped_column(primary_key=True)
    plano_id: Mapped[int | None] = mapped_column(ForeignKey("plano_manutencao.id"))
    equipamento_id: Mapped[int] = mapped_column(
        ForeignKey("equipamento.id", ondelete="CASCADE"), index=True
    )
    executada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tecnico: Mapped[str] = mapped_column(String(120))
    descricao: Mapped[str | None] = mapped_column(Text)
    # "concluida" devolve o equipamento a operacional; "sem_conserto" mantém em manutenção.
    resultado: Mapped[str] = mapped_column(String(30), default="concluida")
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=True)


class OrdemServico(Timestamps, Base):
    __tablename__ = "ordem_servico"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipamento_id: Mapped[int] = mapped_column(
        ForeignKey("equipamento.id", ondelete="CASCADE"), index=True
    )
    motivo: Mapped[str] = mapped_column(Text)
    prioridade: Mapped[e.PrioridadeOS] = mapped_column(pg_enum(e.PrioridadeOS, "prioridade_os"))
    status: Mapped[e.StatusOS] = mapped_column(
        pg_enum(e.StatusOS, "status_os"), default=e.StatusOS.aberta
    )
    aberta_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fechada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HistoricoSituacao(Base):
    """Somente inserção. Um trigger no banco recusa UPDATE e DELETE."""

    __tablename__ = "historico_situacao"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipamento_id: Mapped[int] = mapped_column(ForeignKey("equipamento.id"), index=True)
    situacao_anterior: Mapped[e.Situacao | None] = mapped_column(pg_enum(e.Situacao, "situacao"))
    situacao_nova: Mapped[e.Situacao] = mapped_column(pg_enum(e.Situacao, "situacao"))
    motivo: Mapped[str] = mapped_column(Text)
    usuario: Mapped[str] = mapped_column(String(120))
    em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Agente(Timestamps, Base):
    __tablename__ = "agente"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    matricula: Mapped[str] = mapped_column(String(30), unique=True)
    categoria: Mapped[e.CategoriaAgente] = mapped_column(
        pg_enum(e.CategoriaAgente, "categoria_agente"), index=True
    )
    orgao_id: Mapped[int] = mapped_column(ForeignKey("orgao.id"), index=True)
    equipe: Mapped[str | None] = mapped_column(String(60))
    situacao: Mapped[e.SituacaoAgente] = mapped_column(
        pg_enum(e.SituacaoAgente, "situacao_agente"), default=e.SituacaoAgente.em_atividade
    )
    contato: Mapped[str | None] = mapped_column(String(60))
    veiculo_id: Mapped[int | None] = mapped_column(ForeignKey("equipamento.id"))
    base_id: Mapped[int | None] = mapped_column(ForeignKey("base.id"))
    # Posição em campo (Parte 2), atualizada pela telemetria a cada 15 s.
    posicao = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=True)
    posicao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    regiao: Mapped[str | None] = mapped_column(String(60), index=True)

    orgao: Mapped[Orgao] = relationship(lazy="joined")
    veiculo: Mapped[Equipamento | None] = relationship(lazy="joined")
    base: Mapped[BaseOperacional | None] = relationship(lazy="joined")


class Anexo(Base):
    __tablename__ = "anexo"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipamento_id: Mapped[int] = mapped_column(
        ForeignKey("equipamento.id", ondelete="CASCADE"), index=True
    )
    registro_id: Mapped[int | None] = mapped_column(ForeignKey("registro_manutencao.id"))
    tipo: Mapped[str] = mapped_column(String(30))  # etiqueta, campo
    url: Mapped[str] = mapped_column(String(300))
    em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alerta(Base):
    """Alerta gerado pelo motor de interpretação.

    `chave` identifica o problema (regra + alvo): só existe um alerta não resolvido por chave,
    e repetições aumentam `contador`. `severidade` e `resolvido_em` seguem a Parte 1.
    """

    __tablename__ = "alerta"
    __table_args__ = (
        Index("uq_alerta_chave_aberta", "chave", unique=True, postgresql_where="resolvido_em IS NULL"),
        Index("ix_alerta_regiao_estado", "regiao", "estado"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    equipamento_id: Mapped[int | None] = mapped_column(
        ForeignKey("equipamento.id", ondelete="CASCADE"), index=True
    )
    tipo: Mapped[e.TipoAlerta] = mapped_column(pg_enum(e.TipoAlerta, "tipo_alerta"), index=True)
    severidade: Mapped[e.Severidade] = mapped_column(pg_enum(e.Severidade, "severidade"))
    mensagem: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    chave: Mapped[str] = mapped_column(String(120))
    nivel: Mapped[e.NivelAlerta] = mapped_column(pg_enum(e.NivelAlerta, "nivel_alerta"), index=True)
    nivel_inicial: Mapped[e.NivelAlerta] = mapped_column(pg_enum(e.NivelAlerta, "nivel_alerta"))
    motivos_nivel: Mapped[list[str]] = mapped_column(JSONB, default=list)
    estado: Mapped[e.EstadoAlerta] = mapped_column(
        pg_enum(e.EstadoAlerta, "estado_alerta"), default=e.EstadoAlerta.aberto, index=True
    )
    contador: Mapped[int] = mapped_column(Integer, default=1)
    ultima_ocorrencia_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    regiao: Mapped[str | None] = mapped_column(String(60))
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    dispositivo_iot_id: Mapped[str | None] = mapped_column(String(80))
    agente_alvo_id: Mapped[int | None] = mapped_column(ForeignKey("agente.id", ondelete="CASCADE"))
    incidente_id: Mapped[int | None] = mapped_column(ForeignKey("alerta.id", ondelete="SET NULL"), index=True)
    dados: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    reconhecido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconhecido_por: Mapped[str | None] = mapped_column(String(120))
    agente_id: Mapped[int | None] = mapped_column(ForeignKey("agente.id", ondelete="SET NULL"), index=True)
    ordem_servico_id: Mapped[int | None] = mapped_column(ForeignKey("ordem_servico.id", ondelete="SET NULL"))
    silenciado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    silenciado_motivo: Mapped[str | None] = mapped_column(Text)
    tocado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolvido_por: Mapped[str | None] = mapped_column(String(120))
    resolucao: Mapped[str | None] = mapped_column(Text)

    equipamento: Mapped[Equipamento | None] = relationship(lazy="joined")
    agente: Mapped[Agente | None] = relationship(lazy="joined", foreign_keys=[agente_id])


class Regiao(Timestamps, Base):
    """Agrupamento de bairros usado pela central. Zonas oficiais substituem esta tabela sem mudar código."""

    __tablename__ = "regiao"
    __table_args__ = (UniqueConstraint("cidade_id", "nome"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cidade_id: Mapped[int] = mapped_column(ForeignKey("cidade.id"))
    nome: Mapped[str] = mapped_column(String(60))
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True), nullable=True)
    # Horários de pico: [{"dias": [0..6, 0 = segunda], "inicio": "07:00", "fim": "09:30"}]
    picos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class ConfigMotor(Base):
    """Limites do motor (50 m, 3 vezes, 15 min, 15%...) ajustáveis sem mexer no código."""

    __tablename__ = "config_motor"
    chave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[Any] = mapped_column(JSONB)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Instantaneo(Base):
    """Foto dos indicadores e das regiões a cada minuto: variação na última hora e linha do tempo."""

    __tablename__ = "instantaneo"
    id: Mapped[int] = mapped_column(primary_key=True)
    em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    indicadores: Mapped[dict[str, Any]] = mapped_column(JSONB)
    regioes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
