"""Testes rodam num banco separado (atalaia_test) no mesmo Postgres do compose."""

import os

BASE = os.environ.get("DATABASE_URL", "postgresql+psycopg://atalaia:atalaia@localhost:5433/atalaia")
TEST_URL = BASE.rsplit("/", 1)[0] + "/atalaia_test"
os.environ["DATABASE_URL"] = TEST_URL
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["WEBHOOK_URL"] = ""

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.domain import catalogo, limites  # noqa: E402
from app.domain.schemas_tipo import com_ordem  # noqa: E402
from app.models import Bairro, Cidade, Orgao, TipoEquipamento  # noqa: E402


@pytest.fixture(scope="session")
def banco():
    admin = create_engine(BASE, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS atalaia_test WITH (FORCE)"))
        c.execute(text("CREATE DATABASE atalaia_test"))
    admin.dispose()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


TABELAS = (
    "serie_equipamento_hora, estado_preditivo, backtest_resultado, recomendacao, previsao, modelo_versao, escala_agente, clima_hora, "
    "evento_cidade, calendario, ocorrencia, "
    "instantaneo, config_motor, regiao, anexo, alerta, agente, ordem_servico, registro_manutencao, plano_manutencao, historico_situacao, "
    "localizacao, equipamento, base, bairro, cidade, tipo_equipamento, orgao"
)


@pytest.fixture
def limpar(banco):
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {TABELAS} RESTART IDENTITY CASCADE"))
    with SessionLocal() as db:
        for o in catalogo.ORGAOS:
            db.add(Orgao(**o))
        sp = Cidade(nome="São Paulo", uf="SP", tem_lista_bairros=True, centro="SRID=4326;POINT(-46.634 -23.5505)")
        db.add(sp)
        db.flush()
        db.add(Bairro(cidade_id=sp.id, nome="Centro", regiao="Centro",
                      geom="SRID=4326;MULTIPOLYGON(((-46.65 -23.56,-46.62 -23.56,-46.62 -23.54,-46.65 -23.54,-46.65 -23.56)))"))
        db.add(Bairro(cidade_id=sp.id, nome="Pinheiros", regiao="Oeste",
                      geom="SRID=4326;MULTIPOLYGON(((-46.71 -23.58,-46.68 -23.58,-46.68 -23.55,-46.71 -23.55,-46.71 -23.58)))"))
        for t in catalogo.TIPOS:
            campos = {k: v for k, v in t.items() if k != "marcas"}
            db.add(TipoEquipamento(**{**campos, "schema_atributos": com_ordem(campos["schema_atributos"])}))
        db.flush()
        # Regiões da central: uma por bairro de teste, sem horário de pico (testes não dependem da hora).
        db.execute(text("""
            INSERT INTO regiao (cidade_id, nome, geom, picos, criado_em, atualizado_em)
            SELECT cidade_id, regiao, ST_Multi(ST_Union(geom)), '[]'::jsonb, now(), now()
            FROM bairro GROUP BY cidade_id, regiao
        """))
        db.commit()
    limites.limpar_cache()
    from app.services import central

    central.ESTADO_REGIOES.clear()
    yield


@pytest.fixture
def client(limpar):
    from app.main import app

    return TestClient(app)


RADAR = {
    "tipo_id": 1,  # Radar (primeiro do catálogo)
    "numero_serie": "PK-0001",
    "marca": "Perkons",
    "modelo": "PK-Vel 300",
    "orgao_id": 1,
    "dispositivo_iot_id": "IOT-TESTE-1",
    "situacao_inicial": "operacional",
    "atributos": {"modalidade": "velocidade", "velocidade_maxima": 60, "faixas_monitoradas": 2},
    "localizacao": {"cidade_id": 1, "rua": "Av. Paulista", "referencia": "oposto ao 181", "lon": -46.64, "lat": -23.55},
}


@pytest.fixture
def radar(client):
    def criar(**extra):
        body = {**RADAR, **extra}
        r = client.post("/equipamentos", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    return criar
