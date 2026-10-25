"""P3: índice de risco de 0 a 100 por região, por hora e por período do dia.

Cinco componentes explicáveis, cada um de 0 a 100, somados com pesos configuráveis
(`prev_p3_pesos`, padrão 40/20/15/15/10):

1. Ocorrências previstas (P2), ponderadas pela gravidade, em relação ao normal da região.
2. Equipamentos já fora de operação ou com alto risco de falha (P1 e Parte 2).
3. Cobertura prevista de câmeras e radares.
4. Agentes previstos pela escala em relação à demanda prevista.
5. Fatores externos: eventos grandes e chuva forte.

Funções puras: recebem números, devolvem o índice e quanto cada componente somou.
"""

from dataclasses import dataclass

import numpy as np

COMPONENTES = ("ocorrencias", "equipamentos", "cobertura", "agentes", "externos")
NOMES = {
    "ocorrencias": "Ocorrências previstas",
    "equipamentos": "Equipamentos fora de operação ou em risco",
    "cobertura": "Cobertura de câmeras e radares",
    "agentes": "Agentes na escala × demanda",
    "externos": "Eventos e clima",
}
FAIXAS = ((75, "MUITO_ALTO", "Muito alto"), (50, "ALTO", "Alto"), (25, "MODERADO", "Moderado"), (0, "BAIXO", "Baixo"))
PERIODOS = (("madrugada", 0, 6), ("manha", 6, 12), ("tarde", 12, 18), ("noite", 18, 24))
NOME_PERIODO = {"madrugada": "Madrugada (0 h às 6 h)", "manha": "Manhã (6 h às 12 h)", "tarde": "Tarde (12 h às 18 h)",
                "noite": "Noite (18 h às 24 h)"}


@dataclass
class Entrada:
    """O que se sabe (ou se prevê) de uma região numa hora ou período."""

    previstas: float                # ocorrências previstas (P2), soma das horas
    normal: float                   # ocorrências normais da região no mesmo número de horas (média geral)
    gravidade_media: float          # gravidade média recente da região
    gravidade_normal: float         # gravidade média da cidade
    fixos: int                      # equipamentos fixos em serviço na região
    indisponiveis: int              # já fora de operação
    alto_risco: int                 # em operação com risco alto ou muito alto (P1, 7 dias)
    vigilancia: int                 # câmeras e radares em serviço
    vigilancia_operando: int
    vigilancia_risco: int
    agentes: float                  # agentes-hora na escala
    demanda_agentes: float          # agentes-hora necessários pela demanda prevista
    evento_publico: int = 0
    evento_nome: str | None = None
    chuva_mm: float = 0.0           # maior chuva prevista numa hora
    tempestade: bool = False


def _clip(x: float) -> float:
    return float(np.clip(x, 0, 100))


def notas(e: Entrada) -> dict[str, float]:
    """Nota de 0 a 100 de cada componente (100 = pior)."""
    razao = (e.previstas * e.gravidade_media / max(e.gravidade_normal, 1e-6)) / max(e.normal, 1e-6)
    frac_equip = (e.indisponiveis + e.alto_risco) / max(e.fixos, 1)
    cobertura = (e.vigilancia_operando - e.vigilancia_risco) / max(e.vigilancia, 1)
    atendimento = e.agentes / max(e.demanda_agentes, 1e-6)
    externos = max(e.evento_publico / 40_000 * 100, e.chuva_mm / 10 * 100, 100 if e.tempestade else 0)
    return {
        "ocorrencias": _clip((razao - 0.8) * 50),        # normal = 10; o dobro = 60; 2,8 vezes = 100
        "equipamentos": _clip(frac_equip / 0.15 * 100),  # 15% da região fora ou em risco = 100
        "cobertura": _clip((1 - cobertura) / 0.25 * 100),  # 75% de cobertura = 100
        "agentes": _clip((1 - atendimento) / 0.6 * 100),   # escala cobre a demanda = 0; cobre 40% = 100
        "externos": _clip(externos),
    }


def faixa(indice: float) -> tuple[str, str]:
    for limite, codigo, nome in FAIXAS:
        if indice >= limite:
            return codigo, nome
    return "BAIXO", "Baixo"


def _fmt(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def descricao(c: str, e: Entrada) -> str:
    if c == "ocorrencias":
        razao = e.previstas / max(e.normal, 1e-6)
        return f"{_fmt(e.previstas)} ocorrências previstas, {_fmt(razao)}× o normal da região"
    if c == "equipamentos":
        return f"{e.indisponiveis} equipamentos fora de operação e {e.alto_risco} com risco alto de falha"
    if c == "cobertura":
        cob = (e.vigilancia_operando - e.vigilancia_risco) / max(e.vigilancia, 1)
        return f"{cob:.0%} das câmeras e radares operando sem risco alto".replace(".", ",")
    if c == "agentes":
        return f"{_fmt(e.agentes, 0)} agentes-hora na escala para uma demanda de {_fmt(e.demanda_agentes, 0)}"
    partes = []
    if e.evento_publico:
        partes.append(f"{e.evento_nome or 'Evento'} com {_fmt(e.evento_publico / 1000, 0)} mil pessoas")
    if e.tempestade:
        partes.append("alerta de tempestade")
    elif e.chuva_mm >= 0.5:
        partes.append(f"chuva de até {_fmt(e.chuva_mm)} mm por hora")
    return "; ".join(partes).capitalize() if partes else "Sem evento grande nem chuva prevista"


def indice(e: Entrada, pesos: dict[str, float]) -> dict:
    """Índice, nível e quanto cada componente somou (peso × nota). A soma das contribuições é o índice."""
    n = notas(e)
    total_pesos = sum(pesos[c] for c in COMPONENTES) or 1
    comps = []
    for c in COMPONENTES:
        w = pesos[c] / total_pesos
        comps.append({"componente": c, "nome": NOMES[c], "nota": round(n[c], 1), "peso": round(w, 4),
                      "contribuicao": round(w * n[c], 2), "descricao": descricao(c, e)})
    valor = round(sum(x["contribuicao"] for x in comps), 1)
    codigo, nome = faixa(valor)
    principal = max(comps, key=lambda x: x["contribuicao"])
    return {"indice": valor, "nivel": codigo, "nivel_nome": nome, "componentes": comps, "motivo_principal": principal["descricao"]}


def somar(entradas: list[Entrada]) -> Entrada:
    """Junta horas num período: somas para contagens, máximos para eventos e chuva."""
    e0 = entradas[0]
    return Entrada(
        previstas=sum(e.previstas for e in entradas), normal=sum(e.normal for e in entradas),
        gravidade_media=e0.gravidade_media, gravidade_normal=e0.gravidade_normal, fixos=e0.fixos,
        indisponiveis=e0.indisponiveis, alto_risco=e0.alto_risco, vigilancia=e0.vigilancia,
        vigilancia_operando=e0.vigilancia_operando, vigilancia_risco=e0.vigilancia_risco,
        agentes=sum(e.agentes for e in entradas), demanda_agentes=sum(e.demanda_agentes for e in entradas),
        evento_publico=max(e.evento_publico for e in entradas),
        evento_nome=next((e.evento_nome for e in sorted(entradas, key=lambda e: -e.evento_publico) if e.evento_nome), None),
        chuva_mm=max(e.chuva_mm for e in entradas), tempestade=any(e.tempestade for e in entradas),
    )


def periodo_da_hora(hora: int) -> str:
    return next(p for p, a, b in PERIODOS if a <= hora < b)
