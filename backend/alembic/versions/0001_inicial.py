"""Esquema inicial do Atalaia.

Revision ID: 0001
Revises:
"""
from alembic import op

from app.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    Base.metadata.create_all(op.get_bind())

    # Busca textual rápida por trechos de código, série, marca e modelo.
    op.execute(
        """
        CREATE INDEX ix_equipamento_busca_trgm ON equipamento USING gin (
            (codigo_interno || ' ' || numero_serie || ' ' || marca || ' ' || modelo) gin_trgm_ops
        )
        """
    )
    op.execute("CREATE INDEX ix_equipamento_situacao_tipo ON equipamento (situacao, tipo_id)")

    # Histórico é somente inserção: nada é apagado ou editado.
    op.execute(
        """
        CREATE FUNCTION historico_somente_insercao() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'historico_situacao e somente insercao';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER tg_historico_somente_insercao
        BEFORE UPDATE OR DELETE ON historico_situacao
        FOR EACH ROW EXECUTE FUNCTION historico_somente_insercao()
        """
    )


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
    op.execute("DROP FUNCTION IF EXISTS historico_somente_insercao")
