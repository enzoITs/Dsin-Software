"""Gera dados de demonstração realistas.

Uso: python -m scripts.seed [--se-vazio] [--quantidade N] [--semente S] [--data-referencia AAAA-MM-DD]

Mesma semente e mesma data de referência: mesmo histórico.

Gera órgãos, cidades, bairros, tipos, equipamentos com anos de histórico coerente
com a máquina de estados, planos e registros de manutenção, ordens de serviço,
bases e agentes. Os últimos 18 meses da vida de cada equipamento vêm do gerador
da Parte 3 (app/preditivo/gerador_equipamentos.py), com padrões plantados. Também planta problemas de qualidade (duplicidades, coordenadas
suspeitas, bairro divergente, campos vazios) para o painel de qualidade ter o que mostrar.
"""

import argparse
import random
import string
import time
from datetime import date, datetime, timedelta, timezone

from faker import Faker
from shapely.geometry import MultiPoint, MultiPolygon, Point, box
from shapely.ops import voronoi_diagram
from shapely.strtree import STRtree
from sqlalchemy import func, insert, select, text

from app.config import settings
from app.db import SessionLocal
from app.domain import catalogo, derivados
from app.domain.schemas_tipo import com_ordem
from app.models import EstadoPreditivo
from app.preditivo import clima as clima_mod
from app.preditivo import gerador_equipamentos
from app.models import (
    Agente,
    Bairro,
    BaseOperacional,
    Cidade,
    Equipamento,
    HistoricoSituacao,
    Localizacao,
    OrdemServico,
    Orgao,
    PlanoManutencao,
    RegistroManutencao,
    TipoEquipamento,
)
from app.models.enums import (
    CategoriaAgente,
    PrioridadeOS,
    Situacao,
    SituacaoAgente,
    StatusOS,
    TipoPlano,
)

S = Situacao
fake = Faker("pt_BR")
AGORA = datetime.now(timezone.utc)
HOJE = AGORA.astimezone(clima_mod.FUSO).date()  # data de referência; main() pode trocar
SEMENTE = 42
DIAS_HISTORICO = 540  # período simulado com padrões (18 meses)

CUIDADO_ORGAO = {"PM": 0.4, "GCM": 0.8, "CET": 1.0, "SMT": 1.9}

# Só o que não sai da simulação: os demais estados finais vêm da vida simulada.
DIST_PREDEFINIDA = [(None, 0.94), (S.nao_instalado, 0.03), (S.desativado, 0.03)]


def escolher(pesos: dict | list):
    if isinstance(pesos, dict):
        itens, ws = list(pesos.keys()), list(pesos.values())
    else:
        itens, ws = [p[0] for p in pesos], [p[1] for p in pesos]
    return random.choices(itens, ws)[0]


def ewkt(lon: float, lat: float) -> str:
    return f"SRID=4326;POINT({lon:.6f} {lat:.6f})"


def placa() -> str:
    letras = "".join(random.choices(string.ascii_uppercase, k=3))
    return f"{letras}{random.randint(0, 9)}{random.choice(string.ascii_uppercase)}{random.randint(10, 99)}"


def chassi() -> str:
    return "9" + "".join(random.choices("ABCDEFGHJKLMNPRSTUVWXYZ0123456789", k=16))


def serie(prefixo: str) -> str:
    return f"{prefixo[:2]}{random.randint(10, 99)}-{random.randint(100000, 999999)}"


def referencia() -> str:
    n = random.randint(1, 3500)
    return random.choice(
        [f"número {n}", f"oposto ao {n}", f"em frente ao {n}", "S/N", f"próximo ao {n}",
         f"em frente ao {random.choice(['Mercado', 'Posto', 'Hospital', 'Terminal', 'Shopping'])} "
         f"{fake.last_name()}"]
    )


def atributos_para(prefixo: str, tipo: dict) -> dict:
    a: dict = {}
    if prefixo == "RAD":
        mod = escolher({"velocidade": 0.6, "semaforo": 0.25, "retorno_proibido": 0.08, "conversao_proibida": 0.07})
        a = {"modalidade": mod, "faixas_monitoradas": random.randint(1, 4),
             "sentido": random.choice(["bairro-centro", "centro-bairro", "ambos"]),
             "leitura_placas": random.random() < 0.7}
        if mod == "velocidade":
            a["velocidade_maxima"] = random.choice([40, 50, 60, 70, 80, 90])
    elif prefixo == "CAM":
        ptz = random.random() < 0.3
        a = {"resolucao": escolher({"1080p": 0.5, "4MP": 0.25, "4K": 0.15, "720p": 0.1}),
             "visao_noturna": random.random() < 0.75, "colorida": random.random() < 0.85,
             "ptz": ptz, "campo_visao_graus": 360 if ptz else random.choice([60, 90, 110])}
    elif prefixo == "BAL":
        a = {"capacidade_max_t": random.choice([30, 45, 60, 80]), "modo": random.choice(["dinamica", "estatica"])}
    elif prefixo == "CAN":
        a = {"largura_m": random.choice([3, 4, 5, 6]), "tipo_acesso": random.choice(["veicular", "misto"])}
    elif prefixo == "TOT":
        a = {"meios_pagamento": random.sample(["moedas", "cartao", "pix", "aplicativo"], k=random.randint(1, 4)),
             "impressora": random.random() < 0.6}
    elif prefixo == "VAF":
        a = {"autonomia_h": random.choice([6, 8, 10]), "leitura_placas": True,
             "zona_atribuida": f"Zona Azul {random.choice(['Centro', 'Pinheiros', 'Moema', 'Santana'])}"}
    elif prefixo == "PAT":
        a = {"bateria_wh": random.choice([374, 474, 551]), "velocidade_max_kmh": random.choice([20, 25]),
             "uso": random.choice(["publico", "compartilhado"]), "operadora": random.choice(["Whoosh", "Jet", "Tembici"])}
    elif prefixo == "VTR":
        sub = escolher({"taxi": 0.6, "escolar": 0.25, "mototaxi": 0.15})
        a = {"subtipo": sub, "placa": placa(), "permissao": f"ALV-{random.randint(10000, 99999)}",
             "capacidade": {"taxi": 4, "escolar": random.choice([12, 16, 20]), "mototaxi": 1}[sub],
             "validade_vistoria": (HOJE + timedelta(days=random.randint(-60, 365))).isoformat()}
    elif prefixo in ("MOT", "VIA"):
        a = {"placa": placa(), "prefixo": f"{prefixo[0]}-{random.randint(1000, 9999)}",
             "capacidade": 2 if prefixo == "MOT" else 5,
             "combustivel": random.choice(["gasolina", "flex"])}
    # Campos opcionais vazios de propósito: dados reais têm lacunas.
    obrig = set(tipo["schema_atributos"].get("required", []))
    for k in list(a):
        if k not in obrig and random.random() < 0.06:
            del a[k]
    return a


def gerar_bairros() -> list[tuple[str, str, MultiPolygon, Point]]:
    pontos = [Point(lon, lat) for _, lat, lon, _ in catalogo.BAIRROS_SP]
    limite = box(*catalogo.LIMITE_SP)
    celulas = voronoi_diagram(MultiPoint(pontos), envelope=limite)
    saida = []
    for (nome, lat, lon, regiao), p in zip(catalogo.BAIRROS_SP, pontos):
        cel = next(c for c in celulas.geoms if c.contains(p))
        poly = cel.intersection(limite)
        mp = poly if isinstance(poly, MultiPolygon) else MultiPolygon([poly])
        saida.append((nome, regiao, mp, p))
    return saida


def ja_tem_dados(db) -> bool:
    return db.scalar(select(func.count()).select_from(Orgao)) > 0


def seed(quantidade: int) -> None:
    t0 = time.time()
    db = SessionLocal()

    # Órgãos
    orgaos = {o["sigla"]: Orgao(**o) for o in catalogo.ORGAOS}
    db.add_all(orgaos.values())

    # Cidades e bairros
    c = catalogo.CIDADE_PRINCIPAL
    sp = Cidade(nome=c["nome"], uf=c["uf"], tem_lista_bairros=True, centro=ewkt(c["centro"][1], c["centro"][0]))
    c2 = catalogo.CIDADE_SEM_BAIRROS
    gru = Cidade(nome=c2["nome"], uf=c2["uf"], tem_lista_bairros=False, centro=ewkt(c2["centro"][1], c2["centro"][0]))
    db.add_all([sp, gru])
    db.flush()

    bairros_geo = gerar_bairros()
    bairros = []
    for nome, regiao, mp, _ in bairros_geo:
        b = Bairro(cidade_id=sp.id, nome=nome, regiao=regiao, geom=f"SRID=4326;{mp.wkt}")
        bairros.append(b)
    db.add_all(bairros)

    # Tipos
    tipos: dict[str, TipoEquipamento] = {}
    for t in catalogo.TIPOS:
        campos = {k: v for k, v in t.items() if k != "marcas"}
        campos["schema_atributos"] = com_ordem(campos["schema_atributos"])
        tipos[t["prefixo"]] = TipoEquipamento(**campos)
    db.add_all(tipos.values())
    db.flush()

    # Bases operacionais (onde ficam os móveis e os agentes)
    bases: dict[str, list[BaseOperacional]] = {}
    coord_base: dict[tuple[str, int], tuple[float, float]] = {}
    for sigla, org in orgaos.items():
        bases[sigla] = []
        for i in range(random.randint(3, 5)):
            nome_b, _, _, centro = random.choice(bairros_geo)
            lon, lat = centro.x + random.gauss(0, 0.003), centro.y + random.gauss(0, 0.003)
            coord_base[(sigla, i)] = (lon, lat)
            base = BaseOperacional(
                nome=f"Base {sigla} {nome_b}", orgao_id=org.id, cidade_id=sp.id,
                endereco=f"{fake.street_name()}, {random.randint(10, 2000)}", geom=ewkt(lon, lat),
            )
            bases[sigla].append(base)
            db.add(base)
    db.flush()
    print(f"[seed] cadastros básicos em {time.time() - t0:.1f}s")

    arvore = STRtree([mp for _, _, mp, _ in bairros_geo])
    seq_por_tipo = {p: 0 for p in tipos}
    catalogo_por_prefixo = {t["prefixo"]: t for t in catalogo.TIPOS}

    equipamentos, localizacoes, planos, ordens = [], [], [], []
    vida: list[dict] = []          # entrada do gerador da Parte 3
    tem_iot_por_id: dict[int, bool] = {}
    seriais_usados: dict[str, list[tuple[str, str]]] = {}
    pares_usados: set[tuple[str, str]] = set()
    moveis_por_orgao: dict[tuple[str, str], list[int]] = {}

    for eid in range(1, quantidade + 1):
        prefixo = escolher(catalogo.PESO_TIPO)
        tdef = catalogo_por_prefixo[prefixo]
        tipo = tipos[prefixo]
        sigla = escolher(catalogo.DONO_POR_TIPO[prefixo])
        seq_por_tipo[prefixo] += 1
        marca = random.choice(list(tdef["marcas"]))
        modelo = random.choice(tdef["marcas"][marca])
        movel = tdef["mobilidade"] == "movel"
        num_serie = chassi() if prefixo in ("VTR", "MOT", "VIA", "VAF") else serie(prefixo)
        while (marca, num_serie) in pares_usados:
            num_serie = serie(prefixo)

        # Duplicidade plantada: mesmo número de série com a marca escrita diferente.
        if seriais_usados.get(prefixo) and random.random() < 0.004:
            marca_ant, serie_ant = random.choice(seriais_usados[prefixo])
            if (marca_ant.upper() + " ", serie_ant) not in pares_usados:
                marca, num_serie = marca_ant.upper() + " ", serie_ant
        seriais_usados.setdefault(prefixo, []).append((marca, num_serie))
        pares_usados.add((marca, num_serie))

        predefinida = escolher(DIST_PREDEFINIDA)
        cuidado = CUIDADO_ORGAO[sigla]  # órgãos com cadastro mais ou menos caprichado
        tem_iot_por_id[eid] = random.random() > 0.07 * cuidado
        instalado_em = HOJE - timedelta(days=random.randint(30, 365 * 7))
        desativado_em = None
        if predefinida == S.desativado:
            desativado_em = instalado_em + timedelta(days=random.randint(10, max(11, (HOJE - instalado_em).days - 1)))

        atributos = atributos_para(prefixo, tdef)
        equipamentos.append({
            "id": eid,
            "codigo_interno": f"{prefixo}-{seq_por_tipo[prefixo]:04d}",
            "tipo_id": tipo.id,
            "numero_serie": num_serie,
            "marca": marca,
            "modelo": modelo,
            "orgao_id": orgaos[sigla].id,
            "dispositivo_iot_id": f"IOT-{eid:06d}-{random.randint(0, 0xFFFF):04X}" if tem_iot_por_id[eid] else None,
            "ultimo_sinal_em": None,
            "situacao": S.nao_instalado,
            "data_instalacao": instalado_em if predefinida != S.nao_instalado else None,
            "atributos": atributos,
            "score_saude": 100,
            "score_motivos": [],
        })
        if movel:
            moveis_por_orgao.setdefault((sigla, prefixo), []).append(eid)

        # Localização: fixos no ponto de instalação; móveis na base.
        if movel:
            blon, blat = coord_base[(sigla, random.randrange(len(bases[sigla])))]
            lon, lat = blon + random.gauss(0, 0.0003), blat + random.gauss(0, 0.0003)
            regiao = None
        else:
            nome_b, regiao, mp, centro = random.choice(bairros_geo)
            lon, lat = centro.x + random.gauss(0, 0.008), centro.y + random.gauss(0, 0.008)
        cidade_id = sp.id
        bairro_id = None
        bairro_real = None
        idx = arvore.query(Point(lon, lat), predicate="within")
        if len(idx):
            bairro_id = bairros[int(idx[0])].id
            bairro_real, regiao = bairros_geo[int(idx[0])][0], bairros_geo[int(idx[0])][1]
        regiao_real = regiao
        r = random.random()
        if r < 0.003:
            lon, lat = lon + random.choice([-1, 1]) * random.uniform(0.6, 3), lat + random.uniform(0.5, 2)  # longe da cidade
        elif r < 0.01 and bairro_id:
            bairro_id = random.choice(bairros).id  # bairro divergente do ponto
        elif r < 0.01 + 0.06 * cuidado:
            bairro_id = None  # bairro não informado
        if random.random() < 0.03:
            cidade_id, bairro_id, regiao = gru.id, None, None
            lon, lat = -46.5333 + random.gauss(0, 0.02), -23.4538 + random.gauss(0, 0.02)
            bairro_real = regiao_real = None
        sem_geom = random.random() < 0.004
        localizacoes.append({
            "equipamento_id": eid, "cidade_id": cidade_id, "rua": fake.street_name(),
            "cep": f"0{random.randint(1000, 5999)}-{random.randint(0, 999):03d}" if random.random() > 0.3 * cuidado else None,
            "bairro_id": bairro_id, "referencia": referencia(), "regiao": regiao,
            "geom": None if sem_geom else ewkt(lon, lat),
        })
        vida.append({
            "id": eid, "prefixo": prefixo, "marca": marca, "atributos": atributos,
            "instalado_em": instalado_em if predefinida != S.nao_instalado else None, "desativado_em": desativado_em,
            "regiao": regiao_real, "bairro": bairro_real, "lon": None if sem_geom else lon, "lat": None if sem_geom else lat,
            "movel": movel, "periodicidade": tdef["periodicidade_padrao_dias"],
        })

    # Vida dos equipamentos: anos simples antes, 18 meses com padrões plantados (Parte 3).
    inicio_hist = HOJE - timedelta(days=DIAS_HISTORICO)
    clima_dia = {}
    for k in range(DIAS_HISTORICO + 2):
        d = inicio_hist - timedelta(days=1) + timedelta(days=k)
        horas = clima_mod.dia(d, SEMENTE)
        clima_dia[d] = (sum(h["chuva_mm"] for h in horas), max(h["temperatura_c"] for h in horas))
    usuarios = [fake.name() for _ in range(300)]
    t_vida = time.time()
    res = gerador_equipamentos.simular(vida, inicio_hist, HOJE, clima_dia, SEMENTE, usuarios)
    print(f"[seed] vida simulada: {len(res.historicos)} mudanças de situação, {len(res.registros)} manutenções "
          f"em {time.time() - t_vida:.1f}s")

    plano_por_eq: dict[int, int] = {}
    for e, v in zip(equipamentos, vida):
        eid = e["id"]
        fim = res.situacao[eid]
        e["situacao"] = fim
        ultimo = res.ultimo.get(eid)
        # Sinal IoT
        if tem_iot_por_id[eid] and fim != S.nao_instalado:
            intervalo = catalogo_por_prefixo[v["prefixo"]]["intervalo_sinal_esperado_min"]
            if fim == S.operacional:
                silencioso = random.random() < 0.012
                atraso = random.uniform(intervalo * 1.5, intervalo * 40) if silencioso else random.uniform(0, intervalo * 0.8)
                e["ultimo_sinal_em"] = AGORA - timedelta(minutes=atraso)
            else:
                e["ultimo_sinal_em"] = (ultimo["em"] if ultimo else AGORA) - timedelta(minutes=random.uniform(1, 600))
        # Planos de manutenção (o periódico existe mesmo para desativados, inativo, porque as preventivas apontam para ele)
        periodo = v["periodicidade"]
        if fim != S.nao_instalado and periodo:
            pid = len(planos) + 1
            plano_por_eq[eid] = pid
            proxima = res.proxima_preventiva.get(eid) or HOJE + timedelta(days=random.randint(1, periodo))
            planos.append({"id": pid, "equipamento_id": eid, "tipo": TipoPlano.periodica, "proxima_data": proxima,
                           "periodicidade_dias": periodo, "descricao": "Manutenção preventiva periódica",
                           "ativo": fim != S.desativado})
        if fim == S.mau_funcionamento and ultimo:
            planos.append({"id": len(planos) + 1, "equipamento_id": eid, "tipo": TipoPlano.imediata,
                           "proxima_data": ultimo["em"].date(), "periodicidade_dias": None,
                           "descricao": f"Manutenção imediata: {ultimo['motivo']}", "ativo": True})
            ordens.append({"equipamento_id": eid, "motivo": f"Mau funcionamento: {ultimo['motivo']}",
                           "prioridade": PrioridadeOS.alta, "status": StatusOS.aberta, "aberta_em": ultimo["em"]})
    registros = []
    for r in res.registros:
        prev = r.pop("preventiva")
        r["plano_id"] = plano_por_eq.get(r["equipamento_id"]) if prev else None
        registros.append(r)

    def inserir(modelo, linhas, lote=5000):
        for i in range(0, len(linhas), lote):
            db.execute(insert(modelo), linhas[i:i + lote])

    inserir(Equipamento, equipamentos)
    db.execute(text("SELECT setval('equipamento_id_seq', (SELECT max(id) FROM equipamento))"))
    inserir(Localizacao, localizacoes)
    inserir(HistoricoSituacao, sorted(res.historicos, key=lambda h: h["em"]))
    inserir(PlanoManutencao, planos)
    db.execute(text("SELECT setval('plano_manutencao_id_seq', (SELECT max(id) FROM plano_manutencao))"))
    inserir(RegistroManutencao, registros)
    inserir(OrdemServico, ordens)
    db.merge(EstadoPreditivo(chave="historico", valor={
        "semente": SEMENTE, "data_referencia": HOJE.isoformat(), "inicio": inicio_hist.isoformat(),
        "gerado_em": AGORA.isoformat()}))
    print(f"[seed] {len(equipamentos)} equipamentos, {len(res.historicos)} históricos em {time.time() - t0:.1f}s")

    # Agentes
    agentes = []
    cat_por_orgao = {"CET": CategoriaAgente.agente_transito, "GCM": CategoriaAgente.guarda_municipal,
                     "PM": CategoriaAgente.policial_militar}
    qtd_agentes = max(30, quantidade // 15)
    usados: set[int] = set()
    for i in range(qtd_agentes):
        sigla = escolher({"CET": 0.4, "GCM": 0.33, "PM": 0.27})
        veiculo = None
        if random.random() < 0.45:
            pool = moveis_por_orgao.get((sigla, random.choice(["MOT", "VIA"])), [])
            livres = [v for v in random.sample(pool, min(len(pool), 10)) if v not in usados]
            if livres:
                veiculo = livres[0]
                usados.add(veiculo)
        agentes.append({
            "nome": fake.name(), "matricula": f"{sigla}{100000 + i}",
            "categoria": cat_por_orgao[sigla], "orgao_id": orgaos[sigla].id,
            "equipe": f"Equipe {random.choice(['Alfa', 'Bravo', 'Charlie', 'Delta', 'Eco'])}-{random.randint(1, 9)}",
            "situacao": escolher({SituacaoAgente.em_atividade: 0.6, SituacaoAgente.em_pausa: 0.1,
                                  SituacaoAgente.fora_de_escala: 0.3}),
            "contato": fake.cellphone_number(), "veiculo_id": veiculo,
            "base_id": random.choice(bases[sigla]).id,
        })
    inserir(Agente, agentes)
    db.flush()

    print("[seed] calculando score, manutenção e alertas...")
    res = derivados.recalcular(db, None, AGORA)
    db.commit()
    db.execute(text("ANALYZE"))
    db.commit()
    print(f"[seed] {qtd_agentes} agentes; {res}; total {time.time() - t0:.1f}s")
    db.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--se-vazio", action="store_true", help="só roda se o banco estiver vazio")
    ap.add_argument("--quantidade", type=int, default=settings.seed_equipamentos)
    ap.add_argument("--semente", type=int, default=42)
    ap.add_argument("--data-referencia", type=date.fromisoformat, default=None,
                    help="fim do histórico (padrão: hoje). Mesma semente e mesma data: mesmos dados")
    args = ap.parse_args()
    global HOJE, SEMENTE
    HOJE = args.data_referencia or HOJE
    SEMENTE = args.semente
    random.seed(args.semente)
    Faker.seed(args.semente)
    with SessionLocal() as db:
        if ja_tem_dados(db):
            if args.se_vazio:
                print("[seed] banco já tem dados, pulando")
                return
            raise SystemExit("Banco já tem dados. Rode com banco limpo ou use --se-vazio.")
    seed(args.quantidade)


if __name__ == "__main__":
    main()
