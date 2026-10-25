"""Prepara o banco para a Central de Operações (roda na subida, depois do seed).

Uso: python -m scripts.preparar_central [--forcar]

Idempotente:
1. Cria as regiões a partir dos bairros (se ainda não existirem) com horário de pico padrão.
2. Dá posição inicial a agentes e móveis que ainda não têm.
3. Alinha os módulos "mudos" do simulador (1% que nunca manda sinal) com o banco.
4. Linha de base: na primeira vez, roda o motor e marca o que já estava errado como
   "pendência anterior à central" (reconhecido). Assim a central abre com a cidade em
   estado conhecido, e só problemas novos tocam e pesam no índice das regiões.
"""

import argparse
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update

from app.db import SessionLocal
from app.domain import derivados, limites
from app.models import ConfigMotor, Equipamento, TipoEquipamento
from app.models.enums import Situacao
from app.services import motor
from scripts.simulador_telemetria import mudo

MARCA = "_linha_de_base_em"
PICOS_PADRAO = '[{"dias": [0, 1, 2, 3, 4], "inicio": "07:00", "fim": "09:30"}, {"dias": [0, 1, 2, 3, 4], "inicio": "17:00", "fim": "19:30"}]'


def preparar(forcar: bool = False) -> None:
    t0 = time.time()
    agora = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.execute(text(f"""
            INSERT INTO regiao (cidade_id, nome, geom, picos, criado_em, atualizado_em)
            SELECT b.cidade_id, b.regiao, ST_Multi(ST_Union(b.geom)), '{PICOS_PADRAO}'::jsonb, now(), now()
            FROM bairro b WHERE b.regiao IS NOT NULL AND b.geom IS NOT NULL
            GROUP BY b.cidade_id, b.regiao
            ON CONFLICT (cidade_id, nome) DO NOTHING
        """))
        db.execute(text("""
            UPDATE agente a SET
                posicao = ST_SetSRID(ST_MakePoint(ST_X(b.geom) + (random() - 0.5) * 0.02,
                                                  ST_Y(b.geom) + (random() - 0.5) * 0.02), 4326),
                posicao_em = CASE WHEN a.situacao = 'em_atividade' THEN now() END
            FROM base b WHERE b.id = a.base_id AND a.posicao IS NULL AND b.geom IS NOT NULL
        """))
        db.execute(text("""
            UPDATE agente a SET regiao = r.nome FROM regiao r
            WHERE a.regiao IS NULL AND a.posicao IS NOT NULL AND ST_Contains(r.geom, a.posicao)
        """))
        db.execute(text("""
            UPDATE equipamento e SET
                posicao = ST_SetSRID(ST_MakePoint(ST_X(l.geom) + (random() - 0.5) * 0.04,
                                                  ST_Y(l.geom) + (random() - 0.5) * 0.04), 4326),
                posicao_em = e.ultimo_sinal_em
            FROM localizacao l, tipo_equipamento t
            WHERE l.equipamento_id = e.id AND t.id = e.tipo_id AND t.mobilidade = 'movel'
              AND e.posicao IS NULL AND l.geom IS NOT NULL
        """))
        db.commit()

        ja = db.get(ConfigMotor, MARCA)
        if ja is not None and not forcar:
            print(f"[central] linha de base já feita em {ja.valor}; nada a fazer")
            return

        # Mudos do simulador: ficam sem sinal desde já, para não virarem alerta novo no meio da demonstração.
        cfg = limites.carregar(db, forcar=True)
        linhas = db.execute(
            select(Equipamento.id, Equipamento.codigo_interno, TipoEquipamento.intervalo_sinal_esperado_min)
            .join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
            .where(Equipamento.situacao == Situacao.operacional, Equipamento.dispositivo_iot_id.is_not(None))
        ).all()
        mudos = [(i, intervalo) for i, cod, intervalo in linhas if mudo(cod, 0.01)]
        for i, intervalo in mudos:
            db.execute(update(Equipamento).where(Equipamento.id == i).values(
                ultimo_sinal_em=agora - timedelta(minutes=intervalo * cfg["silencio_fator"] + 5)))
        derivados.recalcular(db, None, agora)
        if forcar:
            # Recomeço da demonstração: tudo que está aberto agora vira pendência conhecida.
            db.execute(text("""
                UPDATE alerta SET estado = 'reconhecido', reconhecido_em = now(), reconhecido_por = :p
                WHERE resolvido_em IS NULL AND estado = 'aberto'
            """), {"p": motor.central.LINHA_DE_BASE})
        db.commit()
        res = motor.verificar(db, agora, linha_de_base=True)
        if ja is None:
            db.add(ConfigMotor(chave=MARCA, valor=agora.isoformat()))
        else:
            ja.valor = agora.isoformat()
        db.commit()
        print(f"[central] {len(mudos)} módulos mudos alinhados; linha de base: {res}; {time.time() - t0:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forcar", action="store_true", help="refaz a linha de base")
    preparar(ap.parse_args().forcar)


if __name__ == "__main__":
    main()
