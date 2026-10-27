"""Consultas compactas sobre as previsões, para o copiloto (C3) e o briefing diário (C4).

Cada função devolve só o necessário para responder (dicionários pequenos, com o id da previsão
quando há um cartão por trás), lendo os mesmos dados que a API e as telas mostram.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import ModeloVersao
from app.preditivo import acertometro, cartoes, planejamento
from app.preditivo.variaveis import FUSO

NOME_NIVEL = {"BAIXO": "baixo", "MODERADO": "moderado", "ALTO": "alto", "MUITO_ALTO": "muito alto"}
REGIOES = ("Centro", "Norte", "Sul", "Leste", "Oeste")


def _fmt(v: float, casas: int = 1) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def regiao_citada(texto: str) -> str | None:
    t = (texto or "").lower()
    return next((r for r in REGIOES if r.lower() in t), None)


def risco(db: Session, horas: int = 24, regiao: str | None = None, limite: int = 6, dia: date | None = None) -> dict:
    """Períodos (madrugada, manhã, tarde, noite) de maior índice de risco no último lote de P3."""
    origem = planejamento.ultima_origem(db)
    if not origem:
        return {"disponivel": False, "periodos": []}
    agora = datetime.now(timezone.utc)
    filtro, par = "", {"o": origem}
    if dia is not None:
        filtro = "AND p.detalhe->>'data_local' = :d"
        par["d"] = dia.isoformat()
    else:
        filtro = "AND p.horizonte_fim > :a AND p.horizonte_inicio < :b"
        par.update(a=agora, b=agora + timedelta(hours=horas))
    if regiao:
        filtro += " AND p.detalhe->'alvo'->>'nome' = :r"
        par["r"] = regiao
    linhas = db.execute(text(f"""
        SELECT p.id, p.detalhe->'alvo'->>'nome' regiao, p.horizonte_inicio ini, p.horizonte_fim fim, p.valor, p.nivel,
               p.detalhe->>'motivo_principal' motivo
        FROM previsao p WHERE p.modulo = 'P3' AND p.detalhe->>'origem' = :o AND p.detalhe->>'granularidade' = 'periodo' {filtro}
        ORDER BY p.valor DESC LIMIT :n"""), {**par, "n": limite}).mappings().all()
    return {"disponivel": True, "origem": origem, "periodos": [{
        "previsao_id": x["id"], "regiao": x["regiao"], "quando": planejamento._rotulo(pd.Timestamp(x["ini"]), pd.Timestamp(x["fim"])),
        "indice": round(x["valor"]), "nivel": x["nivel"], "nivel_nome": NOME_NIVEL.get(x["nivel"], x["nivel"]), "motivo": x["motivo"],
    } for x in linhas]}


def ocorrencias_previstas(db: Session, dia: date) -> dict:
    """Total previsto (P2) para o dia local, contra o normal das 8 semanas, por região."""
    origem = planejamento.ultima_origem(db)
    if not origem:
        return {"disponivel": False}
    ini = pd.Timestamp(dia).tz_localize(FUSO).tz_convert("UTC")
    linhas = db.execute(text("""
        SELECT detalhe->'alvo'->>'nome' regiao, sum(valor) previsto, sum((detalhe->>'normal')::float) normal
        FROM previsao WHERE modulo = 'P2' AND detalhe->>'origem' = :o AND horizonte_inicio >= :a AND horizonte_inicio < :b
        GROUP BY 1 ORDER BY 2 DESC"""), {"o": origem, "a": ini, "b": ini + pd.Timedelta(days=1)}).mappings().all()
    prev, normal = sum(x["previsto"] for x in linhas), sum(x["normal"] or 0 for x in linhas)
    return {"disponivel": bool(linhas), "previsto": round(prev, 1), "normal": round(normal, 1),
            "por_regiao": [{"regiao": x["regiao"], "previsto": round(x["previsto"], 1),
                                                   "normal": round(x["normal"] or 0, 1)} for x in linhas]}


def equipamentos(db: Session, janela: int = 7, regiao: str | None = None, tipo: str | None = None, limite: int = 8) -> dict:
    """Maiores riscos de falha (P1), com nível, principal fator e se já há OS."""
    from app.routers import previsoes

    try:
        r = previsoes.ranking(db, janela=janela, nivel=[], tipo=tipo, regiao=regiao, busca=None, limite=limite)
    except HTTPException:
        return {"disponivel": False, "itens": []}
    return {"disponivel": True, "janela_dias": janela, "totais_por_nivel": r["totais_por_nivel"], "selo": r["selo"]["texto"],
            "itens": [{"previsao_id": x["previsao_id"], "codigo": x["codigo"], "tipo": x["tipo"], "regiao": x["regiao"],
                       "probabilidade": round(x["probabilidade"], 3), "nivel": x["nivel"],
                       "principal_fator": x["fatores"][0]["descricao"] if x["fatores"] else None,
                       "os_aberta": x["os_aberta"], "decisao": x["decisao"]} for x in r["itens"]]}


def reforcos(db: Session, horas: int | None = 24) -> dict:
    """Recomendações de reforço de equipes pendentes (P4), na ordem do horário."""
    agora = datetime.now(timezone.utc)
    linhas = db.execute(text("""
        SELECT id, previsao_id, texto, parametros->>'inicio' inicio, impacto_estimado FROM recomendacao
        WHERE tipo = 'REFORCAR_EQUIPES' AND estado = 'pendente' ORDER BY parametros->>'inicio'""")).mappings().all()
    itens = []
    for x in linhas:
        ini = datetime.fromisoformat(x["inicio"]) if x["inicio"] else None
        if horas is not None and ini is not None and ini > agora + timedelta(hours=horas):
            continue
        imp = x["impacto_estimado"] or {}
        itens.append({"recomendacao_id": x["id"], "previsao_id": x["previsao_id"], "texto": x["texto"],
                      "falta_antes": imp.get("falta_destino_antes"), "falta_depois": imp.get("falta_destino_depois")})
    return {"itens": itens}


def anomalias(db: Session, limite: int = 8) -> dict:
    linhas = db.execute(text("""
        SELECT id, tipo::text tipo, mensagem, criado_em FROM alerta
        WHERE tipo::text IN ('anomalia_equipamento', 'anomalia_regiao') AND resolvido_em IS NULL
        ORDER BY criado_em DESC LIMIT :n"""), {"n": limite}).mappings().all()
    return {"itens": [{"alerta_id": x["id"], "tipo": x["tipo"], "mensagem": x["mensagem"]} for x in linhas]}


def alertas_preventivos(db: Session, limite: int = 10) -> dict:
    linhas = db.execute(text("""
        SELECT id, tipo::text tipo, nivel::text nivel, mensagem, (dados->'preditivo'->>'previsao_id')::int previsao_id FROM alerta
        WHERE tipo::text LIKE 'previsao_%' AND resolvido_em IS NULL
        ORDER BY nivel DESC, criado_em DESC LIMIT :n"""), {"n": limite}).mappings().all()
    return {"itens": [dict(x) for x in linhas]}


def qualidade(db: Session) -> dict:
    """Selo de cada modelo contra a média histórica e o que já foi conferido nos últimos 7 dias."""
    saida = {}
    for nome, mod in (("falha_equipamento_7d", "P1"), ("ocorrencias_regiao_hora", "P2")):
        mv = db.scalar(text("SELECT id FROM modelo_versao WHERE nome = :n AND ativo"), {"n": nome})
        s = cartoes.selo(db.get(ModeloVersao, mv) if mv else None, mod)
        saida[mod] = {"selo": s["texto"], "confianca": s["confianca"]}
    r = acertometro.resumo(db, 7)
    g = r["P2"].get("geral")
    saida["acertometro_7d"] = None if not g else {
        "horas_conferidas": g["n"], "erro_modelo": g["mae"], "erro_media_historica": g["mae_baseline"], "ganho_pct": g["ganho_pct"],
        "dentro_da_faixa": g["cobertura_intervalo"]}
    return saida


def contexto(db: Session, dia: date) -> dict:
    """Feriado, eventos e clima previsto para o dia local."""
    ini = pd.Timestamp(dia).tz_localize(FUSO).tz_convert("UTC").to_pydatetime()
    fim = ini + timedelta(days=1)
    cal = db.execute(text("SELECT feriado, feriado_nome, vespera_feriado FROM calendario WHERE data = :d"), {"d": dia}).first()
    eventos = db.execute(text("""SELECT nome, local_nome, inicio_em, publico_estimado FROM evento_cidade
                                 WHERE fim_em > :a AND inicio_em < :b ORDER BY publico_estimado DESC LIMIT 5"""),
                         {"a": ini, "b": fim}).mappings().all()
    clima = db.execute(text("""SELECT em, temperatura_c, chuva_mm, alerta_tempestade FROM clima_hora
                               WHERE em >= :a AND em < :b ORDER BY em"""), {"a": ini, "b": fim}).mappings().all()
    horas_chuva = [c["em"].astimezone(ZoneInfo(FUSO)).hour for c in clima if c["chuva_mm"] >= 0.5]
    return {
        "feriado": cal.feriado_nome if cal and cal.feriado else None, "vespera_feriado": bool(cal and cal.vespera_feriado),
        "eventos": [{"nome": e["nome"], "local": e["local_nome"], "publico": e["publico_estimado"],
                     "hora": e["inicio_em"].astimezone(ZoneInfo(FUSO)).strftime("%H:%M")} for e in eventos],
        "chuva_mm": round(sum(c["chuva_mm"] for c in clima), 1), "horas_chuva": horas_chuva,
        "temp_max": round(max((c["temperatura_c"] for c in clima), default=0), 0),
        "tempestade": any(c["alerta_tempestade"] for c in clima),
    }
