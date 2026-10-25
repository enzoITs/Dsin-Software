import enum


class Situacao(str, enum.Enum):
    nao_instalado = "nao_instalado"
    operacional = "operacional"
    mau_funcionamento = "mau_funcionamento"
    em_manutencao = "em_manutencao"
    desativado = "desativado"
    furtado = "furtado"


class Mobilidade(str, enum.Enum):
    fixo = "fixo"
    movel = "movel"


class TipoPlano(str, enum.Enum):
    imediata = "imediata"
    agendada = "agendada"
    periodica = "periodica"


class StatusManutencao(str, enum.Enum):
    em_dia = "em_dia"
    proxima = "proxima"
    vencida = "vencida"


class StatusOS(str, enum.Enum):
    aberta = "aberta"
    fechada = "fechada"


class PrioridadeOS(str, enum.Enum):
    baixa = "baixa"
    media = "media"
    alta = "alta"
    critica = "critica"


class CategoriaAgente(str, enum.Enum):
    agente_transito = "agente_transito"
    guarda_municipal = "guarda_municipal"
    policial_militar = "policial_militar"


class SituacaoAgente(str, enum.Enum):
    em_atividade = "em_atividade"
    em_pausa = "em_pausa"
    fora_de_escala = "fora_de_escala"


class TipoAlerta(str, enum.Enum):
    """Regra de detecção que gerou o alerta (Parte 2: motor de interpretação)."""

    furto = "furto"
    incidente_correlacionado = "incidente_correlacionado"
    mau_funcionamento = "mau_funcionamento"
    falha_silenciosa = "falha_silenciosa"
    regiao_descoberta = "regiao_descoberta"
    sinal_degradado = "sinal_degradado"
    manutencao_vencida = "manutencao_vencida"
    dispositivo_nao_cadastrado = "dispositivo_nao_cadastrado"
    agente_sem_posicao = "agente_sem_posicao"
    manutencao_proxima = "manutencao_proxima"


class Severidade(str, enum.Enum):
    """Mantida por compatibilidade com a Parte 1: crítica vira "critico", o resto "atencao"."""

    critico = "critico"
    atencao = "atencao"


class NivelAlerta(str, enum.Enum):
    baixa = "baixa"
    media = "media"
    alta = "alta"
    critica = "critica"


class EstadoAlerta(str, enum.Enum):
    aberto = "aberto"
    reconhecido = "reconhecido"
    em_atendimento = "em_atendimento"
    resolvido = "resolvido"
