"""Regras puras do motor de interpretação (Parte 2), sem banco.

- Nível inicial de cada regra de detecção.
- Ajuste do nível pelo contexto (cobertura, região em atenção, horário de pico, manutenção).
- Índice de saúde da região.

As funções recebem fatos já carregados e devolvem decisão e motivos, para que a mesma
regra sirva ao motor, aos testes e à explicação na tela.
"""

from dataclasses import dataclass
from datetime import datetime, time

from app.models.enums import NivelAlerta, Situacao, TipoAlerta

N = NivelAlerta
R = TipoAlerta

ORDEM_NIVEL = [N.baixa, N.media, N.alta, N.critica]
ROTULO_NIVEL = {N.baixa: "Baixa", N.media: "Média", N.alta: "Alta", N.critica: "Crítica"}

NIVEL_INICIAL: dict[TipoAlerta, NivelAlerta] = {
    R.furto: N.critica,
    R.incidente_correlacionado: N.critica,
    R.mau_funcionamento: N.alta,
    R.falha_silenciosa: N.alta,
    R.regiao_descoberta: N.alta,
    R.sinal_degradado: N.media,
    R.manutencao_vencida: N.media,
    R.dispositivo_nao_cadastrado: N.media,
    R.agente_sem_posicao: N.media,
    R.manutencao_proxima: N.baixa,
    R.anomalia_equipamento: N.media,
    R.anomalia_regiao: N.alta,
    R.previsao_risco_regiao: N.media,
    R.previsao_falha_equipamento: N.baixa,
    R.previsao_falta_agentes: N.media,
    R.previsao_disponibilidade: N.baixa,
}

ROTULO_REGRA = {
    R.furto: "Furto",
    R.incidente_correlacionado: "Incidente correlacionado",
    R.mau_funcionamento: "Mau funcionamento",
    R.falha_silenciosa: "Falha silenciosa",
    R.regiao_descoberta: "Região descoberta",
    R.sinal_degradado: "Sinal degradado",
    R.manutencao_vencida: "Manutenção vencida",
    R.dispositivo_nao_cadastrado: "Dispositivo não cadastrado",
    R.agente_sem_posicao: "Agente sem posição",
    R.manutencao_proxima: "Manutenção próxima",
    R.anomalia_equipamento: "Anomalia de equipamento",
    R.anomalia_regiao: "Anomalia na região",
    R.previsao_risco_regiao: "Previsão: risco alto na região",
    R.previsao_falha_equipamento: "Previsão: falha de equipamento",
    R.previsao_falta_agentes: "Previsão: falta de agentes",
    R.previsao_disponibilidade: "Previsão: disponibilidade abaixo da meta",
}

# Problemas de equipamento que o contexto pode agravar.
REGRAS_COM_CONTEXTO = {R.furto, R.mau_funcionamento, R.falha_silenciosa, R.sinal_degradado}
# Problemas que, juntos na mesma região e janela, sugerem queda de energia ou de rede.
REGRAS_CORRELACIONAVEIS = {R.mau_funcionamento, R.falha_silenciosa, R.sinal_degradado}
# Furto nunca é suprimido por manutenção em andamento.
NUNCA_SUPRIMIR = {R.furto}
SEM_ALERTA = {Situacao.desativado, Situacao.nao_instalado}
# Parte 3: alertas preventivos falam do futuro; não pesam na saúde atual da região.
PREVENTIVAS = {R.previsao_risco_regiao, R.previsao_falha_equipamento, R.previsao_falta_agentes, R.previsao_disponibilidade}


def subir(n: NivelAlerta) -> NivelAlerta:
    return ORDEM_NIVEL[min(len(ORDEM_NIVEL) - 1, ORDEM_NIVEL.index(n) + 1)]


def rank(n: NivelAlerta | str | None) -> int:
    """0 sem alerta, 1 baixa ... 4 crítica."""
    if n is None:
        return 0
    return ORDEM_NIVEL.index(NivelAlerta(n)) + 1


def nome_curto(nome_tipo: str) -> tuple[str, str]:
    """("câmera", "outra") a partir de "Câmera de videomonitoramento"."""
    palavra = nome_tipo.split()[0].lower() if nome_tipo else "equipamento"
    return palavra, "outra" if palavra.endswith("a") else "outro"


@dataclass
class Contexto:
    situacao: Situacao | None = None
    manutencao_em_andamento: bool = False
    sem_cobertura: bool = False
    nome_tipo: str = ""
    regiao: str | None = None
    regiao_em_atencao: bool = False
    horario_pico: bool = False
    raio_m: int = 500


def decidir_nivel(regra: TipoAlerta, ctx: Contexto | None) -> tuple[NivelAlerta | None, list[str]]:
    """Nível final e motivos. None quando o alerta não deve existir (suprimido ou fora da conta)."""
    nivel = NIVEL_INICIAL[regra]
    if ctx is None or regra not in REGRAS_COM_CONTEXTO:
        return nivel, []
    if ctx.situacao in SEM_ALERTA:
        return None, ["equipamento desativado ou ainda não instalado"]
    if ctx.manutencao_em_andamento and regra not in NUNCA_SUPRIMIR:
        return None, ["manutenção planejada em andamento"]

    motivos: list[str] = []
    causas = []
    if ctx.sem_cobertura:
        palavra, outro = nome_curto(ctx.nome_tipo)
        causas.append(f"sem {outro} {palavra} operacional em {ctx.raio_m} m")
    if ctx.regiao_em_atencao and ctx.regiao:
        causas.append(f"região {ctx.regiao} já em atenção")
    if ctx.horario_pico and ctx.regiao:
        causas.append(f"horário de pico na região {ctx.regiao}")
    for causa in causas:
        novo = subir(nivel)
        if novo != nivel:
            motivos.append(f"{ROTULO_NIVEL[nivel]} → {ROTULO_NIVEL[novo]}: {causa}")
        else:
            motivos.append(f"Já crítica; também: {causa}")
        nivel = novo
    return nivel, motivos


def _hora(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def em_pico(picos: list[dict] | None, agora_local: datetime) -> bool:
    """agora_local já no fuso da cidade. dias: 0 = segunda ... 6 = domingo."""
    for p in picos or []:
        if agora_local.weekday() not in p.get("dias", range(7)):
            continue
        if _hora(p["inicio"]) <= agora_local.time() < _hora(p["fim"]):
            return True
    return False


# ---------- Índice de saúde da região ----------

ESTADOS_REGIAO = ("normal", "atencao", "critica")


def estado_por_nota(nota: int) -> str:
    if nota >= 80:
        return "normal"
    if nota >= 50:
        return "atencao"
    return "critica"


def indice_regiao(alertas: dict[str, int], disponibilidade: float | None, agentes_ativos: int, cfg: dict) -> dict:
    """Começa em 100 e perde pontos por fator. Nunca abaixo de 0.

    alertas: alertas em estado "aberto" por nível ({"critica": 1, "alta": 2, "media": 5}).
    disponibilidade: 0 a 1, ou None quando a região não tem equipamento na conta.
    """
    pen = cfg["saude_penalidade"]
    fatores: list[dict] = []

    def add(chave: str, texto: str, pontos: float) -> None:
        if pontos > 0:
            fatores.append({"fator": chave, "texto": texto, "pontos": -round(pontos)})

    n = alertas.get("critica", 0)
    add("critica", f"{n} alerta{'s' if n != 1 else ''} crítico{'s' if n != 1 else ''}", n * pen["critica"])
    n = alertas.get("alta", 0)
    add("alta", f"{n} alerta{'s' if n != 1 else ''} alto{'s' if n != 1 else ''}", n * pen["alta"])
    n = alertas.get("media", 0)
    teto = cfg.get("saude_teto_media")
    pts = n * pen["media"]
    add("media", f"{n} alerta{'s' if n != 1 else ''} médio{'s' if n != 1 else ''}" + (" (com teto)" if teto and pts > teto else ""),
        min(pts, teto) if teto else pts)
    meta = cfg["saude_meta_disponibilidade"]
    if disponibilidade is not None and disponibilidade * 100 < meta:
        falta = meta - disponibilidade * 100
        add("disponibilidade", f"disponibilidade {disponibilidade * 100:.1f}% (meta {meta}%)".replace(".", ","), falta)
    if agentes_ativos == 0:
        add("sem_agentes", "nenhum agente em atividade", cfg["saude_sem_agentes"])

    nota = max(0, 100 + sum(f["pontos"] for f in fatores))
    return {"nota": nota, "estado": estado_por_nota(nota), "fatores": sorted(fatores, key=lambda f: f["pontos"])}
