"""Parte 3: Cidade Preditiva.

Ocorrências da cidade, fatores externos (calendário, clima, eventos), escala de agentes
e o que os modelos produzem (versões, previsões, recomendações, backtests).
"""

from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import enums as e
from app.models.entidades import Base, pg_enum


class CategoriaOcorrencia(Base):
    """Catálogo extensível: categorias novas são só uma linha nesta tabela."""

    __tablename__ = "categoria_ocorrencia"
    codigo: Mapped[str] = mapped_column(String(40), primary_key=True)
    nome: Mapped[str] = mapped_column(String(80))
    descricao: Mapped[str | None] = mapped_column(Text)
    gravidade_padrao: Mapped[int] = mapped_column(SmallInteger, default=2)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)


class Ocorrencia(Base):
    __tablename__ = "ocorrencia"
    __table_args__ = (
        CheckConstraint("gravidade BETWEEN 1 AND 4", name="ck_ocorrencia_gravidade"),
        Index("ix_ocorrencia_regiao_inicio", "regiao_id", "inicio_em"),
        Index("ix_ocorrencia_bairro_inicio", "bairro_id", "inicio_em"),
        Index("ix_ocorrencia_categoria_inicio", "categoria", "inicio_em"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    categoria: Mapped[str] = mapped_column(ForeignKey("categoria_ocorrencia.codigo"))
    gravidade: Mapped[int] = mapped_column(SmallInteger)
    inicio_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fim_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=True)
    regiao_id: Mapped[int | None] = mapped_column(ForeignKey("regiao.id"))
    bairro_id: Mapped[int | None] = mapped_column(ForeignKey("bairro.id"))
    origem: Mapped[e.OrigemOcorrencia] = mapped_column(pg_enum(e.OrigemOcorrencia, "origem_ocorrencia"))
    equipamento_id: Mapped[int | None] = mapped_column(ForeignKey("equipamento.id", ondelete="SET NULL"))
    alerta_id: Mapped[int | None] = mapped_column(ForeignKey("alerta.id", ondelete="SET NULL"), index=True)
    # Agentes ativos na região no momento: exposição, para corrigir o viés de patrulhamento.
    agentes_presentes_regiao: Mapped[int | None] = mapped_column(Integer)
    descricao: Mapped[str | None] = mapped_column(Text)
    registrado_por: Mapped[str | None] = mapped_column(String(120))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    categoria_ref: Mapped[CategoriaOcorrencia] = relationship(lazy="joined")


class Calendario(Base):
    __tablename__ = "calendario"
    data: Mapped[date] = mapped_column(Date, primary_key=True)
    dia_semana: Mapped[int] = mapped_column(SmallInteger)  # 0 = segunda
    feriado: Mapped[bool] = mapped_column(Boolean, default=False)
    feriado_nome: Mapped[str | None] = mapped_column(String(120))
    feriado_esfera: Mapped[str | None] = mapped_column(String(20))  # nacional, estadual, municipal
    vespera_feriado: Mapped[bool] = mapped_column(Boolean, default=False)
    periodo_escolar: Mapped[bool] = mapped_column(Boolean, default=False)
    dia_pagamento: Mapped[bool] = mapped_column(Boolean, default=False)


class EventoCidade(Base):
    __tablename__ = "evento_cidade"
    __table_args__ = (Index("ix_evento_cidade_periodo", "inicio_em", "fim_em"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160))
    tipo: Mapped[e.TipoEvento] = mapped_column(pg_enum(e.TipoEvento, "tipo_evento"))
    local_nome: Mapped[str | None] = mapped_column(String(160))
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    inicio_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fim_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    publico_estimado: Mapped[int] = mapped_column(Integer, default=0)
    raio_influencia_m: Mapped[int] = mapped_column(Integer, default=2000)
    simulado: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_por: Mapped[str | None] = mapped_column(String(120))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClimaHora(Base):
    """Uma linha por hora e cidade. `previsao` marca as horas futuras (editáveis na interface)."""

    __tablename__ = "clima_hora"
    cidade_id: Mapped[int] = mapped_column(ForeignKey("cidade.id"), primary_key=True)
    em: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    temperatura_c: Mapped[float] = mapped_column(Float)
    chuva_mm: Mapped[float] = mapped_column(Float, default=0)
    alerta_tempestade: Mapped[bool] = mapped_column(Boolean, default=False)
    previsao: Mapped[bool] = mapped_column(Boolean, default=False)
    editado_por: Mapped[str | None] = mapped_column(String(120))


class EscalaAgente(Base):
    """Turno de uma equipe numa região: base para a recomendação de reforço (P4)."""

    __tablename__ = "escala_agente"
    __table_args__ = (Index("ix_escala_regiao_periodo", "regiao_id", "inicio_em", "fim_em"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    equipe: Mapped[str] = mapped_column(String(60))
    orgao_id: Mapped[int] = mapped_column(ForeignKey("orgao.id"))
    regiao_id: Mapped[int] = mapped_column(ForeignKey("regiao.id"))
    inicio_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fim_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    agentes: Mapped[int] = mapped_column(Integer, default=2)
    origem: Mapped[str] = mapped_column(String(20), default="escala")  # escala, recomendacao, manual


class ModeloVersao(Base):
    __tablename__ = "modelo_versao"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(60), index=True)
    versao: Mapped[str] = mapped_column(String(40))
    treinado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    treino_inicio: Mapped[date | None] = mapped_column(Date)
    treino_fim: Mapped[date | None] = mapped_column(Date)
    parametros: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    metricas: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    metricas_baseline: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    caminho_artefato: Mapped[str | None] = mapped_column(String(300))
    ativo: Mapped[bool] = mapped_column(Boolean, default=False)


class Previsao(Base):
    __tablename__ = "previsao"
    __table_args__ = (
        Index("ix_previsao_modulo_alvo_inicio", "modulo", "alvo_tipo", "horizonte_inicio"),
        Index("ix_previsao_regiao_inicio", "regiao_id", "horizonte_inicio"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    modulo: Mapped[str] = mapped_column(String(4))  # P1, P2, ...
    alvo_tipo: Mapped[str] = mapped_column(String(20))  # equipamento, regiao, bairro, cidade
    alvo_id: Mapped[int | None] = mapped_column(Integer)
    regiao_id: Mapped[int | None] = mapped_column(ForeignKey("regiao.id"))
    horizonte_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizonte_fim: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valor: Mapped[float] = mapped_column(Float)
    faixa_inferior: Mapped[float | None] = mapped_column(Float)
    faixa_superior: Mapped[float | None] = mapped_column(Float)
    nivel: Mapped[str | None] = mapped_column(String(20))
    fatores: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    dados_considerados: Mapped[list[str]] = mapped_column(JSONB, default=list)
    detalhe: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # textos do cartão e extras do módulo
    modelo_versao_id: Mapped[int | None] = mapped_column(ForeignKey("modelo_versao.id", ondelete="SET NULL"))
    gerado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valor_real: Mapped[float | None] = mapped_column(Float)
    conferido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Recomendacao(Base):
    __tablename__ = "recomendacao"
    id: Mapped[int] = mapped_column(primary_key=True)
    previsao_id: Mapped[int | None] = mapped_column(ForeignKey("previsao.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(40))  # ABRIR_ORDEM_SERVICO, REFORCAR_EQUIPES, ...
    texto: Mapped[str] = mapped_column(Text)
    parametros: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    impacto_estimado: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    estado: Mapped[e.EstadoRecomendacao] = mapped_column(
        pg_enum(e.EstadoRecomendacao, "estado_recomendacao"), default=e.EstadoRecomendacao.pendente, index=True
    )
    decidido_por: Mapped[str | None] = mapped_column(String(120))
    decidido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo: Mapped[str | None] = mapped_column(Text)
    resultado: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestResultado(Base):
    __tablename__ = "backtest_resultado"
    id: Mapped[int] = mapped_column(primary_key=True)
    modulo: Mapped[str] = mapped_column(String(4), index=True)
    modelo_versao_id: Mapped[int | None] = mapped_column(ForeignKey("modelo_versao.id", ondelete="CASCADE"))
    data_corte: Mapped[date] = mapped_column(Date)
    metricas: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class EstadoPreditivo(Base):
    """Chave e valor do serviço preditivo: data de referência do histórico, progresso do treino."""

    __tablename__ = "estado_preditivo"
    chave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[Any] = mapped_column(JSONB)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
