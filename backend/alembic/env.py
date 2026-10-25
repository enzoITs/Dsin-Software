from alembic import context

from app.db import engine
from app.models import Base

target_metadata = Base.metadata


def _rodar(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Uma conexão passada por quem chama (testes de migração em banco à parte) tem prioridade.
    conexao = context.config.attributes.get("connection")
    if conexao is not None:
        _rodar(conexao)
        return
    with engine.connect() as connection:
        _rodar(connection)


run_migrations_online()
