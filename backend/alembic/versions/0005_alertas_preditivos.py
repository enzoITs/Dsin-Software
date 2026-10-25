"""Parte 3, fases 7 e 9: novos tipos de alerta (anomalias e alertas preventivos).

Só acrescenta valores ao enum tipo_alerta. O PostgreSQL não remove valores de enum; na volta,
os valores ficam (sem uso) e os alertas desses tipos são apagados.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NOVOS = ["anomalia_equipamento", "anomalia_regiao", "previsao_risco_regiao", "previsao_falha_equipamento",
         "previsao_falta_agentes", "previsao_disponibilidade"]


def upgrade() -> None:
    for v in NOVOS:  # como na 0002: dentro da transação, sem usar o valor novo na mesma migração
        op.execute(f"ALTER TYPE tipo_alerta ADD VALUE IF NOT EXISTS '{v}'")


def downgrade() -> None:
    lista = ", ".join(f"'{v}'" for v in NOVOS)
    op.execute(f"DELETE FROM alerta WHERE tipo::text IN ({lista})")
