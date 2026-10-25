"""Tipos de equipamento iniciais, com os atributos do enunciado.

Depois do seed, novos tipos são criados só pela interface (tabela tipo_equipamento).
"""

PLACA = {"type": "string", "title": "Placa", "pattern": "^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$"}

TIPOS = [
    {
        "nome": "Radar de fiscalização",
        "prefixo": "RAD",
        "categoria": "Fiscalização",
        "mobilidade": "fixo",
        "icone": "radar",
        "intervalo_sinal_esperado_min": 15,
        "periodicidade_padrao_dias": 180,
        "marcas": {"Perkons": ["PK-Vel 300", "PK-Vel 500"], "Pumatronix": ["ITSCAM 450", "ITSCAM 600"], "Velsis": ["VS-Speed"], "Splice": ["Sentinela"]},
        "schema_atributos": {
            "type": "object",
            "required": ["modalidade", "faixas_monitoradas"],
            "properties": {
                "modalidade": {"type": "string", "title": "Modalidade", "enum": ["velocidade", "semaforo", "retorno_proibido", "conversao_proibida"]},
                "velocidade_maxima": {"type": "integer", "title": "Velocidade máxima (km/h)", "minimum": 10, "maximum": 130},
                "faixas_monitoradas": {"type": "integer", "title": "Faixas monitoradas", "minimum": 1, "maximum": 8},
                "sentido": {"type": "string", "title": "Sentido", "enum": ["bairro-centro", "centro-bairro", "ambos"]},
                "leitura_placas": {"type": "boolean", "title": "Leitura de placas (OCR)"},
            },
        },
    },
    {
        "nome": "Câmera de videomonitoramento",
        "prefixo": "CAM",
        "categoria": "Monitoramento",
        "mobilidade": "fixo",
        "icone": "cctv",
        "intervalo_sinal_esperado_min": 10,
        "periodicidade_padrao_dias": 120,
        "marcas": {"Intelbras": ["VIP 5450", "VIP 9230 PTZ"], "Hikvision": ["DS-2CD2T47", "DS-2DE4425"], "Axis": ["Q6155-E", "P1455-LE"], "Bosch": ["AUTODOME 7000"]},
        "schema_atributos": {
            "type": "object",
            "required": ["resolucao"],
            "properties": {
                "resolucao": {"type": "string", "title": "Resolução", "enum": ["720p", "1080p", "4MP", "4K"]},
                "visao_noturna": {"type": "boolean", "title": "Visão noturna"},
                "colorida": {"type": "boolean", "title": "Colorida (não P&B)"},
                "ptz": {"type": "boolean", "title": "PTZ (move e dá zoom)"},
                "campo_visao_graus": {"type": "integer", "title": "Campo de visão (graus)", "minimum": 10, "maximum": 360},
            },
        },
    },
    {
        "nome": "Balança de caminhão",
        "prefixo": "BAL",
        "categoria": "Fiscalização",
        "mobilidade": "fixo",
        "icone": "scale",
        "intervalo_sinal_esperado_min": 60,
        "periodicidade_padrao_dias": 90,
        "marcas": {"Toledo": ["Conquista 2090"], "Filizola": ["Rodoviária BR-80"], "Velsis": ["WIM-Pro"]},
        "schema_atributos": {
            "type": "object",
            "required": ["capacidade_max_t", "modo"],
            "properties": {
                "capacidade_max_t": {"type": "number", "title": "Capacidade máxima (t)", "minimum": 1},
                "modo": {"type": "string", "title": "Pesagem", "enum": ["dinamica", "estatica"]},
            },
        },
    },
    {
        "nome": "Cancela automatizada",
        "prefixo": "CAN",
        "categoria": "Controle de acesso",
        "mobilidade": "fixo",
        "icone": "gate",
        "intervalo_sinal_esperado_min": 60,
        "periodicidade_padrao_dias": 180,
        "marcas": {"PPA": ["Barreira Speed"], "Garen": ["Cancela GR 3m"], "Nice": ["Wil 6"]},
        "schema_atributos": {
            "type": "object",
            "required": ["largura_m"],
            "properties": {
                "largura_m": {"type": "number", "title": "Largura (m)", "minimum": 1, "maximum": 12},
                "tipo_acesso": {"type": "string", "title": "Tipo de acesso", "enum": ["veicular", "pedestre", "misto"]},
            },
        },
    },
    {
        "nome": "Totem de estacionamento rotativo",
        "prefixo": "TOT",
        "categoria": "Estacionamento",
        "mobilidade": "fixo",
        "icone": "parking",
        "intervalo_sinal_esperado_min": 30,
        "periodicidade_padrao_dias": 90,
        "marcas": {"Flowbird": ["Strada Evolution"], "Parkeon": ["Stelio"], "Digicon": ["DigiPark T3"]},
        "schema_atributos": {
            "type": "object",
            "required": ["meios_pagamento"],
            "properties": {
                "meios_pagamento": {
                    "type": "array",
                    "title": "Meios de pagamento",
                    "items": {"type": "string", "enum": ["moedas", "cartao", "pix", "aplicativo"]},
                    "uniqueItems": True,
                    "minItems": 1,
                },
                "impressora": {"type": "boolean", "title": "Imprime comprovante"},
            },
        },
    },
    {
        "nome": "Veículo autônomo de fiscalização",
        "prefixo": "VAF",
        "categoria": "Estacionamento",
        "mobilidade": "movel",
        "icone": "bot",
        "intervalo_sinal_esperado_min": 5,
        "periodicidade_padrao_dias": 60,
        "marcas": {"Velsis": ["Patrol-AV"], "Moobi": ["ScanCar 2"]},
        "schema_atributos": {
            "type": "object",
            "required": ["zona_atribuida"],
            "properties": {
                "autonomia_h": {"type": "number", "title": "Autonomia (h)", "minimum": 0.5},
                "leitura_placas": {"type": "boolean", "title": "Leitura de placas"},
                "zona_atribuida": {"type": "string", "title": "Rota ou zona atribuída"},
            },
        },
    },
    {
        "nome": "Patinete elétrico",
        "prefixo": "PAT",
        "categoria": "Micromobilidade",
        "mobilidade": "movel",
        "icone": "scooter",
        "intervalo_sinal_esperado_min": 15,
        "periodicidade_padrao_dias": 30,
        "marcas": {"Segway": ["Ninebot Max G30"], "Xiaomi": ["Mi Pro 2"], "Okai": ["ES400"]},
        "schema_atributos": {
            "type": "object",
            "required": ["uso"],
            "properties": {
                "bateria_wh": {"type": "integer", "title": "Bateria (Wh)", "minimum": 100},
                "velocidade_max_kmh": {"type": "integer", "title": "Velocidade máxima (km/h)", "minimum": 5, "maximum": 40},
                "uso": {"type": "string", "title": "Uso", "enum": ["publico", "compartilhado"]},
                "operadora": {"type": "string", "title": "Operadora"},
            },
        },
    },
    {
        "nome": "Veículo de transporte",
        "prefixo": "VTR",
        "categoria": "Transporte",
        "mobilidade": "movel",
        "icone": "car",
        "intervalo_sinal_esperado_min": 30,
        "periodicidade_padrao_dias": 365,
        "marcas": {"Toyota": ["Corolla", "Hiace"], "Chevrolet": ["Spin"], "Honda": ["CG 160"], "Volkswagen": ["Saveiro", "Kombi Escolar"], "Fiat": ["Ducato"]},
        "schema_atributos": {
            "type": "object",
            "required": ["subtipo", "placa"],
            "properties": {
                "subtipo": {"type": "string", "title": "Serviço", "enum": ["taxi", "mototaxi", "escolar"]},
                "placa": PLACA,
                "permissao": {"type": "string", "title": "Permissão ou alvará"},
                "capacidade": {"type": "integer", "title": "Capacidade (passageiros)", "minimum": 1},
                "validade_vistoria": {"type": "string", "title": "Validade da vistoria", "format": "date"},
            },
        },
    },
    {
        "nome": "Moto de agente",
        "prefixo": "MOT",
        "categoria": "Frota operacional",
        "mobilidade": "movel",
        "icone": "bike",
        "intervalo_sinal_esperado_min": 10,
        "periodicidade_padrao_dias": 90,
        "marcas": {"Honda": ["XRE 300", "NC 750X"], "Yamaha": ["Lander 250"], "BMW": ["F 850 GS"]},
        "schema_atributos": {
            "type": "object",
            "required": ["placa", "prefixo"],
            "properties": {
                "placa": PLACA,
                "prefixo": {"type": "string", "title": "Prefixo"},
                "capacidade": {"type": "integer", "title": "Capacidade", "minimum": 1, "maximum": 2},
                "combustivel": {"type": "string", "title": "Combustível", "enum": ["gasolina", "flex", "eletrico"]},
            },
        },
    },
    {
        "nome": "Viatura",
        "prefixo": "VIA",
        "categoria": "Frota operacional",
        "mobilidade": "movel",
        "icone": "siren",
        "intervalo_sinal_esperado_min": 10,
        "periodicidade_padrao_dias": 90,
        "marcas": {"Chevrolet": ["Trailblazer", "S10"], "Toyota": ["Hilux", "Corolla Cross"], "Renault": ["Duster"]},
        "schema_atributos": {
            "type": "object",
            "required": ["placa", "prefixo"],
            "properties": {
                "placa": PLACA,
                "prefixo": {"type": "string", "title": "Prefixo"},
                "capacidade": {"type": "integer", "title": "Capacidade", "minimum": 1, "maximum": 9},
                "combustivel": {"type": "string", "title": "Combustível", "enum": ["gasolina", "flex", "diesel", "eletrico"]},
            },
        },
    },
]

ORGAOS = [
    {"sigla": "CET", "nome": "Companhia de Engenharia de Tráfego"},
    {"sigla": "GCM", "nome": "Guarda Civil Metropolitana"},
    {"sigla": "PM", "nome": "Polícia Militar"},
    {"sigla": "SMT", "nome": "Secretaria Municipal de Mobilidade e Trânsito"},
]

# Órgão dono de cada tipo no seed (pesos).
DONO_POR_TIPO = {
    "RAD": {"CET": 1},
    "CAM": {"CET": 0.4, "GCM": 0.35, "PM": 0.25},
    "BAL": {"CET": 1},
    "CAN": {"CET": 0.6, "SMT": 0.4},
    "TOT": {"SMT": 1},
    "VAF": {"SMT": 1},
    "PAT": {"SMT": 1},
    "VTR": {"SMT": 1},
    "MOT": {"CET": 0.5, "GCM": 0.3, "PM": 0.2},
    "VIA": {"GCM": 0.5, "PM": 0.5},
}

# Participação de cada tipo no total gerado.
PESO_TIPO = {
    "CAM": 0.28, "RAD": 0.14, "TOT": 0.14, "PAT": 0.12, "VTR": 0.12,
    "MOT": 0.06, "VIA": 0.06, "CAN": 0.04, "BAL": 0.02, "VAF": 0.02,
}

# Bairros de São Paulo com centro aproximado (lat, lon) e região.
# Os polígonos são gerados por Voronoi a partir destes pontos: servem para a demo,
# não são os limites oficiais.
CIDADE_PRINCIPAL = {"nome": "São Paulo", "uf": "SP", "centro": (-23.5505, -46.6340)}
BAIRROS_SP = [
    ("Sé", -23.5505, -46.6340, "Centro"), ("República", -23.5440, -46.6430, "Centro"),
    ("Bela Vista", -23.5610, -46.6470, "Centro"), ("Liberdade", -23.5590, -46.6350, "Centro"),
    ("Consolação", -23.5530, -46.6600, "Centro"), ("Brás", -23.5440, -46.6160, "Centro"),
    ("Bom Retiro", -23.5270, -46.6390, "Centro"), ("Pinheiros", -23.5670, -46.6930, "Oeste"),
    ("Lapa", -23.5230, -46.7040, "Oeste"), ("Butantã", -23.5710, -46.7300, "Oeste"),
    ("Perdizes", -23.5360, -46.6770, "Oeste"), ("Itaim Bibi", -23.5850, -46.6800, "Oeste"),
    ("Vila Mariana", -23.5890, -46.6340, "Sul"), ("Moema", -23.6010, -46.6620, "Sul"),
    ("Saúde", -23.6170, -46.6390, "Sul"), ("Campo Belo", -23.6230, -46.6680, "Sul"),
    ("Santo Amaro", -23.6540, -46.7100, "Sul"), ("Jabaquara", -23.6460, -46.6410, "Sul"),
    ("Ipiranga", -23.5900, -46.6070, "Sul"), ("Mooca", -23.5590, -46.5990, "Leste"),
    ("Tatuapé", -23.5400, -46.5760, "Leste"), ("Vila Prudente", -23.5830, -46.5800, "Leste"),
    ("Penha", -23.5260, -46.5440, "Leste"), ("Itaquera", -23.5390, -46.4570, "Leste"),
    ("Santana", -23.5020, -46.6250, "Norte"), ("Tucuruvi", -23.4800, -46.6040, "Norte"),
    ("Casa Verde", -23.5080, -46.6550, "Norte"), ("Freguesia do Ó", -23.4990, -46.6980, "Norte"),
]
# Limite usado para recortar os polígonos (lon_min, lat_min, lon_max, lat_max).
LIMITE_SP = (-46.78, -23.68, -46.43, -23.46)

# Segunda cidade sem lista oficial de bairros: mostra o cadastro sem bairro.
CIDADE_SEM_BAIRROS = {"nome": "Guarulhos", "uf": "SP", "centro": (-23.4538, -46.5333)}
