"""Parte 3, fase 10: cenários "e se" salvos (C1).

Só acrescenta a tabela cenario. Usa checkfirst porque a 0001 cria as tabelas a partir dos modelos
atuais num banco novo.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

from app.models import Cenario

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Cenario.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cenario CASCADE")
