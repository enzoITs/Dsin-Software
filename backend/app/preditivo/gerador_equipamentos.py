"""Vida dos equipamentos no período do histórico, com os padrões 4, 5, 6, 7 e 11.

Usado pelo seed da Parte 1: em vez de espalhar falhas ao acaso, simula dia a dia (vetorizado com
NumPy) quem falha, quem é furtado, quando a manutenção chega e quando a preventiva é feita.
Antes do período, a vida do equipamento continua simples (alguns ciclos de falha e conserto).

Determinístico: mesma semente e mesma data de referência geram o mesmo histórico.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import numpy as np

from app.models.enums import Situacao as S
from app.preditivo import padroes as P
from app.preditivo.clima import FUSO

OP, MAU, MAN, FUR, DES, FORA = 0, 1, 2, 3, 4, -1
NOME = {OP: S.operacional, MAU: S.mau_funcionamento, MAN: S.em_manutencao, FUR: S.furtado, DES: S.desativado}
NUNCA = 10**6

MOTIVO_FALHA = {
    "CAM": ["Lente danificada", "Imagem sem foco", "Falha de comunicação", "Queda de energia recorrente"],
    "RAD": ["Leitura inconsistente", "Sensor sem resposta", "Falha de comunicação", "Superaquecimento do gabinete"],
    "_": ["Falha de comunicação", "Queda de energia recorrente", "Leitura inconsistente", "Defeito mecânico"],
}


@dataclass
class Resultado:
    historicos: list[dict] = field(default_factory=list)
    registros: list[dict] = field(default_factory=list)   # "preventiva": True quando ligado ao plano periódico
    situacao: dict[int, S] = field(default_factory=dict)
    proxima_preventiva: dict[int, date] = field(default_factory=dict)
    ultimo: dict[int, dict] = field(default_factory=dict)  # último histórico de cada equipamento


def _quando(d: date, hora: int, minuto: int) -> datetime:
    return datetime(d.year, d.month, d.day, hora, minuto, tzinfo=FUSO).astimezone(timezone.utc)


def _camera_perto(equips: list[dict], alvo: np.ndarray) -> np.ndarray:
    """Para cada equipamento marcado em `alvo`, se há câmera a menos de RAIO_CAMERA_M."""
    cams = np.array([(e["lon"], e["lat"]) for e in equips if e["prefixo"] == "CAM" and e["lon"] is not None])
    saida = np.zeros(len(equips), dtype=bool)
    if not len(cams):
        return saida
    graus = P.RAIO_CAMERA_M / 111_000
    for i in np.flatnonzero(alvo):
        e = equips[i]
        if e["lon"] is None:
            continue
        d2 = ((cams[:, 0] - e["lon"]) * 0.917) ** 2 + (cams[:, 1] - e["lat"]) ** 2  # cos(-23,5°) ≈ 0,917
        perto = d2 < graus**2
        saida[i] = perto.sum() > (1 if e["prefixo"] == "CAM" else 0)  # a própria câmera não conta
    return saida


def _antes_do_periodo(e: dict, inicio: date, rng: np.random.Generator, usuarios: list[str], res: Resultado) -> int:
    """Vida simples antes do período gerado. Devolve o estado no início do período."""
    inst = e["instalado_em"]
    t0 = _quando(inst, 9, int(rng.integers(0, 60)))
    fim_pre = min(inicio, e["desativado_em"]) if e["desativado_em"] else inicio
    dias = max(1, (fim_pre - inst).days)
    trilha = [S.operacional]
    for _ in range(int(rng.choice([0, 1, 2], p=[0.6, 0.3, 0.1])) if dias > 60 else 0):
        trilha += [S.mau_funcionamento, S.em_manutencao, S.operacional]
    desativou = e["desativado_em"] is not None and e["desativado_em"] < inicio
    if desativou:
        trilha.append(S.desativado)
    passo = dias / (len(trilha) + 1)
    atual = S.nao_instalado
    ultimo_em = None
    for i, nova in enumerate(trilha):
        em = t0 + timedelta(days=passo * i + float(rng.uniform(0, passo * 0.5)), minutes=int(rng.integers(0, 600)))
        if ultimo_em:
            em = max(em, ultimo_em + timedelta(hours=1))
        motivo = {S.operacional: "Instalação concluída" if atual == S.nao_instalado else "Manutenção concluída",
                  S.mau_funcionamento: str(rng.choice(MOTIVO_FALHA["_"])), S.em_manutencao: "Ordem de serviço aberta",
                  S.desativado: str(rng.choice(["Fim da vida útil", "Remanejamento"]))}[nova]
        h = {"equipamento_id": e["id"], "situacao_anterior": atual, "situacao_nova": nova, "motivo": motivo,
             "usuario": usuarios[int(rng.integers(len(usuarios)))], "em": em}
        res.historicos.append(h)
        res.ultimo[e["id"]] = h
        if atual == S.em_manutencao and nova == S.operacional:
            res.registros.append({"equipamento_id": e["id"], "executada_em": em, "descricao": "Manutenção corretiva",
                                  "tecnico": h["usuario"], "resultado": "concluida", "preventiva": False})
        atual, ultimo_em = nova, em
    return DES if desativou else OP


def simular(equips: list[dict], inicio: date, fim: date, clima_dia: dict[date, tuple[float, float]],
            semente: int, usuarios: list[str]) -> Resultado:
    """Simula de `inicio` (inclusive) a `fim` (exclusive).

    equips: [{id, prefixo, marca, atributos, instalado_em, desativado_em, regiao, bairro, lon, lat,
              movel, periodicidade}]; instalado_em None = nunca instalado.
    clima_dia: data -> (chuva total do dia em mm, temperatura máxima em °C).
    """
    rng = np.random.default_rng(P.chave("equipamentos", semente, inicio.isoformat()))
    res = Resultado()
    n = len(equips)
    D = (fim - inicio).days
    prefixo = np.array([e["prefixo"] for e in equips], dtype=object)
    base = np.array([P.FALHA_BASE_DIA.get(p, 0.0025) for p in prefixo])
    fragil = np.array([e["prefixo"] == "CAM" and e["marca"].strip().lower() == P.MARCA_FRAGIL for e in equips])
    rodovia = np.array([e["prefixo"] == "RAD" and (e["atributos"] or {}).get("modalidade") == "velocidade"
                        and (e["atributos"] or {}).get("velocidade_maxima", 0) >= P.VELOCIDADE_RODOVIA for e in equips])
    movel = np.array([bool(e["movel"]) for e in equips])
    leste = np.array([e["regiao"] == P.REGIAO_SEM_PREVENTIVA and not e["movel"] for e in equips])
    furtavel = np.array([e["prefixo"] in P.TIPOS_FURTAVEIS for e in equips])
    bairro_furto = np.array([e["bairro"] in P.BAIRROS_FURTO and not e["movel"] for e in equips])
    cam_perto = _camera_perto(equips, bairro_furto)
    period = np.array([e["periodicidade"] or 0 for e in equips])
    fragilidade = rng.lognormal(0, 0.35, n)  # cada equipamento é um pouco diferente

    def dia_idx(d: date | None) -> int:
        return NUNCA if d is None else (d - inicio).days

    inst = np.array([dia_idx(e["instalado_em"]) for e in equips])
    desat = np.array([dia_idx(e["desativado_em"]) for e in equips])
    estado = np.full(n, FORA)
    prox_acao = np.full(n, NUNCA)          # dia da próxima transição agendada
    repor = np.zeros(n, dtype=bool)        # furtado que será reposto
    vence = np.full(n, NUNCA)              # dia em que vence a preventiva
    executa = np.full(n, NUNCA)            # dia em que a preventiva será de fato feita
    inicio_abandono = int(D * P.FRACAO_INICIO_ABANDONO)

    def sortear_execucao(idx: np.ndarray) -> None:
        if not len(idx):
            return
        faixa = rng.choice(len(P.ATRASO_PREVENTIVA), size=len(idx), p=[f[0] for f in P.ATRASO_PREVENTIVA])
        lo = np.array([P.ATRASO_PREVENTIVA[f][1] for f in faixa])
        hi = np.array([P.ATRASO_PREVENTIVA[f][2] for f in faixa])
        atraso = rng.integers(lo, hi + 1)
        abandonada = leste[idx] & (vence[idx] >= inicio_abandono) & (rng.random(len(idx)) > P.PREVENTIVA_FEITA_NO_ABANDONO)
        executa[idx] = np.where(abandonada, NUNCA, vence[idx] + atraso)

    def agendar_preventiva(idx: np.ndarray, t: int, primeira: bool = False) -> None:
        idx = idx[period[idx] > 0]
        if not len(idx):
            return
        if primeira:
            vence[idx] = t + rng.integers(1, period[idx] + 1)
        else:
            vence[idx] = t + period[idx]
        sortear_execucao(idx)

    def registrar(i: int, d: date, hora: int, anterior: int, nova: int, motivo: str) -> None:
        h = {"equipamento_id": equips[i]["id"], "situacao_anterior": S.nao_instalado if anterior == FORA else NOME[anterior],
             "situacao_nova": NOME[nova], "motivo": motivo, "usuario": usuarios[int(rng.integers(len(usuarios)))],
             "em": _quando(d, hora, int(rng.integers(0, 60)))}
        res.historicos.append(h)
        res.ultimo[equips[i]["id"]] = h

    # Antes do período
    for i, e in enumerate(equips):
        if e["instalado_em"] is not None and inst[i] < 0:
            estado[i] = _antes_do_periodo(e, inicio, rng, usuarios, res)
    agendar_preventiva(np.flatnonzero(estado == OP), 0, primeira=True)

    for t in range(D):
        d = inicio + timedelta(days=t)
        chuva_ontem = clima_dia.get(d - timedelta(days=1), (0.0, 25.0))[0]
        tmax = clima_dia.get(d, (0.0, 25.0))[1]
        mexeu = np.zeros(n, dtype=bool)

        # Instalações
        for i in np.flatnonzero(inst == t):
            registrar(i, d, int(rng.integers(8, 17)), FORA, OP, "Instalação concluída")
            estado[i] = OP
            mexeu[i] = True
        agendar_preventiva(np.flatnonzero(inst == t), t)

        # Desativações
        for i in np.flatnonzero((desat == t) & (estado >= 0) & (estado != DES) & ~mexeu):
            registrar(i, d, int(rng.integers(8, 17)), int(estado[i]), DES,
                      str(rng.choice(["Fim da vida útil", "Remanejamento", "Não recuperado"])))
            estado[i], prox_acao[i], mexeu[i] = DES, NUNCA, True

        # Transições agendadas
        for i in np.flatnonzero((prox_acao == t) & ~mexeu):
            hora = int(rng.integers(8, 18))
            if estado[i] == MAU:
                registrar(i, d, hora, MAU, MAN, "Ordem de serviço aberta")
                estado[i], prox_acao[i] = MAN, t + 1 + int(rng.integers(0, 3))
            elif estado[i] == MAN:
                registrar(i, d, hora, MAN, OP, "Manutenção concluída")
                res.registros.append({"equipamento_id": equips[i]["id"], "executada_em": res.ultimo[equips[i]["id"]]["em"],
                                      "descricao": "Manutenção corretiva", "tecnico": res.ultimo[equips[i]["id"]]["usuario"],
                                      "resultado": "concluida", "preventiva": False})
                estado[i], prox_acao[i] = OP, NUNCA  # conserto corretivo não substitui a preventiva
            elif estado[i] == FUR:
                if repor[i]:
                    registrar(i, d, hora, FUR, MAN, "Reposição do equipamento furtado")
                    estado[i], prox_acao[i] = MAN, t + 1 + int(rng.integers(0, 4))
                else:
                    registrar(i, d, hora, FUR, DES, "Não recuperado")
                    estado[i], prox_acao[i] = DES, NUNCA
            mexeu[i] = True

        # Preventivas feitas hoje (só em quem está operando)
        for i in np.flatnonzero((executa <= t) & (estado == OP) & ~mexeu):
            res.registros.append({"equipamento_id": equips[i]["id"],
                                  "executada_em": _quando(d, int(rng.integers(8, 17)), int(rng.integers(0, 60))),
                                  "descricao": "Manutenção preventiva periódica", "tecnico": usuarios[int(rng.integers(len(usuarios)))],
                                  "resultado": "concluida", "preventiva": True})
            vence[i] = t + period[i]
            sortear_execucao(np.array([i]))

        # Falhas
        ativo = (estado == OP) & ~mexeu
        idade = np.where(inst == NUNCA, 0, t - inst)  # dias desde a instalação (inst negativo = antes do período)
        atraso = np.where(vence < NUNCA, t - vence, 0)
        h = P.risco_falha_dia(base, idade, fragil, rodovia, atraso, fragilidade, chuva_ontem, tmax)
        for i in np.flatnonzero(ativo & (rng.random(n) < h)):
            motivos = MOTIVO_FALHA.get(prefixo[i], MOTIVO_FALHA["_"])
            registrar(i, d, int(rng.integers(0, 24)), OP, MAU, str(rng.choice(motivos)))
            espera = P.ESPERA_CONSERTO_DIAS
            if leste[i] and t >= inicio_abandono:  # padrão 11: conserto cada vez mais lento
                espera += (P.ESPERA_CONSERTO_ABANDONO_MAX - P.ESPERA_CONSERTO_DIAS) * (t - inicio_abandono) / max(1, D - inicio_abandono)
            estado[i], prox_acao[i], mexeu[i] = MAU, t + 1 + int(rng.gamma(2.0, espera / 2.0)), True

        # Furtos
        candidatos = ((estado == OP) | (estado == MAU)) & ~mexeu & ~movel | ((prefixo == "PAT") & (estado == OP) & ~mexeu)
        hf = P.risco_furto_dia(furtavel, bairro_furto, cam_perto)
        for i in np.flatnonzero(candidatos & (rng.random(n) < hf)):
            hora = int(rng.choice(P.HORAS_MADRUGADA)) if bairro_furto[i] or rng.random() < 0.4 else int(rng.integers(0, 24))
            registrar(i, d, hora, int(estado[i]), FUR,
                      str(rng.choice(["Equipamento não encontrado no local", "Furto de cabos e módulo",
                                      "Boletim de ocorrência registrado"])))
            estado[i], prox_acao[i], repor[i] = FUR, t + int(rng.integers(5, 30)), rng.random() < 0.55

    for i, e in enumerate(equips):
        if estado[i] == FORA:
            res.situacao[e["id"]] = S.nao_instalado
            continue
        res.situacao[e["id"]] = NOME[int(estado[i])]
        if period[i] > 0 and estado[i] != DES and vence[i] < NUNCA:
            res.proxima_preventiva[e["id"]] = inicio + timedelta(days=int(vence[i]))
    return res
