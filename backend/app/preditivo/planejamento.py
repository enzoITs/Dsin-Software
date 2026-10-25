"""Planejamento de equipes (P4) a partir das previsões gravadas de P2 e P3 e da escala.

Para cada período das próximas 72 h (madrugada, manhã, tarde, noite), monta a demanda por região,
as equipes escaladas no período e roda a otimização (`p4.otimizar`). Grava uma previsão P4 por
região e período e uma recomendação por reforço ("+2 equipes no Centro, vindas da região Sul").
"""

import math
from collections import defaultdict

import pandas as pd
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.domain import limites
from app.models import Previsao, Recomendacao
from app.preditivo import p4
from app.preditivo import variaveis as V

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
ORGAO = {"CET": "trânsito (CET)", "GCM": "guarda municipal (GCM)", "PM": "polícia militar (PM)"}
COMO_AJUDA = ("Leva as equipes para onde a demanda prevista vai estar, antes do pico, sem aumentar o efetivo: "
              "só redistribui quem já está escalado")


def ultima_origem(db: Session) -> str | None:
    return db.scalar(text("SELECT detalhe->>'origem' FROM previsao WHERE modulo = 'P3' ORDER BY gerado_em DESC, id DESC LIMIT 1"))


def _rotulo(ini: pd.Timestamp, fim: pd.Timestamp) -> str:
    a, b = ini.tz_convert(V.FUSO), fim.tz_convert(V.FUSO)
    fim_h = "24" if b.hour == 0 else f"{b.hour}"
    return f"{DIAS[a.day_of_week].capitalize()} ({a:%d/%m}), {a.hour} h às {fim_h} h"


def entradas(db: Session, origem: str) -> list[dict]:
    """Períodos com as regiões (demanda, risco) e as equipes escaladas, a partir das previsões da origem."""
    p3p = pd.DataFrame(db.execute(text("""
        SELECT id, regiao_id, detalhe->'alvo'->>'nome' regiao, horizonte_inicio ini, horizonte_fim fim, valor indice, nivel,
               detalhe->>'motivo_principal' motivo, detalhe->>'nivel_nome' nivel_nome, detalhe->>'periodo' periodo
        FROM previsao WHERE modulo = 'P3' AND detalhe->>'origem' = :o AND detalhe->>'granularidade' = 'periodo'
        ORDER BY ini"""), {"o": origem}).mappings().all())
    if p3p.empty:
        return []
    p2h = pd.DataFrame(db.execute(text("""
        SELECT regiao_id, horizonte_inicio em, valor, faixa_inferior lo, faixa_superior hi, (detalhe->>'normal')::float normal
        FROM previsao WHERE modulo = 'P2' AND detalhe->>'origem' = :o"""), {"o": origem}).mappings().all())
    ini_total, fim_total = p3p.ini.min(), p3p.fim.max()
    esc = pd.DataFrame(db.execute(text("""
        SELECT s.id, s.equipe, s.regiao_id, r.nome regiao, o.sigla orgao, s.inicio_em, s.fim_em, s.agentes
        FROM escala_agente s JOIN regiao r ON r.id = s.regiao_id JOIN orgao o ON o.id = s.orgao_id
        WHERE s.fim_em > :a AND s.inicio_em < :b"""), {"a": ini_total, "b": fim_total}).mappings().all())
    cfg = limites.carregar(db)
    fator = cfg["prev_agentes_por_ocorrencia"]
    periodos = []
    for (ini, fim), regs in p3p.groupby(["ini", "fim"]):
        horas = p2h[(p2h.em >= ini) & (p2h.em < fim)]
        regioes, info = [], {}
        for r in regs.itertuples():
            h = horas[horas.regiao_id == r.regiao_id]
            prev, lo, hi, normal = float(h.valor.sum()), float(h.lo.sum()), float(h.hi.sum()), float(h.normal.sum())
            regioes.append(p4.Regiao(r.regiao, prev * fator, peso=1 + float(r.indice) / 50, muito_alto=r.nivel == "MUITO_ALTO"))
            info[r.regiao] = {"previsao_p3_id": int(r.id), "regiao_id": int(r.regiao_id), "indice": float(r.indice),
                              "nivel": r.nivel, "nivel_nome": r.nivel_nome, "motivo": r.motivo, "previstas": prev,
                              "demanda_lo": lo * fator, "demanda_hi": hi * fator, "razao_normal": prev / normal if normal else None}
        equipes = []
        if not esc.empty:
            for s in esc[(esc.fim_em > ini) & (esc.inicio_em < fim)].itertuples():
                horas_sob = (min(s.fim_em, fim) - max(s.inicio_em, ini)).total_seconds() / 3600
                if horas_sob > 0:
                    equipes.append(p4.Equipe(str(s.id), s.equipe, s.orgao, s.regiao, s.agentes * horas_sob, int(s.agentes)))
        periodos.append({"inicio": ini, "fim": fim, "periodo": regs.periodo.iloc[0], "regioes": regioes, "equipes": equipes,
                         "info": info})
    return periodos


def texto_reforco(per: dict, destino: str, movs: list[dict], info: dict) -> str:
    origens = defaultdict(list)
    for m in movs:
        origens[m["de"]].append(m)
    n = len(movs)
    orgaos = sorted({ORGAO.get(m["orgao"], m["orgao"]) for m in movs})
    vindas = "; ".join(
        f"{len(ms)} da região {de} (risco previsto {info[de]['nivel_nome'].lower()} nesse horário)" if len(origens) > 1
        else f"{'vinda' if n == 1 else 'vindas'} da região {de} (risco previsto {info[de]['nivel_nome'].lower()} nesse horário)"
        for de, ms in origens.items())
    d = info[destino]
    motivo = d["motivo"]
    razao = d.get("razao_normal")
    extra = f"; ocorrências esperadas {razao:.1f}× o normal do horário".replace(".", ",") if razao and razao >= 1.1 else ""
    return (f"{_rotulo(per['inicio'], per['fim'])}: reforçar a região {destino} com +{n} "
            f"{'equipe' if n == 1 else 'equipes'} de {' e '.join(orgaos)}, {vindas}. Motivo: {motivo}{extra}.")


def planejar(db: Session, origem: str | None = None, max_deslocamentos: int | None = None, min_por_regiao: int | None = None,
             fixas: set[str] | None = None) -> list[dict]:
    cfg = limites.carregar(db, forcar=True)
    origem = origem or ultima_origem(db)
    if not origem:
        return []
    saida = []
    for per in entradas(db, origem):
        r = p4.otimizar(per["equipes"], per["regioes"], max_deslocamentos or cfg["prev_p4_max_deslocamentos"],
                        cfg["prev_p4_min_equipes"] if min_por_regiao is None else min_por_regiao, fixas,
                        tempo_max_s=cfg["prev_p4_tempo_max_s"])
        saida.append({**per, "resultado": r})
    return saida


def resumo_json(planos: list[dict]) -> dict:
    """Formato da API: períodos, regiões, movimentos, recomendações e o risco não coberto antes e depois."""
    periodos, antes, depois = [], 0.0, 0.0
    for p in planos:
        r: p4.Resultado = p["resultado"]
        antes += r.nao_coberto_antes
        depois += r.nao_coberto_depois
        movs = r.por_regiao.get("_movimentos", [])
        por_destino = defaultdict(list)
        for m in movs:
            por_destino[m["para"]].append(m)
        periodos.append({
            "inicio": p["inicio"].isoformat(), "fim": p["fim"].isoformat(), "periodo": p["periodo"],
            "rotulo": _rotulo(p["inicio"], p["fim"]), "metodo": r.metodo, "status": r.status, "avisos": r.avisos,
            "nao_coberto_antes": round(r.nao_coberto_antes, 1), "nao_coberto_depois": round(r.nao_coberto_depois, 1),
            "reducao_pct": None if r.reducao_pct is None else round(r.reducao_pct, 1),
            "regioes": [{"regiao": reg.nome, **r.por_regiao[reg.nome], **{k: v for k, v in p["info"][reg.nome].items()
                                                                           if k not in ("demanda_lo", "demanda_hi")}}
                        for reg in p["regioes"]],
            "movimentos": movs,
            "recomendacoes": [texto_reforco(p, d, ms, p["info"]) for d, ms in por_destino.items()],
        })
    return {"periodos": periodos, "nao_coberto_antes": round(antes, 1), "nao_coberto_depois": round(depois, 1),
            "reducao_pct": round((antes - depois) / antes * 100, 1) if antes > 0 else None,
            "unidade": "agentes-hora ponderados pelo risco"}


def gravar(db: Session, planos: list[dict], origem: str) -> dict:
    """Uma previsão P4 por região e período, e uma recomendação pendente por reforço."""
    db.execute(text("DELETE FROM previsao WHERE modulo = 'P4' AND detalhe->>'origem' = :o"), {"o": origem})
    db.execute(text("""UPDATE recomendacao SET estado = 'expirada' WHERE estado = 'pendente' AND tipo = 'REFORCAR_EQUIPES'"""))
    mv_id = db.scalar(text("SELECT id FROM modelo_versao WHERE nome = 'ocorrencias_regiao_hora' AND ativo"))
    q = db.scalar(text("""SELECT detalhe->'qualidade_do_modelo' FROM previsao WHERE modulo = 'P2' AND detalhe->>'origem' = :o
                          LIMIT 1"""), {"o": origem})
    n_prev = n_rec = 0
    for p in planos:
        r: p4.Resultado = p["resultado"]
        caps = [e.capacidade for e in p["equipes"]] or [1.0]
        cap_media = sum(caps) / len(caps)
        movs = r.por_regiao.get("_movimentos", [])
        rotulo = _rotulo(p["inicio"], p["fim"])
        ids = {}
        for reg in p["regioes"]:
            info, pr = p["info"][reg.nome], r.por_regiao[reg.nome]
            entram = [m for m in movs if m["para"] == reg.nome]
            saem = [m for m in movs if m["de"] == reg.nome]
            if entram:
                acao = {"texto": texto_reforco(p, reg.nome, entram, p["info"]), "tipo": "REFORCAR_EQUIPES",
                        "parametros": {"regiao_id": info["regiao_id"], "inicio": p["inicio"].isoformat(), "fim": p["fim"].isoformat()}}
            elif saem:
                acao = {"texto": f"{rotulo}: ceder {len(saem)} {'equipe' if len(saem) == 1 else 'equipes'} para "
                                 f"{', '.join(sorted({m['para'] for m in saem}))}", "tipo": "CEDER_EQUIPES", "parametros": {}}
            else:
                acao = {"texto": "Manter a escala prevista", "tipo": "NENHUMA", "parametros": {}}
            fatores = [
                {"descricao": f"Demanda prevista de {reg.demanda:.0f} agentes-hora ({info['previstas']:.1f} ocorrências)".replace(".", ","),
                 "efeito": round(reg.demanda, 1), "grupo": "demanda"},
                {"descricao": f"Escala atual: {pr['equipes_antes']} equipes, {pr['capacidade_antes']:.0f} agentes-hora", "efeito":
                    round(-pr["capacidade_antes"], 1), "grupo": "escala"},
                {"descricao": f"Risco previsto {info['nivel_nome'].lower()} ({info['indice']:.0f}): {info['motivo']}",
                 "efeito": round(info["indice"], 1), "grupo": "risco"},
            ]
            linha = {
                "modulo": "P4", "alvo_tipo": "regiao", "alvo_id": info["regiao_id"], "regiao_id": info["regiao_id"],
                "horizonte_inicio": p["inicio"].to_pydatetime(), "horizonte_fim": p["fim"].to_pydatetime(),
                "valor": float(pr["equipes_depois"]),
                "faixa_inferior": float(math.ceil(info["demanda_lo"] / cap_media)),
                "faixa_superior": float(math.ceil(info["demanda_hi"] / cap_media)), "nivel": info["nivel"],
                "fatores": fatores, "modelo_versao_id": mv_id,
                "dados_considerados": ["Ocorrências previstas por hora (P2)", "Índice de risco das regiões (P3)",
                                       "Escala de agentes do período", "Órgão de cada equipe e limites de deslocamento"],
                "detalhe": {"origem": origem, "alvo": {"tipo": "regiao", "id": info["regiao_id"], "nome": reg.nome, "regiao": reg.nome},
                            "periodo": p["periodo"], "rotulo": rotulo,
                            "o_que_preve": f"Equipes necessárias na região {reg.nome}, {rotulo}",
                            **pr, "entram": entram, "saem": saem, "como_ajuda": COMO_AJUDA, "acao_recomendada": acao,
                            "qualidade_do_modelo": q, "metodo": r.metodo, "status": r.status,
                            "nao_coberto_periodo_antes": round(r.nao_coberto_antes, 1),
                            "nao_coberto_periodo_depois": round(r.nao_coberto_depois, 1),
                            "modelo": {"nome": "recomendacao_equipes", "versao": "otimização HiGHS"}},
            }
            ids[reg.nome] = db.execute(insert(Previsao).values(**linha).returning(Previsao.id)).scalar_one()
            n_prev += 1
        por_destino = defaultdict(list)
        for m in movs:
            por_destino[m["para"]].append(m)
        for destino, ms in por_destino.items():
            db.execute(insert(Recomendacao).values(
                previsao_id=ids[destino], tipo="REFORCAR_EQUIPES", texto=texto_reforco(p, destino, ms, p["info"]),
                parametros={"inicio": p["inicio"].isoformat(), "fim": p["fim"].isoformat(), "destino": destino,
                            "destino_regiao_id": p["info"][destino]["regiao_id"],
                            "equipes": [{"escala_id": int(m["id"]), "equipe": m["equipe"], "orgao": m["orgao"], "de": m["de"],
                                         "agentes": m["agentes"]} for m in ms]},
                impacto_estimado={"nao_coberto_antes": round(r.nao_coberto_antes, 1),
                                  "nao_coberto_depois": round(r.nao_coberto_depois, 1),
                                  "reducao_pct": None if r.reducao_pct is None else round(r.reducao_pct, 1),
                                  "falta_destino_antes": r.por_regiao[destino]["falta_antes"],
                                  "falta_destino_depois": r.por_regiao[destino]["falta_depois"]}))
            n_rec += 1
    db.commit()
    return {"previsoes": n_prev, "recomendacoes": n_rec}


def prever_p4(db: Session) -> dict:
    origem = ultima_origem(db)
    if not origem:
        return {"previsoes": 0, "recomendacoes": 0}
    planos = planejar(db, origem)
    res = gravar(db, planos, origem)
    res.update({k: v for k, v in resumo_json(planos).items() if k != "periodos"})
    return res
