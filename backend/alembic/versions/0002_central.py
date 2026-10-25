"""Parte 2: Central de Operações.

Regiões, posição de agentes e móveis, métricas da telemetria, alertas com nível,
ciclo de vida e agrupamento, configuração do motor e instantâneos para a linha do tempo.

A migração 0001 cria as tabelas a partir dos modelos atuais; por isso tudo aqui é
idempotente (IF NOT EXISTS) e funciona tanto num banco novo quanto num banco da Parte 1.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

from app.models import ConfigMotor, Instantaneo, Regiao

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

NOVAS_REGRAS = [
    "incidente_correlacionado", "mau_funcionamento", "regiao_descoberta", "sinal_degradado",
    "dispositivo_nao_cadastrado", "agente_sem_posicao", "manutencao_proxima",
]

# Horário de pico padrão (hora local): manhã e fim de tarde, de segunda a sexta.
PICOS_PADRAO = '[{"dias": [0, 1, 2, 3, 4], "inicio": "07:00", "fim": "09:30"}, {"dias": [0, 1, 2, 3, 4], "inicio": "17:00", "fim": "19:30"}]'


def upgrade() -> None:
    bind = op.get_bind()
    for v in NOVAS_REGRAS:
        op.execute(f"ALTER TYPE tipo_alerta ADD VALUE IF NOT EXISTS '{v}'")
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE nivel_alerta AS ENUM ('baixa', 'media', 'alta', 'critica');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE estado_alerta AS ENUM ('aberto', 'reconhecido', 'em_atendimento', 'resolvido');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    for t in (Regiao.__table__, ConfigMotor.__table__, Instantaneo.__table__):
        t.create(bind, checkfirst=True)

    # Estado atual vindo da telemetria
    op.execute("""
        ALTER TABLE equipamento
            ADD COLUMN IF NOT EXISTS posicao geometry(POINT, 4326),
            ADD COLUMN IF NOT EXISTS posicao_em timestamptz,
            ADD COLUMN IF NOT EXISTS metricas jsonb NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS metricas_em timestamptz
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_equipamento_posicao ON equipamento USING gist (posicao)")
    op.execute("""
        ALTER TABLE agente
            ADD COLUMN IF NOT EXISTS posicao geometry(POINT, 4326),
            ADD COLUMN IF NOT EXISTS posicao_em timestamptz,
            ADD COLUMN IF NOT EXISTS regiao varchar(60)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agente_posicao ON agente USING gist (posicao)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agente_regiao ON agente (regiao)")

    # Alertas: nível, ciclo de vida, agrupamento
    op.execute("ALTER TABLE alerta ALTER COLUMN equipamento_id DROP NOT NULL")
    op.execute("""
        ALTER TABLE alerta
            ADD COLUMN IF NOT EXISTS chave varchar(120),
            ADD COLUMN IF NOT EXISTS nivel nivel_alerta,
            ADD COLUMN IF NOT EXISTS nivel_inicial nivel_alerta,
            ADD COLUMN IF NOT EXISTS motivos_nivel jsonb NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS estado estado_alerta NOT NULL DEFAULT 'aberto',
            ADD COLUMN IF NOT EXISTS contador integer NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS ultima_ocorrencia_em timestamptz,
            ADD COLUMN IF NOT EXISTS regiao varchar(60),
            ADD COLUMN IF NOT EXISTS geom geometry(POINT, 4326),
            ADD COLUMN IF NOT EXISTS dispositivo_iot_id varchar(80),
            ADD COLUMN IF NOT EXISTS agente_alvo_id integer REFERENCES agente(id) ON DELETE CASCADE,
            ADD COLUMN IF NOT EXISTS incidente_id integer REFERENCES alerta(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS dados jsonb NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS reconhecido_em timestamptz,
            ADD COLUMN IF NOT EXISTS reconhecido_por varchar(120),
            ADD COLUMN IF NOT EXISTS agente_id integer REFERENCES agente(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS ordem_servico_id integer REFERENCES ordem_servico(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS silenciado_ate timestamptz,
            ADD COLUMN IF NOT EXISTS silenciado_motivo text,
            ADD COLUMN IF NOT EXISTS tocado_em timestamptz,
            ADD COLUMN IF NOT EXISTS resolvido_por varchar(120),
            ADD COLUMN IF NOT EXISTS resolucao text
    """)

    # Alertas da Parte 1: ganham nível e chave. Os abertos já eram conhecidos antes da central
    # existir, então entram como "reconhecidos" (pendência anterior) e não disparam som.
    op.execute("""
        UPDATE alerta a SET
            chave = a.tipo::text || ':eq:' || a.equipamento_id,
            nivel = CASE WHEN a.severidade = 'critico' THEN 'critica'::nivel_alerta
                         WHEN a.tipo::text = 'falha_silenciosa' THEN 'alta'::nivel_alerta
                         ELSE 'media'::nivel_alerta END,
            estado = CASE WHEN a.resolvido_em IS NOT NULL THEN 'resolvido'::estado_alerta
                          ELSE 'reconhecido'::estado_alerta END,
            reconhecido_em = CASE WHEN a.resolvido_em IS NULL THEN now() END,
            reconhecido_por = CASE WHEN a.resolvido_em IS NULL THEN 'Pendência anterior à central' END,
            ultima_ocorrencia_em = a.criado_em,
            regiao = l.regiao,
            geom = l.geom
        FROM localizacao l
        WHERE l.equipamento_id = a.equipamento_id AND a.chave IS NULL
    """)
    op.execute("""
        UPDATE alerta SET chave = tipo::text || ':id:' || id,
            nivel = CASE WHEN severidade = 'critico' THEN 'critica'::nivel_alerta ELSE 'media'::nivel_alerta END,
            estado = CASE WHEN resolvido_em IS NOT NULL THEN 'resolvido'::estado_alerta ELSE 'reconhecido'::estado_alerta END
        WHERE chave IS NULL
    """)
    op.execute("UPDATE alerta SET nivel_inicial = nivel WHERE nivel_inicial IS NULL")
    # Só um alerta não resolvido por chave: duplicatas antigas são encerradas, fica o mais novo.
    op.execute("""
        UPDATE alerta a SET resolvido_em = now(), estado = 'resolvido', resolucao = 'Duplicado ao migrar'
        WHERE a.resolvido_em IS NULL AND EXISTS (
            SELECT 1 FROM alerta b WHERE b.chave = a.chave AND b.resolvido_em IS NULL AND b.id > a.id)
    """)
    op.execute("ALTER TABLE alerta ALTER COLUMN chave SET NOT NULL")
    op.execute("ALTER TABLE alerta ALTER COLUMN nivel SET NOT NULL")
    op.execute("ALTER TABLE alerta ALTER COLUMN nivel_inicial SET NOT NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_alerta_chave_aberta ON alerta (chave) WHERE resolvido_em IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alerta_regiao_estado ON alerta (regiao, estado)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alerta_nivel ON alerta (nivel)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alerta_estado ON alerta (estado)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alerta_incidente_id ON alerta (incidente_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alerta_agente_id ON alerta (agente_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alerta_criado_em ON alerta (criado_em)")

    # Linha do tempo: "qual era a situação em T" lê o histórico por equipamento e data.
    op.execute("CREATE INDEX IF NOT EXISTS ix_historico_equip_em ON historico_situacao (equipamento_id, em)")

    # Regiões a partir dos bairros (o campo regiao do bairro já existia na Parte 1).
    op.execute(f"""
        INSERT INTO regiao (cidade_id, nome, geom, picos)
        SELECT b.cidade_id, b.regiao, ST_Multi(ST_Union(b.geom)), '{PICOS_PADRAO}'::jsonb
        FROM bairro b
        WHERE b.regiao IS NOT NULL AND b.geom IS NOT NULL
        GROUP BY b.cidade_id, b.regiao
        ON CONFLICT (cidade_id, nome) DO NOTHING
    """)

    # Posição inicial: agentes perto da base; móveis espalhados pela região da base.
    op.execute("""
        UPDATE agente a SET
            posicao = ST_SetSRID(ST_MakePoint(ST_X(b.geom) + (random() - 0.5) * 0.02,
                                              ST_Y(b.geom) + (random() - 0.5) * 0.02), 4326),
            posicao_em = CASE WHEN a.situacao = 'em_atividade' THEN now() END
        FROM base b
        WHERE b.id = a.base_id AND a.posicao IS NULL AND b.geom IS NOT NULL
    """)
    op.execute("""
        UPDATE agente a SET regiao = r.nome FROM regiao r
        WHERE a.regiao IS NULL AND ST_Contains(r.geom, a.posicao)
    """)
    op.execute("""
        UPDATE equipamento e SET
            posicao = ST_SetSRID(ST_MakePoint(ST_X(l.geom) + (random() - 0.5) * 0.04,
                                              ST_Y(l.geom) + (random() - 0.5) * 0.04), 4326),
            posicao_em = e.ultimo_sinal_em
        FROM localizacao l, tipo_equipamento t
        WHERE l.equipamento_id = e.id AND t.id = e.tipo_id AND t.mobilidade = 'movel'
          AND e.posicao IS NULL AND l.geom IS NOT NULL
    """)


def downgrade() -> None:
    for t in ("instantaneo", "config_motor", "regiao"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    op.execute("DROP INDEX IF EXISTS uq_alerta_chave_aberta")
    for c in ("chave", "nivel", "nivel_inicial", "motivos_nivel", "estado", "contador", "ultima_ocorrencia_em", "regiao",
              "geom", "dispositivo_iot_id", "agente_alvo_id", "incidente_id", "dados", "reconhecido_em", "reconhecido_por",
              "agente_id", "ordem_servico_id", "silenciado_ate", "silenciado_motivo", "tocado_em", "resolvido_por", "resolucao"):
        op.execute(f"ALTER TABLE alerta DROP COLUMN IF EXISTS {c}")
    for c in ("posicao", "posicao_em", "regiao"):
        op.execute(f"ALTER TABLE agente DROP COLUMN IF EXISTS {c}")
    for c in ("posicao", "posicao_em", "metricas", "metricas_em"):
        op.execute(f"ALTER TABLE equipamento DROP COLUMN IF EXISTS {c}")
