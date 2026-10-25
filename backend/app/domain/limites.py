"""Limites do motor de interpretação.

Os valores padrão estão aqui; qualquer um pode ser trocado pela tabela config_motor
(PUT /central/configuracao), sem mexer no código. A leitura do banco fica em cache por 10 s.
"""

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

PADRAO: dict[str, Any] = {
    # Regras de detecção
    "furto_distancia_m": 50,            # fixo afastado do ponto de instalação
    "silencio_fator": 3,                # sem sinal por mais de N x o intervalo do tipo = falha silenciosa
    "dado_velho_fator": 2,              # no mapa, sem sinal há mais de N x o intervalo = ponto esmaecido
    "incidente_minimo": 3,              # equipamentos com problema na mesma região...
    "incidente_janela_min": 15,         # ...dentro desta janela = incidente correlacionado
    "bateria_min_pct": 15,              # patinete
    "camera_qualidade_min_pct": 60,     # câmera com queda de qualidade de imagem
    "agente_sem_posicao_min": 10,
    "manutencao_aviso_dias": 7,
    # Criticidade
    "cobertura_raio_m": 500,            # sem outro do mesmo tipo operacional neste raio: sobe um nível
    "escalonar_critico_min": 2,         # crítico não reconhecido volta a tocar
    "escalonar_alto_min": 10,           # alto não reconhecido vira crítico
    "silenciar_max_min": 30,
    # Índice de saúde da região
    "saude_penalidade": {"critica": 25, "alta": 10, "media": 3},
    "saude_teto_media": 15,             # soma dos alertas médios tem teto (pendências administrativas)
    "saude_meta_disponibilidade": 90,   # -1 por ponto percentual abaixo
    "saude_sem_agentes": 20,
    # Mapa
    "camera_alcance_m": 120,
    "fuso": "America/Sao_Paulo",
    # Parte 3: treino e avaliação dos modelos de previsão
    "prev_backtest_dias": 91,           # backtest de origem móvel cobre os últimos N dias
    "prev_backtest_passo_dias": 7,      # um corte por semana
    "prev_treino_semanas": 52,          # P1: semanas de histórico usadas no treino
    "prev_treino_origens_dias": 270,    # P2: dias de origens usadas no treino
    "prev_p1_taxa_dias": 365,           # baseline de P1: taxa de falha do tipo nos últimos N dias
    "prev_p2_semanas_baseline": 8,      # baseline de P2: média da mesma hora e dia da semana em N semanas
    "prev_p6_media_dias": 30,           # baseline de P6: última média móvel de N dias
    "prev_horas_pico": [7, 8, 9, 17, 18, 19],  # horas de pico dos dias úteis, avaliadas à parte em P2
    "prev_p1_retreino_semanas": 2,      # no backtest de P1, retreina a cada N cortes
    "prev_p1_limites_nivel": [0.05, 0.12, 0.25],      # P1 em 7 dias: moderado, alto e muito alto a partir de
    "prev_p1_limites_nivel_30d": [0.15, 0.30, 0.50],  # P1 em 30 dias
    "prev_p2_retreino_semanas": 2,      # no backtest de P2, retreina a cada N cortes
    "prev_p3_pesos": {"ocorrencias": 40, "equipamentos": 20, "cobertura": 15, "agentes": 15, "externos": 10},
    "prev_agentes_por_ocorrencia": 12,  # agentes-hora necessários por ocorrência prevista na hora (demanda de P3 e P4)
    "prev_p4_max_deslocamentos": 4,     # equipes que podem trocar de região em cada período
    "prev_p4_min_equipes": 1,           # nenhuma região fica com menos equipes que isto (ou que já tinha)
    "prev_p4_tempo_max_s": 10,          # tempo máximo da otimização; depois disso, heurística gulosa
}

_cache: dict[str, Any] = {"em": 0.0, "valores": None}
TTL_S = 10


def carregar(db: Session | None = None, forcar: bool = False) -> dict[str, Any]:
    """Padrões sobrepostos pelo que estiver gravado no banco."""
    agora = time.monotonic()
    if not forcar and _cache["valores"] is not None and agora - _cache["em"] < TTL_S:
        return _cache["valores"]
    valores = dict(PADRAO)
    if db is None:
        return _cache["valores"] or valores
    if db is not None:
        from app.models import ConfigMotor

        try:
            for chave, valor in db.execute(select(ConfigMotor.chave, ConfigMotor.valor)).all():
                if chave in PADRAO:
                    valores[chave] = valor
        except Exception:  # tabela ainda não criada (antes da migração)
            db.rollback()
    _cache.update(em=agora, valores=valores)
    return valores


def limpar_cache() -> None:
    _cache.update(em=0.0, valores=None)
