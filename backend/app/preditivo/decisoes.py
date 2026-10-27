"""O humano decide: aceitar, ajustar ou rejeitar uma recomendação, sempre registrado (C5).

Aceitar ou ajustar executa a ação: abre a ordem de serviço preventiva (P1), move as equipes
na escala para o período recomendado (P4) ou abre as OS preventivas dos equipamentos de risco alto
de uma região (P6). As demais (ronda noturna de P7, planejamento de manutenção de P8) ficam registradas
para quem executa fora do sistema. Rejeitar exige motivo.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.estados import RegraViolada
from app.models import EscalaAgente, OrdemServico, Previsao, Recomendacao, Regiao
from app.models.enums import EstadoRecomendacao as ER
from app.models.enums import PrioridadeOS, StatusOS
from app.services.barramento import emitir

ACOES = {"aceitar": ER.aceita, "ajustar": ER.ajustada, "rejeitar": ER.rejeitada}


def recomendacao_da_previsao(db: Session, p: Previsao) -> Recomendacao:
    """A recomendação ligada à previsão; criada na hora a partir da ação do cartão, se ainda não existir."""
    rec = db.scalar(select(Recomendacao).where(Recomendacao.previsao_id == p.id).order_by(Recomendacao.id.desc()).limit(1))
    if rec is not None:
        return rec
    acao = (p.detalhe or {}).get("acao_recomendada") or {}
    rec = Recomendacao(previsao_id=p.id, tipo=acao.get("tipo", "NENHUMA"), texto=acao.get("texto", ""),
                       parametros=acao.get("parametros") or {}, impacto_estimado={"valor_previsto": p.valor},
                       estado=ER.pendente)
    db.add(rec)
    db.flush()
    return rec


def _abrir_os(db: Session, rec: Recomendacao, params: dict, usuario: str) -> dict:
    eid = params.get("equipamento_id")
    if not eid:
        raise RegraViolada("sem_equipamento", "A recomendação não indica o equipamento.")
    aberta = db.scalar(select(OrdemServico).where(OrdemServico.equipamento_id == eid, OrdemServico.status == StatusOS.aberta))
    if aberta is not None:
        return {"ordem_servico_id": aberta.id, "ja_existia": True}
    prioridade = params.get("prioridade") or ("baixa" if rec.tipo == "INCLUIR_ROTA_MANUTENCAO" else "media")
    os_ = OrdemServico(equipamento_id=eid, motivo=f"Preventiva recomendada pela previsão ({usuario}): {rec.texto}",
                       prioridade=PrioridadeOS(prioridade), status=StatusOS.aberta)
    db.add(os_)
    db.flush()
    return {"ordem_servico_id": os_.id, "ja_existia": False}


def _mover_equipes(db: Session, params: dict) -> dict:
    """Move cada turno para a região de destino durante o período; o resto do turno fica onde estava."""
    destino = params.get("destino_regiao_id")
    if destino is None or db.get(Regiao, destino) is None:
        raise RegraViolada("sem_destino", "A recomendação não indica a região de destino.")
    p0, p1 = datetime.fromisoformat(params["inicio"]), datetime.fromisoformat(params["fim"])
    movidos = []
    for eq in params.get("equipes", []):
        t = db.get(EscalaAgente, eq["escala_id"])
        if t is None:
            continue
        a, b = max(t.inicio_em, p0), min(t.fim_em, p1)
        if a >= b:
            continue
        if t.inicio_em < a:
            db.add(EscalaAgente(equipe=t.equipe, orgao_id=t.orgao_id, regiao_id=t.regiao_id, inicio_em=t.inicio_em, fim_em=a,
                                agentes=t.agentes, origem=t.origem))
        if b < t.fim_em:
            db.add(EscalaAgente(equipe=t.equipe, orgao_id=t.orgao_id, regiao_id=t.regiao_id, inicio_em=b, fim_em=t.fim_em,
                                agentes=t.agentes, origem=t.origem))
        t.inicio_em, t.fim_em, t.regiao_id, t.origem = a, b, destino, "recomendacao"
        movidos.append({"escala_id": t.id, "equipe": t.equipe, "inicio": a.isoformat(), "fim": b.isoformat()})
    db.flush()
    return {"equipes_movidas": movidos}


def decidir(db: Session, rec: Recomendacao, acao: str, usuario: str, motivo: str | None = None,
            parametros: dict | None = None) -> Recomendacao:
    if acao not in ACOES:
        raise RegraViolada("acao_invalida", "Use aceitar, ajustar ou rejeitar.")
    if rec.estado != ER.pendente:
        raise RegraViolada("ja_decidida", f"Esta recomendação já foi {rec.estado.value}.", status=409)
    if acao == "rejeitar" and not (motivo or "").strip():
        raise RegraViolada("motivo_obrigatorio", "Diga por que a recomendação foi rejeitada: o motivo ajuda a ajustar as regras.")
    if acao == "ajustar" and not parametros:
        raise RegraViolada("ajuste_vazio", "Informe o que foi ajustado.")
    params = {**(rec.parametros or {}), **(parametros or {})}
    rec.estado = ACOES[acao]
    rec.decidido_por = usuario
    rec.decidido_em = datetime.now(timezone.utc)
    rec.motivo = (motivo or "").strip() or None
    resultado = {}
    if acao in ("aceitar", "ajustar"):
        if acao == "ajustar":
            rec.parametros = params
        if rec.tipo in ("ABRIR_ORDEM_SERVICO", "INCLUIR_ROTA_MANUTENCAO"):
            resultado = _abrir_os(db, rec, params, usuario)
        elif rec.tipo == "REFORCAR_EQUIPES":
            resultado = _mover_equipes(db, params)
        elif rec.tipo == "PRIORIZAR_MANUTENCAO":
            abertas = [_abrir_os(db, rec, {"equipamento_id": i, "prioridade": "alta"}, usuario)
                       for i in params.get("equipamento_ids", [])]
            resultado = {"ordens_servico": abertas, "novas": sum(not a["ja_existia"] for a in abertas)}
    rec.resultado = {**(rec.resultado or {}), "execucao": resultado}
    db.flush()
    emitir(db, {"tipo": "recomendacao", "acao": rec.estado.value, "recomendacao": {"id": rec.id, "tipo": rec.tipo,
                                                                                    "estado": rec.estado.value}})
    return rec
