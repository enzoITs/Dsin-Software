"""Parte 3: Cidade Preditiva.

Ocorrências urbanas e catálogo de categorias, calendário, eventos da cidade, clima por hora,
escala de agentes e as tabelas que guardam modelos, previsões, recomendações e backtests.

Só acrescenta: nada das Partes 1 e 2 muda. Como a 0001 cria as tabelas a partir dos modelos
atuais, tudo aqui usa checkfirst e funciona num banco novo e num banco da Parte 2.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
from sqlalchemy import text

from app.models import (
    BacktestResultado,
    Calendario,
    CategoriaOcorrencia,
    ClimaHora,
    EscalaAgente,
    EstadoPreditivo,
    EventoCidade,
    ModeloVersao,
    Ocorrencia,
    Previsao,
    Recomendacao,
)

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Ordem de criação respeita as chaves estrangeiras.
TABELAS = [CategoriaOcorrencia, Ocorrencia, Calendario, EventoCidade, ClimaHora, EscalaAgente,
           ModeloVersao, Previsao, Recomendacao, BacktestResultado, EstadoPreditivo]
TIPOS = ["origem_ocorrencia", "tipo_evento", "estado_recomendacao"]

CATEGORIAS = [
    ("ACIDENTE", "Acidente de trânsito", "Colisão, atropelamento ou queda", 3),
    ("CONGESTIONAMENTO", "Congestionamento", "Trânsito parado ou muito lento", 2),
    ("ESTACIONAMENTO_IRREGULAR", "Estacionamento irregular", "Veículo em local proibido ou fila dupla", 1),
    ("VEICULO_QUEBRADO", "Veículo quebrado", "Veículo parado na via por pane", 2),
    ("ALAGAMENTO", "Alagamento", "Via com água acumulada", 3),
    ("SEMAFORO_APAGADO", "Semáforo apagado", "Semáforo sem funcionar ou piscando", 3),
    ("FURTO_EQUIPAMENTO", "Furto de equipamento", "Equipamento público furtado", 4),
    ("VANDALISMO", "Vandalismo", "Equipamento ou mobiliário danificado de propósito", 2),
    ("PERTURBACAO", "Perturbação", "Aglomeração, barulho ou briga", 2),
    ("OUTROS", "Outros", "Qualquer outra ocorrência", 1),
]


def upgrade() -> None:
    bind = op.get_bind()
    for modelo in TABELAS:
        modelo.__table__.create(bind, checkfirst=True)
    for codigo, nome, desc, grav in CATEGORIAS:
        bind.execute(
            text("""INSERT INTO categoria_ocorrencia (codigo, nome, descricao, gravidade_padrao, ativa)
                    VALUES (:c, :n, :d, :g, true) ON CONFLICT (codigo) DO NOTHING"""),
            {"c": codigo, "n": nome, "d": desc, "g": grav},
        )


def downgrade() -> None:
    for modelo in reversed(TABELAS):
        op.execute(f"DROP TABLE IF EXISTS {modelo.__tablename__} CASCADE")
    for t in TIPOS:
        op.execute(f"DROP TYPE IF EXISTS {t}")
