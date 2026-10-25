"""Parte 3, fase 2: séries por hora de equipamentos (base do detector de anomalias).

Só acrescenta a tabela serie_equipamento_hora. Usa checkfirst porque a 0001 cria as tabelas
a partir dos modelos atuais num banco novo.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

from app.models import SerieEquipamentoHora

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    SerieEquipamentoHora.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS serie_equipamento_hora CASCADE")
