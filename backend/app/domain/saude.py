"""Score de saúde de 0 a 100, sempre acompanhado dos motivos.

A função `calcular` é pura: recebe os fatos já carregados e devolve nota e motivos.
Assim o mesmo cálculo serve para um equipamento (na ficha) e para milhares (no job).
"""

from dataclasses import dataclass
from datetime import date, datetime

from app.models.enums import Situacao

PENALIDADE_POR_FALHA = 10
MAX_PENALIDADE_FALHAS = 40


@dataclass
class FatosSaude:
    situacao: Situacao
    falhas_90d: int
    furtos_365d: int
    dias_manutencao_atrasada: int  # 0 se em dia
    sem_sinal: bool
    tem_dispositivo_iot: bool
    data_instalacao: date | None
    ultima_manutencao: datetime | None


def calcular(f: FatosSaude, hoje: date) -> tuple[int, list[dict]]:
    motivos: list[dict] = []

    def penaliza(pontos: int, texto: str, chave: str) -> None:
        if pontos > 0:
            motivos.append({"chave": chave, "texto": texto, "pontos": -pontos})

    if f.situacao == Situacao.furtado:
        penaliza(50, "equipamento furtado", "furtado")
    elif f.situacao == Situacao.mau_funcionamento:
        penaliza(25, "em mau funcionamento", "mau_funcionamento")
    elif f.situacao == Situacao.em_manutencao:
        penaliza(10, "em manutenção", "em_manutencao")

    if f.falhas_90d:
        pontos = min(MAX_PENALIDADE_FALHAS, f.falhas_90d * PENALIDADE_POR_FALHA)
        plural = "falha" if f.falhas_90d == 1 else "falhas"
        penaliza(pontos, f"{f.falhas_90d} {plural} em 90 dias", "falhas_90d")

    if f.furtos_365d:
        penaliza(min(20, f.furtos_365d * 10), f"{f.furtos_365d} furto(s) no último ano", "furtos")

    if f.dias_manutencao_atrasada > 0:
        d = f.dias_manutencao_atrasada
        penaliza(min(30, 8 + 2 * d), f"manutenção atrasada há {d} dia{'s' if d != 1 else ''}", "manutencao_vencida")

    if f.sem_sinal:
        penaliza(15, "sem sinal além do intervalo esperado", "sem_sinal")

    if not f.tem_dispositivo_iot:
        penaliza(5, "sem módulo IoT vinculado", "sem_iot")

    if f.data_instalacao:
        anos = (hoje - f.data_instalacao).days / 365
        if anos > 5:
            penaliza(min(15, int(anos - 5) * 5 + 5), f"instalado há {int(anos)} anos", "idade")
        if anos > 1 and f.ultima_manutencao is None:
            penaliza(10, "nenhuma manutenção registrada", "sem_manutencao")

    score = max(0, 100 + sum(m["pontos"] for m in motivos))
    return score, motivos
