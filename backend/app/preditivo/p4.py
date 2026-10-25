"""P4: recomendação de reforço de agentes por região e período.

Duas etapas:
1. Demanda: agentes-hora necessários em cada região e período = ocorrências previstas (P2) ×
   `prev_agentes_por_ocorrencia`. O peso de cada região na otimização sobe com o índice de risco (P3).
2. Alocação: programação linear inteira (HiGHS, pelo `scipy.optimize.milp`, funciona sem internet)
   que redistribui as equipes já escaladas no período, minimizando o risco não coberto
   (Σ peso × agentes-hora que faltam), com as restrições:
   - cada equipe fica numa região só;
   - nenhuma região fica com menos equipes que o mínimo (ou que tinha, se tinha menos);
   - cada região mantém ao menos uma equipe de cada órgão que já tinha (trânsito, guarda, polícia);
   - no máximo `max_deslocamentos` equipes trocam de região no período;
   - região em risco "Muito alto" recebe ao menos uma equipe a mais (se for possível);
   - uma região não cede e recebe equipes no mesmo período (trocas confundem e não ajudam o gestor).
   Se a otimização falhar ou passar do tempo, uma heurística gulosa documentada faz a alocação.

Funções puras: recebem equipes e regiões, devolvem a alocação e o risco não coberto antes e depois.
"""

import time
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


@dataclass
class Equipe:
    id: str                 # chave única no período (id do turno na escala)
    nome: str
    orgao: str              # sigla do órgão: CET, GCM, PM
    regiao: str             # região onde está escalada
    capacidade: float       # agentes-hora dentro do período
    agentes: int = 0


@dataclass
class Regiao:
    nome: str
    demanda: float          # agentes-hora necessários
    peso: float = 1.0       # importância do que falta cobrir (sobe com o risco)
    muito_alto: bool = False


@dataclass
class Resultado:
    alocacao: dict[str, str]                 # equipe -> região
    metodo: str                              # otimizacao, heuristica, escala_atual
    status: str = ""
    nao_coberto_antes: float = 0.0
    nao_coberto_depois: float = 0.0
    por_regiao: dict[str, dict] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    segundos: float = 0.0

    @property
    def movimentos(self) -> int:
        return len(self.por_regiao.get("_movimentos", []))

    @property
    def reducao_pct(self) -> float | None:
        if self.nao_coberto_antes <= 0:
            return None
        return (self.nao_coberto_antes - self.nao_coberto_depois) / self.nao_coberto_antes * 100


def capacidade_por_regiao(alocacao: dict[str, str], equipes: list[Equipe], regioes: list[Regiao]) -> dict[str, float]:
    cap = {r.nome: 0.0 for r in regioes}
    por_id = {e.id: e for e in equipes}
    for eid, reg in alocacao.items():
        cap[reg] = cap.get(reg, 0.0) + por_id[eid].capacidade
    return cap


def nao_coberto(alocacao: dict[str, str], equipes: list[Equipe], regioes: list[Regiao], ponderado: bool = True) -> float:
    """Risco não coberto: Σ peso × max(0, demanda − capacidade), em agentes-hora."""
    cap = capacidade_por_regiao(alocacao, equipes, regioes)
    return float(sum((r.peso if ponderado else 1.0) * max(0.0, r.demanda - cap[r.nome]) for r in regioes))


def _minimos(equipes: list[Equipe], regioes: list[Regiao], min_por_regiao: int) -> tuple[dict, dict]:
    atual = {r.nome: sum(1 for e in equipes if e.regiao == r.nome) for r in regioes}
    minimo = {r: min(min_por_regiao, n) for r, n in atual.items()}
    orgaos = {r.nome: sorted({e.orgao for e in equipes if e.regiao == r.nome}) for r in regioes}
    return minimo, orgaos


def violacoes(alocacao: dict[str, str], equipes: list[Equipe], regioes: list[Regiao], max_deslocamentos: int,
              min_por_regiao: int = 1, fixas: set[str] | None = None) -> list[str]:
    """Lista as restrições desrespeitadas (vazia = alocação válida). Usada nos testes e como checagem final."""
    erros = []
    nomes = {r.nome for r in regioes}
    if set(alocacao) != {e.id for e in equipes}:
        erros.append("toda equipe precisa de exatamente uma região")
    if any(v not in nomes for v in alocacao.values()):
        erros.append("região desconhecida")
    minimo, orgaos = _minimos(equipes, regioes, min_por_regiao)
    for r in regioes:
        n = sum(1 for e in equipes if alocacao.get(e.id) == r.nome)
        if n < minimo[r.nome]:
            erros.append(f"{r.nome} abaixo do mínimo de equipes")
        for o in orgaos[r.nome]:
            if not any(alocacao.get(e.id) == r.nome and e.orgao == o for e in equipes):
                erros.append(f"{r.nome} sem equipe do órgão {o}")
    for r in regioes:
        cede = any(e.regiao == r.nome and alocacao.get(e.id) != r.nome for e in equipes)
        recebe = any(e.regiao != r.nome and alocacao.get(e.id) == r.nome for e in equipes)
        if cede and recebe:
            erros.append(f"{r.nome} cede e recebe equipes no mesmo período")
    mov = sum(1 for e in equipes if alocacao.get(e.id) != e.regiao)
    if mov > max_deslocamentos:
        erros.append(f"{mov} deslocamentos, acima do máximo de {max_deslocamentos}")
    for e in equipes:
        if fixas and e.regiao in fixas and alocacao.get(e.id) != e.regiao:
            erros.append(f"equipe {e.nome} saiu de região fixa")
    return erros


def otimizar(equipes: list[Equipe], regioes: list[Regiao], max_deslocamentos: int = 4, min_por_regiao: int = 1,
             fixas: set[str] | None = None, exigir_muito_alto: bool = True, tempo_max_s: float = 10.0) -> Resultado:
    t0 = time.time()
    original = {e.id: e.regiao for e in equipes}
    antes = nao_coberto(original, equipes, regioes)
    if not equipes or not regioes:
        return _fechar(Resultado(original, "escala_atual", "sem equipes"), equipes, regioes, antes, t0)
    T, R = len(equipes), len(regioes)
    nomes = [r.nome for r in regioes]
    ri = {n: j for j, n in enumerate(nomes)}
    nx = T * R
    xi = lambda t, r: t * R + r  # noqa: E731
    ny = nx + R          # depois de x e da falta u, uma variável por região: 1 = recebe, 0 = pode ceder
    total = ny + R
    minimo, orgaos = _minimos(equipes, regioes, min_por_regiao)
    media_cap = float(np.mean([e.capacidade for e in equipes])) or 1.0

    c = np.zeros(total)
    for t, e in enumerate(equipes):
        for r in range(R):
            if nomes[r] != e.regiao:
                c[xi(t, r)] = 0.01 * media_cap      # deslocar tem um custo pequeno: só se valer a pena
    c[nx:ny] = [r.peso for r in regioes]

    linhas, lo, hi = [], [], []

    def restr(coef: dict[int, float], a: float, b: float) -> None:
        v = np.zeros(total)
        for k, val in coef.items():
            v[k] = val
        linhas.append(v)
        lo.append(a)
        hi.append(b)

    for t in range(T):                                                   # cada equipe numa região
        restr({xi(t, r): 1 for r in range(R)}, 1, 1)
    for r, reg in enumerate(regioes):                                    # falta: u_r ≥ demanda − capacidade
        coef = {xi(t, r): e.capacidade for t, e in enumerate(equipes)}
        coef[nx + r] = 1
        restr(coef, reg.demanda, np.inf)
        restr({xi(t, r): 1 for t in range(T)}, minimo[reg.nome], np.inf)  # mínimo de equipes
        for o in orgaos[reg.nome]:                                       # órgãos que a região já tinha
            restr({xi(t, r): 1 for t, e in enumerate(equipes) if e.orgao == o}, 1, np.inf)
    restr({xi(t, r): 1 for t, e in enumerate(equipes) for r in range(R) if nomes[r] != e.regiao}, 0, max_deslocamentos)
    for r in range(R):                                                   # não ceder e receber no mesmo período
        de_fora = {xi(t, r): 1 for t, e in enumerate(equipes) if e.regiao != nomes[r]}
        restr({**de_fora, ny + r: -T}, -np.inf, 0)                       # recebe só se y_r = 1
        da_casa = [t for t, e in enumerate(equipes) if e.regiao == nomes[r]]
        if da_casa:                                                      # cede (casa < n) só se y_r = 0
            restr({**{xi(t, r): -1 for t in da_casa}, ny + r: len(da_casa)}, -np.inf, 0)
    ub = np.ones(total)
    ub[nx:ny] = np.inf
    lb = np.zeros(total)
    for t, e in enumerate(equipes):                                      # regiões fixas: ninguém sai
        if fixas and e.regiao in fixas:
            lb[xi(t, ri[e.regiao])] = 1
    muito_alto = [r for r, reg in enumerate(regioes) if reg.muito_alto]
    extras = []
    if exigir_muito_alto:
        for r in muito_alto:
            atual = sum(1 for e in equipes if e.regiao == nomes[r])
            v = np.zeros(total)
            for t in range(T):
                v[xi(t, r)] = 1
            extras.append((v, atual + 1))

    integralidade = np.r_[np.ones(nx), np.zeros(R), np.ones(R)]
    for tentativa in (extras, []):
        A = np.array(linhas + [v for v, _ in tentativa])
        a = np.array(lo + [b for _, b in tentativa])
        b = np.array(hi + [np.inf for _ in tentativa])
        res = milp(c, constraints=LinearConstraint(A, a, b), integrality=integralidade, bounds=Bounds(lb, ub),
                   options={"time_limit": tempo_max_s, "disp": False})
        if res.status == 0 and res.x is not None:
            x = res.x[:nx].reshape(T, R)
            aloc = {e.id: nomes[int(np.argmax(x[t]))] for t, e in enumerate(equipes)}
            r = Resultado(aloc, "otimizacao", "ótima")
            if muito_alto and not tentativa and extras:
                r.avisos.append("Não foi possível reforçar todas as regiões em risco muito alto com as restrições atuais")
            if not violacoes(aloc, equipes, regioes, max_deslocamentos, min_por_regiao, fixas):
                return _fechar(r, equipes, regioes, antes, t0)
        if not tentativa:
            break
    r = guloso(equipes, regioes, max_deslocamentos, min_por_regiao, fixas)
    r.status = f"otimização sem solução ({res.message}); heurística gulosa usada"
    return _fechar(r, equipes, regioes, antes, t0)


def guloso(equipes: list[Equipe], regioes: list[Regiao], max_deslocamentos: int = 4, min_por_regiao: int = 1,
           fixas: set[str] | None = None) -> Resultado:
    """Heurística de reserva: a cada passo, move a equipe que mais reduz o risco não coberto, sem quebrar
    nenhuma restrição; regiões em risco muito alto têm prioridade. Para quando nada mais ajuda."""
    aloc = {e.id: e.regiao for e in equipes}
    minimo, orgaos = _minimos(equipes, regioes, min_por_regiao)
    for _ in range(max_deslocamentos):
        atual = nao_coberto(aloc, equipes, regioes)
        melhor = None
        for e in equipes:
            if aloc[e.id] != e.regiao or (fixas and e.regiao in fixas):
                continue                                                # cada equipe se move no máximo uma vez
            for r in regioes:
                if r.nome == e.regiao:
                    continue
                teste = {**aloc, e.id: r.nome}
                if violacoes(teste, equipes, regioes, max_deslocamentos, min_por_regiao, fixas):
                    continue
                ganho = atual - nao_coberto(teste, equipes, regioes) + (1e6 if r.muito_alto and
                                                                         sum(1 for v in aloc.values() if v == r.nome) <=
                                                                         sum(1 for x in equipes if x.regiao == r.nome) else 0)
                if ganho > 1e-9 and (melhor is None or ganho > melhor[0]):
                    melhor = (ganho, e.id, r.nome)
        if melhor is None:
            break
        aloc[melhor[1]] = melhor[2]
    return Resultado(aloc, "heuristica", "heurística gulosa")


def _fechar(r: Resultado, equipes: list[Equipe], regioes: list[Regiao], antes: float, t0: float) -> Resultado:
    r.nao_coberto_antes = antes
    r.nao_coberto_depois = nao_coberto(r.alocacao, equipes, regioes)
    cap_antes = capacidade_por_regiao({e.id: e.regiao for e in equipes}, equipes, regioes)
    cap_depois = capacidade_por_regiao(r.alocacao, equipes, regioes)
    for reg in regioes:
        r.por_regiao[reg.nome] = {
            "demanda": round(reg.demanda, 1), "capacidade_antes": round(cap_antes[reg.nome], 1),
            "capacidade_depois": round(cap_depois[reg.nome], 1),
            "equipes_antes": sum(1 for e in equipes if e.regiao == reg.nome),
            "equipes_depois": sum(1 for e in equipes if r.alocacao[e.id] == reg.nome),
            "falta_antes": round(max(0.0, reg.demanda - cap_antes[reg.nome]), 1),
            "falta_depois": round(max(0.0, reg.demanda - cap_depois[reg.nome]), 1),
        }
    r.por_regiao["_movimentos"] = [{"equipe": e.nome, "id": e.id, "orgao": e.orgao, "de": e.regiao, "para": r.alocacao[e.id],
                                    "agentes": e.agentes} for e in equipes if r.alocacao[e.id] != e.regiao]
    r.segundos = round(time.time() - t0, 3)
    return r
