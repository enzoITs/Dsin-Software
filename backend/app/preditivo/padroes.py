"""Padrões plantados no histórico sintético (Parte 3).

Este módulo é usado SÓ pelo gerador (histórico e modo contínuo). Os modelos de previsão nunca
importam nada daqui: eles precisam redescobrir os padrões olhando os dados.

Tudo aqui é função pura (NumPy), para o histórico e o modo contínuo usarem exatamente a mesma
regra, e para os testes conferirem os padrões sem banco.
"""

import zlib

import numpy as np

# ---------------------------------------------------------------- equipamentos (padrões 4, 5, 6, 7, 11)

# Falhas por dia de um equipamento operacional, antes dos multiplicadores (cerca de 0,6 a 1 por ano).
FALHA_BASE_DIA = {
    "CAM": 0.0024, "RAD": 0.0023, "BAL": 0.0019, "CAN": 0.0021, "TOT": 0.0023,
    "VAF": 0.0020, "PAT": 0.0030, "VTR": 0.0014, "MOT": 0.0017, "VIA": 0.0015,
}
IDADE_POR_ANO = 0.10            # +10% de risco por ano de uso, para todos

# Padrão 4: câmeras desta marca falham muito mais depois de 18 meses, sobretudo após chuva.
MARCA_FRAGIL = "hikvision"
MESES_FRAGIL = 18
FATOR_FRAGIL = 3.0
FATOR_FRAGIL_CHUVA = 2.0        # multiplica de novo no dia seguinte a um dia com chuva >= CHUVA_FORTE_DIA_MM
CHUVA_FORTE_DIA_MM = 10.0

# Padrão 5: radares de rodovia (velocidade máxima >= 80 km/h) falham mais acima de 32 °C.
VELOCIDADE_RODOVIA = 80
TEMPERATURA_CALOR = 32.0
FATOR_CALOR = 4.0

# Padrão 7: manutenção preventiva atrasada há mais de 15 dias dobra a chance de falhar.
ATRASO_CRITICO_DIAS = 15
FATOR_ATRASO = 2.0

# Padrão 11: região que para de fazer preventiva a partir de um ponto do histórico, e cujo
# conserto fica cada vez mais lento. A disponibilidade cai devagar.
REGIAO_SEM_PREVENTIVA = "Leste"
FRACAO_INICIO_ABANDONO = 0.33   # a partir de 1/3 do período gerado
PREVENTIVA_FEITA_NO_ABANDONO = 0.08
ESPERA_CONSERTO_DIAS = 4.0      # média de dias entre a falha e a abertura da manutenção
ESPERA_CONSERTO_ABANDONO_MAX = 14.0  # média no fim do período, na região abandonada

# Padrão 6: furtos concentrados em dois bairros, de madrugada, longe de câmeras.
BAIRROS_FURTO = ("Brás", "Itaquera")
FURTO_BASE_DIA = 0.00004
FATOR_FURTO_BAIRRO = 8.0
FATOR_FURTO_SEM_CAMERA = 5.0    # além do bairro: nenhuma câmera a menos de RAIO_CAMERA_M
RAIO_CAMERA_M = 300
HORAS_MADRUGADA = (0, 1, 2, 3, 4)
TIPOS_FURTAVEIS = ("CAM", "RAD", "TOT", "BAL", "CAN", "PAT")

# Atraso da preventiva em relação à data prevista (dias): a maioria em dia, alguns bem atrasados.
ATRASO_PREVENTIVA = ((0.78, 0, 7), (0.14, 8, 15), (0.08, 16, 45))


def chave(*partes) -> int:
    """Semente estável a partir de textos e números (não depende do hash aleatório do Python)."""
    return zlib.crc32("|".join(str(p) for p in partes).encode())


def risco_falha_dia(
    base: np.ndarray, idade_dias: np.ndarray, fragil: np.ndarray, rodovia: np.ndarray,
    atraso_dias: np.ndarray, fragilidade: np.ndarray, chuva_ontem_mm: float, temp_max_c: float,
) -> np.ndarray:
    """Probabilidade de falhar no dia, por equipamento (vetores do mesmo tamanho; base vem de FALHA_BASE_DIA)."""
    h = base * (1 + IDADE_POR_ANO * np.maximum(idade_dias, 0) / 365.0) * fragilidade
    velha = fragil & (idade_dias > MESES_FRAGIL * 30.4)
    h = np.where(velha, h * FATOR_FRAGIL * (FATOR_FRAGIL_CHUVA if chuva_ontem_mm >= CHUVA_FORTE_DIA_MM else 1.0), h)
    if temp_max_c > TEMPERATURA_CALOR:
        h = np.where(rodovia, h * FATOR_CALOR, h)
    h = np.where(atraso_dias > ATRASO_CRITICO_DIAS, h * FATOR_ATRASO, h)
    return np.clip(h, 0, 0.5)


def risco_furto_dia(furtavel: np.ndarray, bairro_furto: np.ndarray, camera_perto: np.ndarray) -> np.ndarray:
    h = np.where(furtavel, FURTO_BASE_DIA, FURTO_BASE_DIA / 4)
    h = np.where(bairro_furto & furtavel, h * FATOR_FURTO_BAIRRO * np.where(camera_perto, 1.0, FATOR_FURTO_SEM_CAMERA), h)
    return h


# ---------------------------------------------------------------- ocorrências (padrões 1, 2, 3, 6, 8)

CATEGORIAS = ("ACIDENTE", "CONGESTIONAMENTO", "ESTACIONAMENTO_IRREGULAR", "VEICULO_QUEBRADO", "ALAGAMENTO",
              "SEMAFORO_APAGADO", "VANDALISMO", "PERTURBACAO", "OUTROS")
IDX = {c: i for i, c in enumerate(CATEGORIAS)}

# Ocorrências por dia num bairro "médio" (antes de hora, dia da semana e multiplicadores).
BASE_DIA = {
    "ACIDENTE": 1.6, "CONGESTIONAMENTO": 1.4, "ESTACIONAMENTO_IRREGULAR": 2.4, "VEICULO_QUEBRADO": 1.2,
    "ALAGAMENTO": 0.0, "SEMAFORO_APAGADO": 0.5, "VANDALISMO": 0.35, "PERTURBACAO": 0.9, "OUTROS": 0.8,
}
PESO_REGIAO = {"Centro": 1.5, "Oeste": 1.1, "Sul": 1.0, "Leste": 1.0, "Norte": 0.85}


def _perfil(valores: list[float]) -> np.ndarray:
    a = np.array(valores, dtype=float)
    return a / a.mean()


_TRAFEGO = [0.15, 0.1, 0.08, 0.08, 0.12, 0.3, 0.8, 1.5, 1.7, 1.3, 1.1, 1.1, 1.2, 1.2, 1.1, 1.1, 1.3, 1.6, 1.8, 1.5,
            1.1, 0.8, 0.5, 0.3]
PERFIL_HORA = {
    "ACIDENTE": _perfil(_TRAFEGO),
    "CONGESTIONAMENTO": _perfil([0.05, 0.03, 0.03, 0.03, 0.05, 0.2, 0.8, 1.2, 1.2, 1.0, 0.9, 0.9, 1.0, 1.0, 0.9, 0.9, 1.0,
                                 1.2, 1.2, 1.0, 0.6, 0.4, 0.2, 0.1]),
    "ESTACIONAMENTO_IRREGULAR": _perfil([0.1, 0.05, 0.05, 0.05, 0.05, 0.1, 0.3, 0.8, 1.3, 1.6, 1.7, 1.7, 1.6, 1.6, 1.6,
                                         1.5, 1.4, 1.3, 1.1, 0.9, 0.7, 0.5, 0.3, 0.2]),
    "VEICULO_QUEBRADO": _perfil(_TRAFEGO),
    "ALAGAMENTO": np.ones(24),
    "SEMAFORO_APAGADO": np.ones(24),
    "VANDALISMO": _perfil([1.8, 2.0, 2.0, 1.8, 1.4, 0.6, 0.3, 0.3, 0.3, 0.3, 0.3, 0.4, 0.4, 0.4, 0.4, 0.5, 0.6, 0.7,
                           0.9, 1.1, 1.3, 1.5, 1.6, 1.7]),
    "PERTURBACAO": _perfil([1.6, 1.4, 1.0, 0.6, 0.3, 0.2, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.8, 0.8, 0.9, 1.0, 1.1, 1.3,
                            1.5, 1.7, 1.8, 1.8, 1.7]),
    "OUTROS": _perfil(_TRAFEGO),
}
# Dia da semana (0 = segunda). Feriado conta como domingo.
PERFIL_SEMANA = {
    "ACIDENTE": [1.0, 1.0, 1.0, 1.0, 1.1, 1.0, 0.8],
    "CONGESTIONAMENTO": [1.0, 1.0, 1.0, 1.0, 1.0, 0.45, 0.3],
    "ESTACIONAMENTO_IRREGULAR": [1.0, 1.0, 1.0, 1.0, 1.0, 0.8, 0.45],
    "VEICULO_QUEBRADO": [1.0, 1.0, 1.0, 1.0, 1.0, 0.8, 0.7],
    "ALAGAMENTO": [1.0] * 7,
    "SEMAFORO_APAGADO": [1.0] * 7,
    "VANDALISMO": [0.9, 0.9, 0.9, 1.0, 1.1, 1.3, 1.1],
    "PERTURBACAO": [0.8, 0.8, 0.9, 1.0, 1.2, 1.3, 1.0],
    "OUTROS": [1.0] * 7,
}

# Padrão 1: Centro, sexta e sábado, 18 h às 23 h.
REGIAO_NOITE = "Centro"
DIAS_NOITE = (4, 5)
HORAS_NOITE = range(18, 23)
FATOR_NOITE = 2.2
FATOR_NOITE_PERTURBACAO = 3.5

# Padrão 2: chuva.
CHUVA_HORA_MM = 0.5
FATOR_CHUVA_ACIDENTE = 1.4
FATOR_CHUVA_SEMAFORO = 2.0      # chuva forte derruba semáforos
CHUVA_FORTE_HORA_MM = 5.0
BAIRROS_BAIXOS = ("Casa Verde", "Bom Retiro", "Ipiranga", "Lapa")
ALAGAMENTO_POR_MM = 0.12        # alagamentos por hora para cada mm/h de chuva forte, num bairro baixo
ALAGAMENTO_OUTROS_POR_MM = 0.004

# Padrão 3: eventos grandes.
PUBLICO_GRANDE = 10_000
RAIO_EVENTO_M = 2000
HORAS_ANTES_DEPOIS = 2
EVENTO_POR_10MIL_HORA = 0.9     # ocorrências extras por hora a cada 10 mil pessoas
MIX_EVENTO = {"CONGESTIONAMENTO": 0.35, "ESTACIONAMENTO_IRREGULAR": 0.25, "PERTURBACAO": 0.2, "ACIDENTE": 0.1,
              "OUTROS": 0.1}

# Padrão 6 (ocorrências): vandalismo nos bairros de furto, de madrugada.
FATOR_VANDALISMO_MADRUGADA = 5.0

# Padrão 8: congestionamento nos picos dos dias úteis, mais forte em véspera de feriado.
PICOS = (7, 8, 17, 18)
FATOR_PICO = 4.0
FATOR_VESPERA = 1.6

# Ruído: variação diária por bairro (gama com média 1) e viés de registro pelos agentes presentes.
FORMA_RUIDO_DIA = 10.0
VIES_AGENTES = 0.25             # registros = verdade × (1 - VIES + VIES × agentes / média da região)

GRAVIDADE = {
    "ACIDENTE": (0.15, 0.4, 0.35, 0.1), "CONGESTIONAMENTO": (0.3, 0.5, 0.17, 0.03),
    "ESTACIONAMENTO_IRREGULAR": (0.7, 0.27, 0.03, 0.0), "VEICULO_QUEBRADO": (0.35, 0.5, 0.15, 0.0),
    "ALAGAMENTO": (0.05, 0.3, 0.45, 0.2), "SEMAFORO_APAGADO": (0.1, 0.35, 0.45, 0.1),
    "VANDALISMO": (0.3, 0.5, 0.2, 0.0), "PERTURBACAO": (0.3, 0.45, 0.2, 0.05), "OUTROS": (0.6, 0.3, 0.1, 0.0),
    "FURTO_EQUIPAMENTO": (0.0, 0.0, 0.3, 0.7),
}
DURACAO_MIN = {
    "ACIDENTE": (30, 120), "CONGESTIONAMENTO": (30, 150), "ESTACIONAMENTO_IRREGULAR": (15, 60),
    "VEICULO_QUEBRADO": (30, 120), "ALAGAMENTO": (60, 300), "SEMAFORO_APAGADO": (60, 360), "VANDALISMO": (30, 90),
    "PERTURBACAO": (20, 120), "OUTROS": (15, 90), "FURTO_EQUIPAMENTO": (60, 240),
}


def peso_bairro(nome: str, regiao: str | None) -> float:
    """Tamanho relativo de cada bairro: região mais uma variação fixa pelo nome."""
    r = np.random.default_rng(chave("bairro", nome))
    return PESO_REGIAO.get(regiao or "", 1.0) * float(r.lognormal(0, 0.2))


def intensidade_dia(
    bairros: list[dict], dia_semana: int, feriado: bool, vespera: bool, chuva_h: np.ndarray,
    agentes_h: np.ndarray | None = None, agentes_media: np.ndarray | None = None,
) -> np.ndarray:
    """Ocorrências esperadas por bairro × hora local × categoria num dia (sem eventos).

    bairros: [{"nome", "regiao", "peso"}]; chuva_h: mm por hora local (24); agentes_h: agentes da
    região de cada bairro por hora (bairros × 24) e agentes_media: média da região (bairros).
    """
    nb = len(bairros)
    dow = 6 if feriado else dia_semana
    lam = np.zeros((nb, 24, len(CATEGORIAS)))
    peso = np.array([b["peso"] for b in bairros])
    for c, i in IDX.items():
        lam[:, :, i] = (BASE_DIA[c] / 24) * peso[:, None] * PERFIL_HORA[c][None, :] * PERFIL_SEMANA[c][dow]

    util = dow < 5
    if util:  # padrão 8
        fator = FATOR_PICO * (FATOR_VESPERA if vespera else 1.0)
        lam[:, list(PICOS), IDX["CONGESTIONAMENTO"]] *= fator

    if dow in DIAS_NOITE:  # padrão 1
        centro = np.array([b["regiao"] == REGIAO_NOITE for b in bairros])
        horas = list(HORAS_NOITE)
        for c, i in IDX.items():
            if c == "ALAGAMENTO":
                continue
            f = FATOR_NOITE_PERTURBACAO if c == "PERTURBACAO" else FATOR_NOITE
            lam[np.ix_(centro, horas, [i])] *= f

    # padrão 2
    chove = chuva_h >= CHUVA_HORA_MM
    lam[:, chove, IDX["ACIDENTE"]] *= FATOR_CHUVA_ACIDENTE
    forte = chuva_h >= CHUVA_FORTE_HORA_MM
    lam[:, forte, IDX["SEMAFORO_APAGADO"]] *= FATOR_CHUVA_SEMAFORO
    baixo = np.array([b["nome"] in BAIRROS_BAIXOS for b in bairros])
    mm = np.where(forte, chuva_h, 0.0)
    lam[:, :, IDX["ALAGAMENTO"]] = np.where(baixo[:, None], ALAGAMENTO_POR_MM, ALAGAMENTO_OUTROS_POR_MM) * mm[None, :]

    # padrão 6 (vandalismo)
    furto = np.array([b["nome"] in BAIRROS_FURTO for b in bairros])
    lam[np.ix_(furto, list(HORAS_MADRUGADA), [IDX["VANDALISMO"]])] *= FATOR_VANDALISMO_MADRUGADA

    if agentes_h is not None and agentes_media is not None:
        rel = agentes_h / np.maximum(agentes_media[:, None], 1e-6)
        lam *= (1 - VIES_AGENTES + VIES_AGENTES * rel)[:, :, None]
    return lam


def extra_evento_hora(publico: int) -> float:
    """Ocorrências extras por hora em volta de um evento (padrão 3). Abaixo do limite, nada."""
    if publico <= PUBLICO_GRANDE:
        return 0.0
    return EVENTO_POR_10MIL_HORA * publico / 10_000
