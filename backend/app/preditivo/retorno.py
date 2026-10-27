"""Retorno das recomendações (C5): o que foi decidido, por quem, por quê, e o que aconteceu depois.

`conferir` roda de hora em hora e, quando o período da recomendação termina, grava em
`recomendacao.resultado["retorno"]`:
- reforço de equipes: ocorrências registradas na região no período × previstas;
- OS preventiva: se o equipamento falhou na janela da previsão e se a OS foi concluída.

`resumo` junta tudo para a tela de decisões: taxa de aceitação, motivos de rejeição e a comparação
entre aceitas e rejeitadas (por exemplo, quantos equipamentos falharam com e sem a preventiva).
A comparação é observacional (o gestor não decide ao acaso), e a tela diz isso.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Previsao, Recomendacao
from app.models.enums import EstadoRecomendacao as ER

DECIDIDAS = (ER.aceita, ER.ajustada, ER.rejeitada)
TIPOS_OS = ("ABRIR_ORDEM_SERVICO", "INCLUIR_ROTA_MANUTENCAO")
ROTULO_TIPO = {"ABRIR_ORDEM_SERVICO": "OS preventiva", "INCLUIR_ROTA_MANUTENCAO": "Rota de manutenção",
               "REFORCAR_EQUIPES": "Reforço de equipes", "PRIORIZAR_MANUTENCAO": "Priorizar manutenção da região",
               "INCLUIR_RONDA_NOTURNA": "Ronda de madrugada", "PLANEJAR_MANUTENCAO": "Planejar equipe de manutenção"}


def _fmt(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def _retorno_reforco(db: Session, rec: Recomendacao, p: Previsao | None) -> dict | None:
    par = rec.parametros or {}
    if not par.get("inicio") or not par.get("fim"):
        return None
    ini, fim = datetime.fromisoformat(par["inicio"]), datetime.fromisoformat(par["fim"])
    rid = par.get("destino_regiao_id") or (p.regiao_id if p else None)
    if rid is None:
        return None
    origem = (p.detalhe or {}).get("origem") if p else None
    previsto = db.scalar(text("""SELECT sum(valor) FROM previsao WHERE modulo = 'P2' AND regiao_id = :r
                                 AND horizonte_inicio >= :a AND horizonte_inicio < :b AND detalhe->>'origem' = :o"""),
                         {"r": rid, "a": ini, "b": fim, "o": origem}) if origem else None
    real = db.scalar(text("""SELECT count(*) FROM ocorrencia WHERE regiao_id = :r AND inicio_em >= :a AND inicio_em < :b"""),
                     {"r": rid, "a": ini, "b": fim})
    nome = db.scalar(text("SELECT nome FROM regiao WHERE id = :r"), {"r": rid})
    texto = f"Aconteceram {real} ocorrências na região {nome} no período" + (
        f" (previstas {_fmt(float(previsto))})" if previsto is not None else "")
    return {"tipo": "reforco", "real": int(real), "previsto": None if previsto is None else round(float(previsto), 1),
            "razao": round(real / float(previsto), 2) if previsto else None, "texto": texto}


def _retorno_os(db: Session, rec: Recomendacao, p: Previsao | None) -> dict | None:
    eid = (rec.parametros or {}).get("equipamento_id") or (p.alvo_id if p else None)
    if eid is None or p is None:
        return None
    desde = max(p.horizonte_inicio, rec.decidido_em or p.horizonte_inicio)
    falhou = bool(db.scalar(text("""SELECT count(*) FROM historico_situacao WHERE equipamento_id = :e
                                    AND situacao_nova = 'mau_funcionamento' AND em >= :a AND em < :b"""),
                            {"e": eid, "a": desde, "b": p.horizonte_fim}))
    os_id = ((rec.resultado or {}).get("execucao") or {}).get("ordem_servico_id")
    os_ = db.execute(text("SELECT status::text, fechada_em FROM ordem_servico WHERE id = :i"), {"i": os_id}).first() if os_id else None
    texto = ("O equipamento falhou dentro da janela prevista" if falhou else "O equipamento não falhou dentro da janela prevista")
    if os_:
        texto += "; a OS preventiva foi concluída" if os_[0] == "fechada" else "; a OS preventiva ainda está aberta"
    return {"tipo": "os", "falhou": falhou, "os_status": os_[0] if os_ else None, "previsto": round(float(p.valor), 3),
            "texto": texto}


def _fim_do_periodo(rec: Recomendacao, p: Previsao | None) -> datetime | None:
    if rec.tipo == "REFORCAR_EQUIPES" and (rec.parametros or {}).get("fim"):
        return datetime.fromisoformat(rec.parametros["fim"])
    return p.horizonte_fim if p else None


def conferir(db: Session, agora: datetime | None = None) -> int:
    agora = agora or datetime.now(timezone.utc)
    n = 0
    for rec in db.scalars(select(Recomendacao).where(Recomendacao.estado.in_(DECIDIDAS))):
        if (rec.resultado or {}).get("retorno"):
            continue
        p = db.get(Previsao, rec.previsao_id) if rec.previsao_id else None
        fim = _fim_do_periodo(rec, p)
        if fim is None or fim > agora:
            continue
        r = _retorno_reforco(db, rec, p) if rec.tipo == "REFORCAR_EQUIPES" else _retorno_os(db, rec, p) if rec.tipo in TIPOS_OS else None
        if r is None:
            continue
        rec.resultado = {**(rec.resultado or {}), "retorno": {**r, "conferido_em": agora.isoformat()}}
        n += 1
    db.commit()
    return n


def resumo(db: Session, dias: int = 30, agora: datetime | None = None) -> dict:
    agora = agora or datetime.now(timezone.utc)
    recs = list(db.scalars(select(Recomendacao).where(Recomendacao.criado_em >= agora - timedelta(days=dias))
                           .order_by(Recomendacao.id.desc())))
    por_estado = Counter(r.estado.value for r in recs)
    decididas = [r for r in recs if r.estado in DECIDIDAS]
    aceitas = [r for r in decididas if r.estado != ER.rejeitada]
    por_tipo = []
    for tipo in sorted({r.tipo for r in recs} - {"NENHUMA"}):
        rs = [r for r in recs if r.tipo == tipo]
        dec = [r for r in rs if r.estado in DECIDIDAS]
        por_tipo.append({"tipo": tipo, "rotulo": ROTULO_TIPO.get(tipo, tipo), "total": len(rs), "decididas": len(dec),
                         "aceitas": sum(r.estado != ER.rejeitada for r in dec),
                         "rejeitadas": sum(r.estado == ER.rejeitada for r in dec),
                         "expiradas": sum(r.estado == ER.expirada for r in rs), "pendentes": sum(r.estado == ER.pendente for r in rs)})

    def comparar(grupo: list[Recomendacao], tipo: str) -> dict:
        com = [r for r in grupo if ((r.resultado or {}).get("retorno") or {}).get("tipo") == tipo]
        if tipo == "os":
            return {"conferidas": len(com), "falharam": sum(r.resultado["retorno"]["falhou"] for r in com),
                    "taxa_falha": round(sum(r.resultado["retorno"]["falhou"] for r in com) / len(com), 3) if com else None}
        razoes = [r.resultado["retorno"]["razao"] for r in com if r.resultado["retorno"].get("razao") is not None]
        return {"conferidas": len(com), "real_sobre_previsto": round(sum(razoes) / len(razoes), 2) if razoes else None}

    rejeitadas = [r for r in decididas if r.estado == ER.rejeitada]
    return {
        "dias": dias, "total": len(recs), "por_estado": dict(por_estado), "decididas": len(decididas),
        "taxa_aceitacao": round(len(aceitas) / len(decididas), 3) if decididas else None,
        "por_tipo": por_tipo,
        "motivos_rejeicao": [{"motivo": m, "vezes": n} for m, n in Counter((r.motivo or "").strip() for r in rejeitadas).most_common(10)],
        "comparacao": {
            "os": {"aceitas": comparar(aceitas, "os"), "rejeitadas": comparar(rejeitadas, "os")},
            "reforco": {"aceitas": comparar(aceitas, "reforco"), "rejeitadas": comparar(rejeitadas, "reforco")},
            "aviso": ("Comparação observacional: as decisões não são sorteadas, então a diferença entre aceitas e rejeitadas "
                      "mostra uma tendência, não uma prova de causa."),
        },
        "decisoes": [{"id": r.id, "tipo": r.tipo, "rotulo_tipo": ROTULO_TIPO.get(r.tipo, r.tipo), "texto": r.texto,
                      "estado": r.estado.value, "decidido_por": r.decidido_por, "decidido_em": r.decidido_em, "motivo": r.motivo,
                      "previsao_id": r.previsao_id, "execucao": (r.resultado or {}).get("execucao"),
                      "retorno": (r.resultado or {}).get("retorno")} for r in decididas[:200]],
    }
