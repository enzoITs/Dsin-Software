"""Parte 3, fase 11: briefing diário (C4).

Só acrescenta a tabela briefing. Usa checkfirst porque a 0001 cria as tabelas a partir dos modelos
atuais num banco novo.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

from app.models import Briefing

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Briefing.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS briefing CASCADE")
