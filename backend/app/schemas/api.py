from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    CategoriaAgente,
    Mobilidade,
    PrioridadeOS,
    Severidade,
    Situacao,
    SituacaoAgente,
    StatusManutencao,
    StatusOS,
    TipoAlerta,
    TipoPlano,
)

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Pagina(BaseModel, Generic[T]):
    itens: list[T]
    total: int
    pagina: int
    por_pagina: int


# ---------- Cadastros básicos ----------


class OrgaoOut(ORM):
    id: int
    nome: str
    sigla: str


class CidadeOut(ORM):
    id: int
    nome: str
    uf: str
    tem_lista_bairros: bool
    lon: float | None = None
    lat: float | None = None


class BairroOut(ORM):
    id: int
    cidade_id: int
    nome: str
    regiao: str | None


class BaseOut(ORM):
    id: int
    nome: str
    orgao_id: int
    cidade_id: int
    endereco: str | None


# ---------- Tipos ----------


class TipoIn(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    prefixo: str = Field(min_length=2, max_length=5)
    categoria: str = Field(min_length=2, max_length=60)
    mobilidade: Mobilidade
    icone: str = "box"
    schema_atributos: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    intervalo_sinal_esperado_min: int = Field(default=60, ge=1, le=60 * 24 * 7)
    periodicidade_padrao_dias: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("prefixo")
    @classmethod
    def prefixo_maiusculo(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalpha():
            raise ValueError("Prefixo deve ter só letras (ex.: SEM)")
        return v


class TipoOut(ORM):
    id: int
    nome: str
    prefixo: str
    categoria: str
    mobilidade: Mobilidade
    icone: str
    schema_atributos: dict[str, Any]
    intervalo_sinal_esperado_min: int
    periodicidade_padrao_dias: int | None
    total_equipamentos: int = 0


# ---------- Equipamentos ----------


class LocalizacaoIn(BaseModel):
    cidade_id: int
    rua: str = Field(min_length=2, max_length=200)
    cep: str | None = Field(default=None, pattern=r"^\d{5}-?\d{3}$")
    bairro_id: int | None = None
    referencia: str | None = Field(default=None, max_length=200)
    lon: float | None = Field(default=None, ge=-180, le=180)
    lat: float | None = Field(default=None, ge=-90, le=90)


class LocalizacaoOut(BaseModel):
    cidade_id: int
    cidade: str
    uf: str
    rua: str
    cep: str | None
    bairro_id: int | None
    bairro: str | None
    referencia: str | None
    regiao: str | None
    lon: float | None
    lat: float | None


class EquipamentoIn(BaseModel):
    tipo_id: int
    numero_serie: str = Field(min_length=2, max_length=80)
    marca: str = Field(min_length=1, max_length=80)
    modelo: str = Field(min_length=1, max_length=80)
    orgao_id: int
    dispositivo_iot_id: str | None = Field(default=None, max_length=80)
    situacao_inicial: Situacao = Situacao.nao_instalado
    data_instalacao: date | None = None
    atributos: dict[str, Any] = Field(default_factory=dict)
    localizacao: LocalizacaoIn

    @field_validator("situacao_inicial")
    @classmethod
    def so_inicio(cls, v: Situacao) -> Situacao:
        if v not in (Situacao.nao_instalado, Situacao.operacional):
            raise ValueError("Um equipamento novo começa como 'nao_instalado' ou 'operacional'")
        return v

    @field_validator("dispositivo_iot_id")
    @classmethod
    def vazio_vira_none(cls, v: str | None) -> str | None:
        return v.strip() or None if v else None


class EquipamentoPatch(BaseModel):
    numero_serie: str | None = Field(default=None, min_length=2, max_length=80)
    marca: str | None = Field(default=None, min_length=1, max_length=80)
    modelo: str | None = Field(default=None, min_length=1, max_length=80)
    orgao_id: int | None = None
    dispositivo_iot_id: str | None = None
    data_instalacao: date | None = None
    atributos: dict[str, Any] | None = None
    localizacao: LocalizacaoIn | None = None


class TipoResumo(ORM):
    id: int
    nome: str
    prefixo: str
    icone: str
    mobilidade: Mobilidade


class EquipamentoResumo(BaseModel):
    id: int
    codigo_interno: str
    tipo: TipoResumo
    marca: str
    modelo: str
    numero_serie: str
    orgao: str
    situacao: Situacao
    score_saude: int
    status_manutencao: StatusManutencao
    bairro: str | None
    regiao: str | None
    cidade: str | None
    ultimo_sinal_em: datetime | None
    sem_sinal: bool
    lon: float | None
    lat: float | None


class EquipamentoOut(EquipamentoResumo):
    orgao_id: int
    dispositivo_iot_id: str | None
    data_instalacao: date | None
    atributos: dict[str, Any]
    score_motivos: list[dict[str, Any]]
    localizacao: LocalizacaoOut | None
    transicoes_permitidas: list[Situacao]
    criado_em: datetime
    atualizado_em: datetime
    avisos: list[dict[str, Any]] = []


class MudancaSituacaoIn(BaseModel):
    situacao: Situacao
    motivo: str = Field(min_length=3, max_length=500)
    usuario: str | None = None


class MudancaSituacaoOut(BaseModel):
    equipamento: EquipamentoOut
    acoes: list[str]


class HistoricoOut(ORM):
    id: int
    equipamento_id: int
    situacao_anterior: Situacao | None
    situacao_nova: Situacao
    motivo: str
    usuario: str
    em: datetime


class PlanoIn(BaseModel):
    tipo: TipoPlano
    proxima_data: date | None = None
    periodicidade_dias: int | None = Field(default=None, ge=1, le=3650)
    descricao: str | None = None


class PlanoOut(ORM):
    id: int
    equipamento_id: int
    tipo: TipoPlano
    proxima_data: date | None
    periodicidade_dias: int | None
    descricao: str | None
    ativo: bool


class RegistroIn(BaseModel):
    tecnico: str = Field(min_length=2, max_length=120)
    executada_em: datetime | None = None
    plano_id: int | None = None
    descricao: str | None = None
    resultado: str = "concluida"
    lon: float | None = None
    lat: float | None = None


class RegistroOut(ORM):
    id: int
    plano_id: int | None
    equipamento_id: int
    executada_em: datetime
    tecnico: str
    descricao: str | None
    resultado: str


class RegistroCriadoOut(BaseModel):
    registro: RegistroOut
    equipamento: EquipamentoOut
    acoes: list[str]


class OrdemOut(ORM):
    id: int
    equipamento_id: int
    motivo: str
    prioridade: PrioridadeOS
    status: StatusOS
    aberta_em: datetime
    fechada_em: datetime | None


class ScoreOut(BaseModel):
    equipamento_id: int
    codigo_interno: str
    score: int
    motivos: list[dict[str, Any]]
    explicacao: str


# ---------- Telemetria, alertas, indicadores ----------


class SinalIn(BaseModel):
    """Sinal de um módulo IoT. Sem `tipo`, vale como presença (compatível com a Parte 1)."""

    dispositivo_iot_id: str = Field(min_length=1, max_length=80)
    em: datetime | None = None
    tipo: Literal["presenca", "posicao", "erro", "metrica"] = "presenca"
    lon: float | None = Field(None, ge=-180, le=180)
    lat: float | None = Field(None, ge=-90, le=90)
    valores: dict[str, Any] = Field(default_factory=dict, description='ex.: {"bateria": 12}, {"qualidade": 40}, {"codigo": "E-17"}')


class SinalOut(BaseModel):
    equipamento_id: int
    codigo_interno: str
    ultimo_sinal_em: datetime
    alerta_resolvido: bool
    alertas: list[int] = []


class PosicaoAgenteIn(BaseModel):
    agente_id: int | None = None
    matricula: str | None = None
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    em: datetime | None = None


class AcaoAlertaIn(BaseModel):
    acao: Literal["reconhecer", "silenciar", "resolver", "reabrir_som"]
    motivo: str | None = None
    minutos: int | None = Field(None, ge=1, le=30)


class AtribuirIn(BaseModel):
    agente_id: int


class OrdemAlertaIn(BaseModel):
    motivo: str | None = None


class IncidenteIn(BaseModel):
    tipo: Literal["furto", "falha", "silencio", "queda_energia", "degradado", "sem_agentes"]
    regiao: str
    quantidade: int = Field(5, ge=3, le=20)


class AlertaOut(BaseModel):
    id: int
    equipamento_id: int
    codigo_interno: str
    tipo: TipoAlerta
    severidade: Severidade
    mensagem: str
    criado_em: datetime
    resolvido_em: datetime | None


# ---------- Agentes ----------


class AgenteIn(BaseModel):
    nome: str = Field(min_length=3, max_length=120)
    matricula: str = Field(min_length=2, max_length=30)
    categoria: CategoriaAgente
    orgao_id: int
    equipe: str | None = None
    situacao: SituacaoAgente = SituacaoAgente.em_atividade
    contato: str | None = None
    veiculo_id: int | None = None
    base_id: int | None = None


class AgentePatch(BaseModel):
    nome: str | None = None
    equipe: str | None = None
    situacao: SituacaoAgente | None = None
    contato: str | None = None
    veiculo_id: int | None = None
    base_id: int | None = None


class VeiculoResumo(BaseModel):
    id: int
    codigo_interno: str
    tipo: str
    placa: str | None


class AgenteOut(BaseModel):
    id: int
    nome: str
    matricula: str
    categoria: CategoriaAgente
    orgao_id: int
    orgao: str
    equipe: str | None
    situacao: SituacaoAgente
    contato: str | None
    veiculo: VeiculoResumo | None
    base_id: int | None
    base: str | None
