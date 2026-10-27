"""Copiloto (C3): perguntas em português sobre as previsões, respondidas com os dados do sistema.

- Com IA (ANTHROPIC_API_KEY definida): o Claude recebe ferramentas que consultam as mesmas previsões
  da API (risco por região, equipamentos em risco, reforços, anomalias, alertas preventivos, qualidade
  dos modelos, contexto do dia, cenários "e se") e responde citando os cartões de previsão.
- Sem IA (sem chave, sem internet ou erro): perguntas prontas, respondidas por regras fixas sobre as
  mesmas consultas. A tela mostra qual modo respondeu.

O copiloto só lê e simula: não decide, não grava, não fala de pessoas.
"""

import json
import logging
import re
import unicodedata
from datetime import timedelta

import anthropic
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.preditivo import cenarios, consultas, prever
from app.preditivo.consultas import _fmt
from app.services import ia

log = logging.getLogger("atalaia.copiloto")
MAX_PASSOS = 8


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def _dia(rotulo: str | None):
    hoje = prever.hoje_local()
    r = _sem_acento(rotulo or "hoje")
    return hoje + timedelta(days=2 if "depois" in r else 1 if "amanha" in r else 0)


# ---------------------------------------------------------------- ferramentas

def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


NULO_STR = {"type": ["string", "null"]}
NULO_INT = {"type": ["integer", "null"]}
NULO_NUM = {"type": ["number", "null"]}

FERRAMENTAS = [
    {"name": "risco_por_regiao", "strict": True,
     "description": "Períodos (madrugada, manhã, tarde, noite) com maior índice de risco previsto (0 a 100) nas próximas horas, "
                    "com o motivo principal e o id da previsão. Use para 'onde/quando vai ser pior'.",
     "input_schema": _obj({"horas": {"type": "integer", "description": "Janela à frente, de 6 a 72"},
                           "regiao": {**NULO_STR, "description": "Centro, Norte, Sul, Leste ou Oeste; null para todas"}})},
    {"name": "ocorrencias_previstas", "strict": True,
     "description": "Total de ocorrências previstas para um dia, por região, contra o normal das últimas 8 semanas.",
     "input_schema": _obj({"dia": {"type": "string", "enum": ["hoje", "amanhã", "depois de amanhã"]}})},
    {"name": "equipamentos_em_risco", "strict": True,
     "description": "Equipamentos com maior probabilidade de falhar em 7 ou 30 dias, com o principal fator e se já há OS.",
     "input_schema": _obj({"janela": {"type": "integer", "enum": [7, 30]}, "regiao": NULO_STR,
                           "tipo": {**NULO_STR, "description": "Prefixo do tipo: CAM, RAD, TOT, BAL, CAN, PAT; null para todos"}})},
    {"name": "reforcos_de_equipes", "strict": True,
     "description": "Recomendações pendentes de reforço de equipes (quem vai para onde, quando e por quê).",
     "input_schema": _obj({"horas": {"type": "integer", "description": "Só as que começam nas próximas N horas (até 72)"}})},
    {"name": "anomalias_abertas", "strict": True, "description": "Anomalias abertas agora (equipamentos e regiões fora do padrão).",
     "input_schema": _obj({})},
    {"name": "alertas_preventivos", "strict": True,
     "description": "Alertas preventivos abertos na central (risco alto previsto, falha provável, falta de agentes).",
     "input_schema": _obj({})},
    {"name": "qualidade_dos_modelos", "strict": True,
     "description": "Quanto os modelos acertam: comparação com a média histórica no backtest e conferência dos últimos 7 dias.",
     "input_schema": _obj({})},
    {"name": "contexto_do_dia", "strict": True, "description": "Feriado, eventos e previsão do tempo de um dia.",
     "input_schema": _obj({"dia": {"type": "string", "enum": ["hoje", "amanhã", "depois de amanhã"]}})},
    {"name": "simular_cenario", "strict": True,
     "description": "Simula um 'e se' nas próximas 72 h (nada é gravado) e compara com hoje: chuva, equipes a mais ou a menos "
                    "numa região, evento novo num bairro, equipamentos fora de operação. Campos não usados vão como null.",
     "input_schema": _obj({
         "chuva_mm_por_hora": NULO_NUM, "chuva_comeca_em_horas": NULO_INT, "chuva_dura_horas": NULO_INT,
         "equipes_regiao": NULO_STR, "equipes_delta": {**NULO_INT, "description": "Negativo tira equipes, positivo acrescenta"},
         "evento_bairro": NULO_STR, "evento_publico": NULO_INT, "evento_comeca_em_horas": NULO_INT,
         "equipamentos_fora_tipo": NULO_STR, "equipamentos_fora_regiao": NULO_STR, "equipamentos_fora_quantidade": NULO_INT})},
]


def _parametros_cenario(db: Session, x: dict) -> dict:
    from datetime import datetime, timezone

    agora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    p: dict = {}
    if x.get("chuva_mm_por_hora"):
        ini = agora + timedelta(hours=x.get("chuva_comeca_em_horas") or 0)
        p["clima"] = [{"chuva_mm": float(x["chuva_mm_por_hora"]), "inicio": ini.isoformat(),
                       "fim": (ini + timedelta(hours=x.get("chuva_dura_horas") or 6)).isoformat()}]
    if x.get("equipes_regiao") and x.get("equipes_delta"):
        p["equipes"] = [{"regiao": x["equipes_regiao"], "delta": int(x["equipes_delta"])}]
    if x.get("evento_bairro") and x.get("evento_publico"):
        bid = next((i for i, n in db.execute(text("SELECT id, nome FROM bairro WHERE geom IS NOT NULL"))
                    if _sem_acento(n) == _sem_acento(x["evento_bairro"])), None)
        if bid is None:
            raise cenarios.CenarioInvalido(f"Bairro não encontrado: {x['evento_bairro']}")
        ini = agora + timedelta(hours=x.get("evento_comeca_em_horas") or 24)
        p["eventos"] = [{"nome": "Evento do cenário", "bairro_id": bid, "publico": int(x["evento_publico"]),
                         "inicio": ini.isoformat(), "fim": (ini + timedelta(hours=4)).isoformat()}]
    if x.get("equipamentos_fora_quantidade"):
        p["equipamentos_fora"] = {"prefixo": x.get("equipamentos_fora_tipo"), "regiao": x.get("equipamentos_fora_regiao"),
                                  "quantidade": int(x["equipamentos_fora_quantidade"])}
    return p


def executar(db: Session, nome: str, x: dict) -> dict:
    if nome == "risco_por_regiao":
        return consultas.risco(db, horas=max(6, min(72, int(x.get("horas") or 24))), regiao=x.get("regiao"))
    if nome == "ocorrencias_previstas":
        return consultas.ocorrencias_previstas(db, _dia(x.get("dia")))
    if nome == "equipamentos_em_risco":
        return consultas.equipamentos(db, janela=30 if x.get("janela") == 30 else 7, regiao=x.get("regiao"), tipo=x.get("tipo"))
    if nome == "reforcos_de_equipes":
        return consultas.reforcos(db, horas=max(1, min(72, int(x.get("horas") or 24))))
    if nome == "anomalias_abertas":
        return consultas.anomalias(db)
    if nome == "alertas_preventivos":
        return consultas.alertas_preventivos(db)
    if nome == "qualidade_dos_modelos":
        return consultas.qualidade(db)
    if nome == "contexto_do_dia":
        return consultas.contexto(db, _dia(x.get("dia")))
    if nome == "simular_cenario":
        p = _parametros_cenario(db, x)
        if not p:
            return {"erro": "Nenhuma mudança informada para simular."}
        r = cenarios.simular(db, p)
        return {"frases": r["frases"], "regioes": r["regioes"], "equipes": {k: {kk: v[kk] for kk in ("nao_coberto_escala",
                "nao_coberto_otimizado")} for k, v in r["equipes"].items()}, "aplicado": r["aplicado"]}
    return {"erro": f"Ferramenta desconhecida: {nome}"}


def _ids(v, achados: set[int]) -> None:
    if isinstance(v, dict):
        for k, x in v.items():
            if k == "previsao_id" and isinstance(x, int):
                achados.add(x)
            else:
                _ids(x, achados)
    elif isinstance(v, list):
        for x in v:
            _ids(x, achados)


# ---------------------------------------------------------------- com IA

SYSTEM = """Você é o copiloto do Atalaia (PROMETHEUS), a central de operações de trânsito e segurança viária da cidade.
Responde a gestores e operadores, em português do Brasil, sobre as previsões das próximas horas e dias.

Como responder:
- Use as ferramentas para todo número, região, horário ou equipamento que citar; não invente dados.
- Seja direto: comece pela resposta, depois o porquê em poucas linhas e a ação sugerida. Use listas curtas quando ajudarem.
- Ao citar uma previsão, inclua o id dela no formato [prev_123], para a tela abrir o cartão.
- Diga quando a confiança é moderada ou baixa e quando a pergunta foge do que os dados cobrem.
- Recomende, não decida: quem aceita ou rejeita é a pessoa.
- Fale de lugares, períodos e equipamentos, nunca de pessoas. Não faça previsões sobre indivíduos.
- Os dados desta demonstração são sintéticos; mencione isso só se perguntarem sobre a origem dos dados."""


def _com_ia(db: Session, pergunta: str, historico: list[dict]) -> dict:
    cliente = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120.0, max_retries=1)
    mensagens: list = [{"role": h["papel"] if h["papel"] in ("user", "assistant") else "user", "content": h["texto"]}
                       for h in historico[-8:] if h.get("texto")]
    mensagens.append({"role": "user", "content": pergunta})
    usadas, ids = [], set()
    for _ in range(MAX_PASSOS):
        resp = cliente.beta.messages.create(
            model=ia.MODELO, max_tokens=16000, betas=ia.BETAS, fallbacks="default", system=SYSTEM,
            output_config={"effort": "medium"}, tools=FERRAMENTAS, messages=mensagens)
        if resp.stop_reason == "refusal":
            return {"resposta": "Não consigo responder a esta pergunta. Tente uma das perguntas prontas.", "ferramentas": usadas,
                    "previsoes": sorted(ids)}
        if resp.stop_reason == "pause_turn":
            mensagens.append({"role": "assistant", "content": resp.content})
            continue
        chamadas = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not chamadas:
            texto = "\n".join(b.text for b in resp.content if b.type == "text").strip()
            if resp.stop_reason == "max_tokens":
                texto += "\n\n(Resposta cortada: pergunte de forma mais específica.)"
            return {"resposta": texto or "Sem resposta.", "ferramentas": usadas, "previsoes": sorted(ids)}
        mensagens.append({"role": "assistant", "content": resp.content})
        resultados = []
        for c in chamadas:
            try:
                saida = executar(db, c.name, dict(c.input or {}))
                erro = False
            except cenarios.CenarioInvalido as exc:
                saida, erro = {"erro": str(exc)}, True
            except Exception as exc:  # a ferramenta falhou: o modelo é avisado e segue
                log.exception("ferramenta %s falhou", c.name)
                saida, erro = {"erro": f"Falha ao consultar: {type(exc).__name__}"}, True
            _ids(saida, ids)
            usadas.append({"nome": c.name, "entrada": dict(c.input or {})})
            resultados.append({"type": "tool_result", "tool_use_id": c.id, "is_error": erro,
                               "content": json.dumps(saida, ensure_ascii=False, default=str)})
        mensagens.append({"role": "user", "content": resultados})
    return {"resposta": "A consulta ficou longa demais. Tente uma pergunta mais específica.", "ferramentas": usadas,
            "previsoes": sorted(ids)}


# ---------------------------------------------------------------- sem IA: perguntas prontas

def _cit(pid) -> str:
    return f" [prev_{pid}]" if pid else ""


def _p_risco(db: Session, pergunta: str) -> tuple[str, list]:
    reg = consultas.regiao_citada(pergunta)
    r = consultas.risco(db, horas=24, regiao=reg, limite=5)
    if not r["periodos"]:
        return "Ainda não há previsões de risco. O treino roda sozinho no primeiro start.", []
    p0 = r["periodos"][0]
    linhas = [f"**{p0['regiao']}, {p0['quando']}**: risco {p0['nivel_nome']} (índice {p0['indice']}){_cit(p0['previsao_id'])}. "
              f"Motivo: {p0['motivo']}.", "", "Outros períodos de atenção nas próximas 24 h:"]
    linhas += [f"- {p['regiao']}, {p['quando']}: {p['nivel_nome']} ({p['indice']}){_cit(p['previsao_id'])}" for p in r["periodos"][1:]]
    if p0["nivel"] in ("ALTO", "MUITO_ALTO"):
        linhas += ["", "Sugestão: veja as recomendações de reforço de equipes para esse horário."]
    return "\n".join(linhas), ["risco_por_regiao"]


TIPOS_PALAVRA = {"radar": "RAD", "radares": "RAD", "camera": "CAM", "totem": "TOT", "totens": "TOT", "balanca": "BAL",
                 "cancela": "CAN", "patinete": "PAT"}


def _p_manutencao(db: Session, pergunta: str) -> tuple[str, list]:
    q = _sem_acento(pergunta)
    tipo = next((t for palavra, t in TIPOS_PALAVRA.items() if palavra in q), None)
    r = consultas.equipamentos(db, 7, regiao=consultas.regiao_citada(pergunta), tipo=tipo, limite=8)
    if not r["itens"]:
        return "Ainda não há previsões de falha de equipamentos.", []
    sem_os = [x for x in r["itens"] if not x["os_aberta"]]
    tot = r["totais_por_nivel"]
    linhas = [f"Os equipamentos com maior chance de falhar nos próximos 7 dias ({tot.get('MUITO_ALTO', 0)} em risco muito alto, "
              f"{tot.get('ALTO', 0)} em alto):", ""]
    linhas += [f"- **{x['codigo']}** ({x['regiao'] or 'sem região'}): {_fmt(x['probabilidade'] * 100, 0)}%"
               f"{' · já tem OS' if x['os_aberta'] else ''}. {x['principal_fator'] or ''}{_cit(x['previsao_id'])}" for x in r["itens"]]
    linhas += ["", f"Sugestão: abrir OS preventiva para os {len(sem_os)} sem OS (tela Risco de falha, em lote). {r['selo']}."]
    return "\n".join(linhas), ["equipamentos_em_risco"]


def _p_reforco(db: Session, pergunta: str) -> tuple[str, list]:
    r = consultas.reforcos(db, horas=24)
    if not r["itens"]:
        return "Nenhuma recomendação de reforço pendente para as próximas 24 h: a escala atual cobre a demanda prevista.", []
    linhas = ["Recomendações de reforço para as próximas 24 h (decida na tela Equipes ou no cartão):", ""]
    linhas += [f"- {x['texto']}{_cit(x['previsao_id'])}" for x in r["itens"][:6]]
    return "\n".join(linhas), ["reforcos_de_equipes"]


def _p_anomalias(db: Session, pergunta: str) -> tuple[str, list]:
    r = consultas.anomalias(db)
    if not r["itens"]:
        return "Nenhuma anomalia aberta agora: equipamentos e regiões dentro do padrão esperado.", []
    return "\n".join([f"{len(r['itens'])} anomalias abertas:", ""] + [f"- {x['mensagem']}" for x in r["itens"]]), ["anomalias_abertas"]


def _p_alertas(db: Session, pergunta: str) -> tuple[str, list]:
    r = consultas.alertas_preventivos(db)
    if not r["itens"]:
        return "Nenhum alerta preventivo aberto.", []
    return "\n".join([f"{len(r['itens'])} alertas preventivos abertos na central:", ""]
                     + [f"- {x['mensagem']}{_cit(x['previsao_id'])}" for x in r["itens"]]), ["alertas_preventivos"]


def _p_confianca(db: Session, pergunta: str) -> tuple[str, list]:
    q = consultas.qualidade(db)
    linhas = [f"- Ocorrências (P2): {q['P2']['selo']}. Confiança {q['P2']['confianca']}.",
              f"- Falha de equipamento (P1): {q['P1']['selo']}. Confiança {q['P1']['confianca']}."]
    a = q.get("acertometro_7d")
    intro = "No backtest de 13 semanas, sim: os dois modelos acertam mais que a média histórica, com incerteza à mostra."
    if a:
        if a["erro_modelo"] <= a["erro_media_historica"]:
            intro += " E a conferência dos últimos dias confirma."
        else:
            intro += (" Na conferência dos últimos dias, porém, o modelo de ocorrências errou um pouco mais que a média: "
                      "com poucas horas conferidas, o acaso pesa muito; o número fica mais firme a cada dia.")
        linhas.append(f"- Nos últimos 7 dias ({a['horas_conferidas']} horas conferidas): erro médio de {_fmt(a['erro_modelo'], 2)} "
                      f"ocorrências por região e hora, contra {_fmt(a['erro_media_historica'], 2)} da média histórica; "
                      f"{_fmt(a['dentro_da_faixa'] * 100, 0)}% dos valores reais caíram dentro da faixa prevista.")
    return "\n".join([intro, ""] + linhas
                     + ["", "Detalhes na tela Confiança dos modelos."]), ["qualidade_dos_modelos"]


def _p_cenario(params: dict, titulo: str):
    def f(db: Session, pergunta: str) -> tuple[str, list]:
        try:
            r = cenarios.simular(db, params(db) if callable(params) else params)
        except cenarios.CenarioInvalido as exc:
            return f"Não foi possível simular: {exc}", []
        return "\n".join([f"{titulo} (simulação, nada foi alterado):", ""] + [f"- {x}" for x in r["frases"]]
                         + ["", "Monte outras variações na tela Cenários."]), ["simular_cenario"]
    return f


def _chuva_amanha(db: Session) -> dict:
    from app.preditivo.variaveis import FUSO
    import pandas as pd

    ini = pd.Timestamp(prever.hoje_local() + timedelta(days=1)).tz_localize(FUSO) + pd.Timedelta(hours=6)
    return {"clima": [{"chuva_mm": 15, "inicio": ini.isoformat(), "fim": (ini + pd.Timedelta(hours=4)).isoformat()}]}


PRONTAS = [
    {"id": "risco_24h", "texto": "Onde o risco vai ser maior nas próximas 24 horas?", "chaves": ["risco", "pior", "onde", "maior"],
     "f": _p_risco},
    {"id": "manutencao", "texto": "Quais equipamentos devo mandar para manutenção esta semana?",
     "chaves": ["manutencao", "equipamento", "falhar", "quebrar", "os"], "f": _p_manutencao},
    {"id": "reforco", "texto": "Onde vale reforçar equipes nas próximas horas?", "chaves": ["reforc", "equipe", "agente", "escala"],
     "f": _p_reforco},
    {"id": "alertas", "texto": "Quais alertas preventivos estão abertos?", "chaves": ["alerta", "preventiv"], "f": _p_alertas},
    {"id": "anomalias", "texto": "Tem alguma anomalia agora?", "chaves": ["anomalia", "estranho", "fora do padrao"], "f": _p_anomalias},
    {"id": "confianca", "texto": "Os modelos estão acertando?", "chaves": ["acert", "confia", "erro", "modelo", "qualidade"],
     "f": _p_confianca},
    {"id": "chuva", "texto": "E se chover forte amanhã de manhã?", "chaves": ["chuva", "chover", "temporal"],
     "f": _p_cenario(_chuva_amanha, "Com 15 mm/h de chuva amanhã das 6 h às 10 h")},
    {"id": "menos_equipes", "texto": "E se o Centro ficar com 2 equipes a menos?", "chaves": ["menos equipe", "tirar", "sem equipe"],
     "f": _p_cenario({"equipes": [{"regiao": "Centro", "delta": -2}]}, "Com 2 equipes a menos no Centro em cada período")},
]


def prontas() -> list[dict]:
    return [{"id": p["id"], "texto": p["texto"]} for p in PRONTAS]


def _casar(pergunta: str, pronta_id: str | None) -> dict | None:
    if pronta_id:
        return next((p for p in PRONTAS if p["id"] == pronta_id), None)
    q = _sem_acento(pergunta)
    melhor = max(PRONTAS, key=lambda p: sum(k in q for k in p["chaves"]))
    return melhor if any(k in q for k in melhor["chaves"]) else None


def _sem_ia(db: Session, pergunta: str, pronta_id: str | None, motivo: str) -> dict:
    p = _casar(pergunta, pronta_id)
    if p is None:
        return {"modo": "sem_ia", "motivo": motivo, "ferramentas": [], "previsoes": [],
                "resposta": "Sem a IA, respondo às perguntas prontas abaixo. Escolha uma delas ou reformule com palavras como "
                            "risco, manutenção, reforço, anomalia, alertas, chuva ou acerto."}
    texto, usadas = p["f"](db, pergunta)
    return {"modo": "sem_ia", "motivo": motivo, "pronta": p["id"], "resposta": texto,
            "ferramentas": [{"nome": n, "entrada": {}} for n in usadas],
            "previsoes": sorted({int(i) for i in re.findall(r"\[prev_(\d+)\]", texto)})}


def perguntar(db: Session, pergunta: str, historico: list[dict] | None = None, pronta_id: str | None = None) -> dict:
    if pronta_id or not ia.disponivel():
        motivo = "pergunta pronta" if pronta_id else "IA indisponível (sem ANTHROPIC_API_KEY)"
        return {**_sem_ia(db, pergunta, pronta_id, motivo), "dados_sinteticos": True}
    try:
        r = _com_ia(db, pergunta, historico or [])
        return {"modo": "ia", **r, "dados_sinteticos": True}
    except (anthropic.APIConnectionError, anthropic.APIStatusError, anthropic.APITimeoutError) as exc:
        log.warning("copiloto sem IA: %s", exc)
        return {**_sem_ia(db, pergunta, None, "a IA não respondeu agora"), "dados_sinteticos": True}
