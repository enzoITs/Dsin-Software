"""Simulador de telemetria: faz a cidade "respirar" para a central.

Uso: python -m scripts.simulador_telemetria [--api URL] [--ciclo SEGUNDOS] [--posicao SEGUNDOS] [--eventos]

- A cada `--ciclo` (60 s): sinal de presença de cada equipamento operacional com módulo IoT,
  com métricas (qualidade da imagem das câmeras, bateria dos patinetes).
- A cada `--posicao` (15 s): posição dos móveis (viaturas, motos, táxis, patinetes...) e dos
  agentes em atividade, andando pela cidade.

Não envia nada para os "parados" (lista em simulador_parados.json, controlada pela API em
/simulador/parados, e os parados pela simulação de incidentes em simulacao_estado.json),
nem para os "mudos" (1% dos módulos com defeito fixo, sempre os mesmos). Parados e mudos,
passado 3 vezes o intervalo do tipo, viram alerta de "possível falha silenciosa".

Com --eventos, também gera de vez em quando falhas e furtos aleatórios pela própria API.

Modo contínuo da Parte 3 (ligado por padrão; --sem-continuo desliga): a cada `--continuo`
segundos gera as ocorrências e as séries das horas que passaram, com os mesmos padrões do
histórico, e uma vez por hora aplica pela API as falhas, furtos e consertos sorteados pelos
mesmos padrões. Assim as previsões de ontem podem ser conferidas com o que "aconteceu".
"""

import argparse
import json
import math
import random
import time
import zlib
from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.db import SessionLocal
from app.preditivo import historico
from app.models import Agente, Equipamento, Localizacao, TipoEquipamento
from app.models.enums import Situacao, SituacaoAgente

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_PARADOS = RAIZ / "simulador_parados.json"
ARQUIVO_SIMULACAO = RAIZ / "simulacao_estado.json"
LOTE = 1000
LIMITE = (-46.78, -23.68, -46.43, -23.46)  # São Paulo (lon_min, lat_min, lon_max, lat_max)
# Metros andados por ciclo de posição de 15 s.
PASSO_M = {"VTR": 110, "MOT": 90, "VIA": 80, "VAF": 40, "PAT": 35}


def _ler(arquivo: Path):
    try:
        return json.loads(arquivo.read_text())
    except (FileNotFoundError, ValueError):
        return None


def parados() -> set[str]:
    return set(_ler(ARQUIVO_PARADOS) or [])


def simulacao() -> dict:
    return _ler(ARQUIVO_SIMULACAO) or {}


def mudo(codigo: str, fracao: float) -> bool:
    """Módulos com defeito fixo: sempre os mesmos, para a demonstração ter falhas silenciosas reais."""
    return zlib.crc32(codigo.encode()) % 10_000 < fracao * 10_000


class Cidade:
    def __init__(self) -> None:
        self.fixos: list[tuple[int, str, str, str]] = []           # id, código, iot, prefixo (e móveis sem ponto)
        self.moveis: dict[int, dict] = {}                          # id -> {cod, iot, pref, lon, lat, rumo}
        self.agentes: dict[int, dict] = {}                         # id -> {lon, lat, rumo, passo}
        self.bateria: dict[int, float] = {}

    def carregar(self) -> None:
        with SessionLocal() as db:
            linhas = db.execute(
                select(Equipamento.id, Equipamento.codigo_interno, Equipamento.dispositivo_iot_id, TipoEquipamento.prefixo,
                       TipoEquipamento.mobilidade,
                       func.ST_X(func.coalesce(Equipamento.posicao, Localizacao.geom)),
                       func.ST_Y(func.coalesce(Equipamento.posicao, Localizacao.geom)))
                .join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
                .outerjoin(Localizacao, Localizacao.equipamento_id == Equipamento.id)
                .where(Equipamento.situacao == Situacao.operacional, Equipamento.dispositivo_iot_id.is_not(None))
            ).all()
            ags = db.execute(
                select(Agente.id, Agente.veiculo_id, func.ST_X(Agente.posicao), func.ST_Y(Agente.posicao))
                .where(Agente.situacao == SituacaoAgente.em_atividade, Agente.posicao.is_not(None))
            ).all()
        self.fixos = []
        moveis = {}
        for i, cod, iot, pref, mob, x, y in linhas:
            if getattr(mob, "value", mob) == "movel":
                if x is None:  # móvel sem ponto no cadastro: só manda presença, como um fixo
                    self.fixos.append((i, cod, iot, pref))
                    continue
                antigo = self.moveis.get(i)
                moveis[i] = antigo or {"cod": cod, "iot": iot, "pref": pref, "lon": x, "lat": y, "rumo": random.uniform(0, 360)}
            else:
                self.fixos.append((i, cod, iot, pref))
        self.moveis = moveis
        self.agentes = {
            i: self.agentes.get(i) or {"lon": x, "lat": y, "rumo": random.uniform(0, 360), "passo": 60 if v else 22}
            for i, v, x, y in ags
        }


def andar(p: dict, metros: float) -> None:
    p["rumo"] = (p["rumo"] + random.gauss(0, 25)) % 360
    r = math.radians(p["rumo"])
    lon = p["lon"] + metros * math.sin(r) / (111320 * math.cos(math.radians(p["lat"])))
    lat = p["lat"] + metros * math.cos(r) / 110540
    if not (LIMITE[0] < lon < LIMITE[2] and LIMITE[1] < lat < LIMITE[3]):
        p["rumo"] = (p["rumo"] + 180) % 360
        return
    p["lon"], p["lat"] = lon, lat


def enviar(cliente: httpx.Client, caminho: str, itens: list[dict]) -> None:
    for i in range(0, len(itens), LOTE):
        cliente.post(caminho, json=itens[i:i + LOTE]).raise_for_status()


def ciclo_posicoes(cliente: httpx.Client, cidade: Cidade, fora: set[str], fracao_mudos: float) -> str:
    sinais = []
    for p in cidade.moveis.values():
        if p["cod"] in fora or mudo(p["cod"], fracao_mudos):
            continue
        if p["pref"] == "PAT" and random.random() > 0.3:  # patinete passa a maior parte do tempo parado
            sinais.append({"dispositivo_iot_id": p["iot"], "tipo": "posicao", "lon": p["lon"], "lat": p["lat"]})
            continue
        andar(p, PASSO_M.get(p["pref"], 50) * random.uniform(0.4, 1.2))
        sinais.append({"dispositivo_iot_id": p["iot"], "tipo": "posicao", "lon": round(p["lon"], 6), "lat": round(p["lat"], 6)})
    enviar(cliente, "/telemetria/sinais", sinais)
    agentes = []
    for i, p in cidade.agentes.items():
        andar(p, p["passo"] * random.uniform(0, 1.2))
        agentes.append({"agente_id": i, "lon": round(p["lon"], 6), "lat": round(p["lat"], 6)})
    enviar(cliente, "/telemetria/agentes", agentes)
    return f"{len(sinais)} móveis e {len(agentes)} agentes"


def ciclo_presenca(cliente: httpx.Client, cidade: Cidade, fora: set[str], sem_metrica: set[str], fracao_mudos: float) -> str:
    sinais = []
    for i, cod, iot, pref in cidade.fixos:
        if cod in fora or mudo(cod, fracao_mudos):
            continue
        s = {"dispositivo_iot_id": iot}
        if pref == "CAM" and cod not in sem_metrica:
            s.update(tipo="metrica", valores={"qualidade": random.randint(78, 99)})
        sinais.append(s)
    for i, p in cidade.moveis.items():
        if p["pref"] != "PAT" or p["cod"] in fora or p["cod"] in sem_metrica or mudo(p["cod"], fracao_mudos):
            continue
        b = cidade.bateria.get(i, random.uniform(40, 100)) - random.uniform(0.2, 1.5)
        cidade.bateria[i] = b if b > 25 else 100.0  # a operadora troca a bateria antes de acabar
        sinais.append({"dispositivo_iot_id": p["iot"], "tipo": "metrica", "valores": {"bateria": round(cidade.bateria[i])}})
    enviar(cliente, "/telemetria/sinais", sinais)
    return f"{len(sinais)} sinais de presença"


def evento_aleatorio(cliente: httpx.Client, cidade: Cidade) -> str:
    if not cidade.fixos or random.random() > 0.3:
        return ""
    eid, cod, _, _ = random.choice(cidade.fixos)
    nova, motivo = random.choice([
        ("mau_funcionamento", "Simulador: leitura inconsistente"),
        ("mau_funcionamento", "Simulador: queda de comunicação"),
        ("furtado", "Simulador: equipamento não encontrado"),
    ])
    r = cliente.patch(f"/equipamentos/{eid}/situacao", json={"situacao": nova, "motivo": motivo},
                      headers={"X-Usuario": "simulador"})
    return f"; evento {cod} -> {nova} ({r.status_code})"


def ciclo_continuo(cliente: httpx.Client, ultima_hora: list) -> str:
    """Avança o histórico da cidade e, uma vez por hora, mexe nos equipamentos pela API."""
    with SessionLocal() as db:
        res = historico.avancar(db, log=lambda m: print(m, flush=True))
        hora = historico.ultima_hora_gerada(db)
        acoes = []
        if hora is not None and hora != ultima_hora[0]:
            acoes = historico.acoes_equipamentos(db)
            ultima_hora[0] = hora
    feitas = 0
    cab = {"X-Usuario": historico.USUARIO}
    for a in acoes:
        if a["situacao"] == "operacional":
            r = cliente.post(f"/equipamentos/{a['id']}/registros-manutencao", headers=cab,
                             json={"tecnico": "Equipe de manutenção", "descricao": "Manutenção corretiva", "resultado": "concluida"})
        else:
            r = cliente.patch(f"/equipamentos/{a['id']}/situacao", headers=cab,
                              json={"situacao": a["situacao"], "motivo": a["motivo"]})
        feitas += r.status_code < 300
    if not res and not acoes:
        return ""
    return f"; contínuo: {res.get('ocorrencias', 0)} ocorrências, {feitas}/{len(acoes)} mudanças em equipamentos"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--ciclo", type=int, default=60, help="segundos entre sinais de presença dos fixos")
    ap.add_argument("--posicao", type=int, default=15, help="segundos entre posições de móveis e agentes")
    ap.add_argument("--eventos", action="store_true", help="gera falhas e furtos de vez em quando")
    ap.add_argument("--mudos", type=float, default=0.01, help="fração de módulos que nunca mandam sinal")
    ap.add_argument("--continuo", type=int, default=300, help="segundos entre passos do modo contínuo da Parte 3")
    ap.add_argument("--sem-continuo", action="store_true", help="desliga o modo contínuo da Parte 3")
    args = ap.parse_args()
    cidade = Cidade()
    ultimo_presenca = ultimo_carga = ultimo_continuo = 0.0
    ultima_hora: list = [None]
    with httpx.Client(base_url=args.api, timeout=60) as cliente:
        while True:
            inicio = time.time()
            try:
                if inicio - ultimo_carga > 60:
                    cidade.carregar()
                    ultimo_carga = inicio
                sim = simulacao()
                fora = parados() | set(sim.get("parados", []))
                msg = ciclo_posicoes(cliente, cidade, fora, args.mudos)
                if inicio - ultimo_presenca >= args.ciclo:
                    msg += "; " + ciclo_presenca(cliente, cidade, fora, set(sim.get("sem_metrica", [])), args.mudos)
                    ultimo_presenca = inicio
                    if args.eventos:
                        msg += evento_aleatorio(cliente, cidade)
                if not args.sem_continuo and inicio - ultimo_continuo >= args.continuo:
                    msg += ciclo_continuo(cliente, ultima_hora)
                    ultimo_continuo = inicio
                print(f"[simulador] {msg} em {time.time() - inicio:.1f}s; {len(fora)} parados", flush=True)
            except httpx.HTTPError as exc:
                print(f"[simulador] API indisponível ({exc}); tentando de novo", flush=True)
            except Exception as exc:  # banco ainda sendo criado na primeira subida
                print(f"[simulador] aguardando o banco ({type(exc).__name__}: {exc}); tentando de novo", flush=True)
            time.sleep(max(1.0, args.posicao - (time.time() - inicio)))


if __name__ == "__main__":
    main()
