"""Cenários "e se" (C1): o gestor muda o futuro e vê o efeito antes de decidir.

Mudanças possíveis, combináveis:
- evento novo (local, público, horário) ou evento cancelado;
- clima (chuva, temperatura, tempestade) num intervalo das próximas 72 h;
- equipes a mais ou a menos numa região;
- equipamentos fora de operação (por código ou "N câmeras da região X");
- manutenções preventivas feitas agora (os de maior risco da região, ou por código).

Nada é gravado: as fontes são copiadas e alteradas em memória, e P2, P3 e P4 rodam duas vezes
(sem e com a mudança) a partir da mesma hora, com os mesmos modelos. A comparação é sempre entre
as duas rodadas, para que o efeito seja só da mudança.
"""

import dataclasses
import time
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain import limites
from app.preditivo import artefatos, planejamento, prever
from app.preditivo import variaveis as V

_cache: dict = {"chave": None, "em": 0.0, "fontes": None}
CACHE_S = 600
NIVEIS = ["BAIXO", "MODERADO", "ALTO", "MUITO_ALTO"]
NOME_NIVEL = {"BAIXO": "baixo", "MODERADO": "moderado", "ALTO": "alto", "MUITO_ALTO": "muito alto"}


class CenarioInvalido(ValueError):
    pass


def fontes(db: Session) -> V.Fontes:
    """Fontes em cache por 10 min (ou até o modo contínuo avançar): carregar tudo leva alguns segundos."""
    chave = (str(db.get_bind().url), db.scalar(text("SELECT valor->>'ate' FROM estado_preditivo WHERE chave = 'continuo'")))
    agora = time.monotonic()
    if _cache["fontes"] is None or _cache["chave"] != chave or agora - _cache["em"] > CACHE_S:
        _cache.update(chave=chave, em=agora, fontes=V.carregar(db))
    return _cache["fontes"]


def _ts(v, padrao: pd.Timestamp) -> pd.Timestamp:
    """Data e hora do cenário; sem fuso, vale o horário local."""
    if v in (None, ""):
        return padrao
    t = pd.Timestamp(v)
    return (t if t.tzinfo else t.tz_localize(V.FUSO)).tz_convert("UTC")


def _fmt(v: float, casas: int = 0) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- aplicar as mudanças nas fontes

def aplicar(db: Session, f: V.Fontes, esc: pd.DataFrame, params: dict, origem: pd.Timestamp,
            fim: pd.Timestamp) -> tuple[V.Fontes, pd.DataFrame, set[int], dict]:
    """Copia as fontes e aplica as mudanças. Devolve fontes, escala, conjunto de risco de P1 e o que foi feito."""
    feito: dict = {}
    eventos, clima, escala, hist = f.eventos, f.clima, f.escala, f.historico

    cancelar = [int(i) for i in params.get("cancelar_eventos") or []]
    if cancelar:
        nomes = eventos[eventos.id.isin(cancelar)].nome.tolist()
        eventos = eventos[~eventos.id.isin(cancelar)]
        feito["eventos_cancelados"] = nomes

    novos = params.get("eventos") or []
    if novos:
        linhas = []
        for i, ev in enumerate(novos):
            lat, lon = ev.get("lat"), ev.get("lon")
            if (lat is None or lon is None) and ev.get("bairro_id"):
                b = f.bairros[f.bairros.id == int(ev["bairro_id"])]
                if b.empty:
                    raise CenarioInvalido("Bairro do evento não encontrado.")
                c = b.geom.iloc[0].representative_point()
                lon, lat = c.x, c.y
            if lat is None or lon is None:
                raise CenarioInvalido("Informe o local do evento (bairro ou coordenadas).")
            ini = _ts(ev.get("inicio"), origem + pd.Timedelta(hours=24))
            fim_ev = _ts(ev.get("fim"), ini + pd.Timedelta(hours=3))
            if fim_ev <= ini:
                raise CenarioInvalido("O evento precisa terminar depois de começar.")
            linhas.append({"id": -(i + 1), "nome": ev.get("nome") or "Evento do cenário", "inicio_em": ini, "fim_em": fim_ev,
                           "publico": int(ev.get("publico") or 0), "raio": int(ev.get("raio_m") or 2000), "lon": lon, "lat": lat})
        eventos = pd.concat([eventos, pd.DataFrame(linhas)], ignore_index=True)
        feito["eventos_novos"] = [x["nome"] for x in linhas]

    for c in params.get("clima") or []:
        a, b = _ts(c.get("inicio"), origem), _ts(c.get("fim"), fim)
        sel = (clima.em >= a) & (clima.em < b)
        if not sel.any():
            raise CenarioInvalido("O intervalo do clima está fora das próximas 72 horas.")
        clima = clima.copy()
        for campo, coluna in (("chuva_mm", "chuva_mm"), ("temperatura_c", "temperatura_c"), ("tempestade", "alerta_tempestade")):
            if c.get(campo) is not None:
                clima.loc[sel, coluna] = c[campo]
        feito.setdefault("clima", []).append({"inicio": a.isoformat(), "fim": b.isoformat(), "horas": int(sel.sum())})

    if params.get("equipes"):
        esc, removidos, extras = _mudar_equipes(f, esc, params["equipes"], origem, fim)
        escala = escala[~escala.id.isin(removidos)]
        if extras:
            escala = pd.concat([escala, pd.DataFrame(extras)[["id", "regiao_id", "inicio_em", "fim_em", "agentes"]]], ignore_index=True)
        feito["equipes"] = {"turnos_retirados": len(removidos), "turnos_extras": len(extras),
                            "nota": "As ocorrências previstas não mudam com o número de agentes (mais agentes registram mais, "
                                    "não fazem acontecer mais); muda a cobertura e o índice de risco."}

    risco = prever.risco_alto_p1(db)
    fora = _equipamentos(db, params.get("equipamentos_fora"), so_operacionais=True)
    if fora:
        novas = pd.DataFrame({"equipamento_id": [i for i, _ in fora], "em": origem - pd.Timedelta(minutes=1),
                              "anterior": "operacional", "nova": "mau_funcionamento"})
        hist = pd.concat([hist, novas], ignore_index=True).sort_values("em", kind="stable")
        risco -= {i for i, _ in fora}
        feito["equipamentos_fora"] = [c for _, c in fora]

    # A escala alterada vai à parte (`escala_p3`): P2 continua com a escala real, para não confundir registro com demanda.
    novo = dataclasses.replace(f, eventos=eventos, clima=clima, historico=hist)
    feito["_escala_p3"] = escala if params.get("equipes") else None
    manut = _manutencoes(db, f, params.get("manutencoes"), risco)
    if manut:
        risco -= {m["id"] for m in manut}
        feito["manutencoes"] = manut
    return novo, esc, risco, feito


def _mudar_equipes(f: V.Fontes, esc: pd.DataFrame, mudancas: list[dict], origem: pd.Timestamp, fim: pd.Timestamp):
    """Equipes a menos: em cada período, retira os N maiores turnos da região. A mais: N turnos de 2 agentes por período."""
    reg_id = dict(zip(f.bairros.regiao, f.bairros.regiao_id))
    removidos, extras = set(), []
    esc = esc.copy()
    periodos = _periodos(origem, fim)
    for m in mudancas:
        regiao, delta = m.get("regiao"), int(m.get("delta") or 0)
        if regiao not in reg_id:
            raise CenarioInvalido(f"Região desconhecida: {regiao}")
        a, b = _ts(m.get("inicio"), origem), _ts(m.get("fim"), fim)
        for ini, fim_p in periodos:
            if fim_p <= a or ini >= b or delta == 0:
                continue
            if delta < 0:
                cand = esc[(esc.regiao == regiao) & (esc.fim_em > ini) & (esc.inicio_em < fim_p) & ~esc.id.isin(removidos)]
                removidos |= set(cand.sort_values(["agentes", "id"], ascending=[False, True]).id.head(-delta))
            else:
                for k in range(delta):
                    extras.append({"id": -(len(extras) + 1), "equipe": f"Reforço do cenário {len(extras) + 1}",
                                   "regiao_id": int(reg_id[regiao]), "regiao": regiao, "orgao": m.get("orgao") or "CET",
                                   "inicio_em": ini, "fim_em": fim_p, "agentes": int(m.get("agentes") or 2)})
    esc = esc[~esc.id.isin(removidos)]
    if extras:
        esc = pd.concat([esc, pd.DataFrame(extras)], ignore_index=True)
    return esc, removidos, extras


def _periodos(origem: pd.Timestamp, fim: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Os blocos de 6 h locais (madrugada, manhã, tarde, noite) que cobrem as próximas 72 h."""
    saida, t = [], origem.tz_convert(V.FUSO)
    while t.tz_convert("UTC") < fim:
        prox = (t.floor("D") + pd.Timedelta(hours=(t.hour // 6 + 1) * 6))
        saida.append((t.tz_convert("UTC"), min(prox.tz_convert("UTC"), fim)))
        t = prox
    return saida


def _equipamentos(db: Session, sel: dict | None, so_operacionais: bool) -> list[tuple[int, str]]:
    """[(id, código)] pelos códigos, ou os N primeiros de um tipo numa região."""
    if not sel:
        return []
    filtro = "AND e.situacao = 'operacional'" if so_operacionais else ""
    if sel.get("codigos"):
        linhas = db.execute(text(f"""SELECT e.id, e.codigo_interno FROM equipamento e
                                     WHERE e.codigo_interno = ANY(:c) {filtro} ORDER BY e.id"""), {"c": list(sel["codigos"])}).all()
    else:
        linhas = db.execute(text(f"""
            SELECT e.id, e.codigo_interno FROM equipamento e JOIN tipo_equipamento t ON t.id = e.tipo_id
            JOIN localizacao l ON l.equipamento_id = e.id
            WHERE t.mobilidade::text = 'fixo' AND (CAST(:r AS text) IS NULL OR l.regiao = :r) AND (CAST(:t AS text) IS NULL OR t.prefixo = :t) {filtro}
            ORDER BY e.id LIMIT :n"""), {"r": sel.get("regiao"), "t": sel.get("prefixo"), "n": int(sel.get("quantidade") or 5)}).all()
    if not linhas:
        raise CenarioInvalido("Nenhum equipamento em operação com esses critérios.")
    return [(int(i), c) for i, c in linhas]


def _manutencoes(db: Session, f: V.Fontes, sel: dict | None, risco: set[int]) -> list[dict]:
    """Preventiva feita agora: probabilidade de falha em 7 dias antes e depois, recalculada pelo modelo de P1."""
    if not sel:
        return []
    if sel.get("codigos"):
        alvo = _equipamentos(db, sel, so_operacionais=True)
    else:
        alvo = [(int(i), c) for i, c in db.execute(text("""
            SELECT p.alvo_id, p.detalhe->'alvo'->>'nome' FROM previsao p
            WHERE p.modulo = 'P1' AND p.horizonte_fim - p.horizonte_inicio = interval '7 days'
              AND p.horizonte_inicio = (SELECT max(horizonte_inicio) FROM previsao WHERE modulo = 'P1')
              AND (CAST(:r AS text) IS NULL OR p.detalhe->'alvo'->>'regiao' = :r)
            ORDER BY p.valor DESC LIMIT :n"""), {"r": sel.get("regiao"), "n": int(sel.get("quantidade") or 10)})]
    if not alvo:
        raise CenarioInvalido("Nenhum equipamento com previsão de risco para essa manutenção.")
    ids = [i for i, _ in alvo]
    _, modelo = artefatos.ativo(db, "falha_equipamento_7d")
    corte = V.corte_local(prever.hoje_local())
    antes = depois = {}
    if modelo is not None:
        sub = dataclasses.replace(f, equipamentos=f.equipamentos[f.equipamentos.id.isin(ids)])
        x = V.equipamentos(sub, [corte], alvo=False)
        if not x.empty:
            antes = dict(zip(x.id, modelo.prever(x)))
            regs = pd.concat([f.registros, pd.DataFrame({"equipamento_id": ids, "em": corte - pd.Timedelta(minutes=1),
                                                         "preventiva": True})], ignore_index=True).sort_values("em")
            y = V.equipamentos(dataclasses.replace(sub, registros=regs), [corte], alvo=False)
            depois = dict(zip(y.id, modelo.prever(y)))
    return [{"id": i, "codigo": c, "prob_antes": _r(antes.get(i)), "prob_depois": _r(depois.get(i)), "estava_em_risco": i in risco}
            for i, c in alvo]


def _pct(novo: float, antes: float, casas: int = 1) -> str:
    return f"{(novo - antes) / antes * 100:+.{casas}f}%".replace(".", ",") if antes else "—"


def _r(v) -> float | None:
    return None if v is None else round(float(v), 4)


# ---------------------------------------------------------------- rodar e comparar

def _rodar(db: Session, f: V.Fontes, esc: pd.DataFrame, origem: pd.Timestamp, cfg: dict, mv, modelo, risco: set[int],
           escala_p3: pd.DataFrame | None = None) -> dict:
    p2l, p3l = prever.calcular_p2_p3(db, f, origem, cfg, mv, modelo, risco, escala_p3)
    p2 = pd.DataFrame([{"regiao_id": x["regiao_id"], "regiao": x["detalhe"]["alvo"]["nome"], "em": x["horizonte_inicio"],
                        "valor": x["valor"], "lo": x["faixa_inferior"], "hi": x["faixa_superior"],
                        "normal": x["detalhe"]["normal"]} for x in p2l])
    per = [x for x in p3l if x["detalhe"]["granularidade"] == "periodo"]
    p3p = pd.DataFrame([{"id": k, "regiao_id": x["regiao_id"], "regiao": x["detalhe"]["alvo"]["nome"],
                         "ini": pd.Timestamp(x["horizonte_inicio"]), "fim": pd.Timestamp(x["horizonte_fim"]), "indice": x["valor"],
                         "nivel": x["nivel"], "motivo": x["detalhe"]["motivo_principal"], "nivel_nome": x["detalhe"]["nivel_nome"],
                         "periodo": x["detalhe"]["periodo"]} for k, x in enumerate(per)])
    p2["em"] = pd.to_datetime(p2.em, utc=True)
    planos = planejamento.planejar(db, periodos=planejamento.montar_periodos(p3p, p2, esc, cfg["prev_agentes_por_ocorrencia"]))
    return {"p2": p2, "p3p": p3p, "planos": planos}


def _resumo_regioes(base: dict, cen: dict) -> list[dict]:
    saida = []
    for reg, b in base["p2"].groupby("regiao"):
        c = cen["p2"][cen["p2"].regiao == reg]
        pb, pc = base["p3p"][base["p3p"].regiao == reg], cen["p3p"][cen["p3p"].regiao == reg]
        ob, oc = float(b.valor.sum()), float(c.valor.sum())
        saida.append({
            "regiao": reg, "ocorrencias_base": round(ob, 1), "ocorrencias_cenario": round(oc, 1),
            "diferenca_pct": round((oc - ob) / ob * 100, 1) if ob else None,
            "indice_medio_base": round(float(pb.indice.mean()), 1), "indice_medio_cenario": round(float(pc.indice.mean()), 1),
            "indice_max_base": round(float(pb.indice.max()), 1), "indice_max_cenario": round(float(pc.indice.max()), 1),
            "nivel_max_base": pb.loc[pb.indice.idxmax(), "nivel"], "nivel_max_cenario": pc.loc[pc.indice.idxmax(), "nivel"],
            "periodos_alto_base": int(pb.nivel.isin(["ALTO", "MUITO_ALTO"]).sum()),
            "periodos_alto_cenario": int(pc.nivel.isin(["ALTO", "MUITO_ALTO"]).sum()),
        })
    return sorted(saida, key=lambda r: -abs(r["indice_medio_cenario"] - r["indice_medio_base"]))


def _resumo_periodos(base: dict, cen: dict) -> list[dict]:
    saida = []
    for (ini, fim), b in base["p3p"].groupby(["ini", "fim"]):
        c = cen["p3p"][(cen["p3p"].ini == ini) & (cen["p3p"].fim == fim)].set_index("regiao")
        saida.append({"inicio": ini.isoformat(), "fim": fim.isoformat(), "rotulo": planejamento._rotulo(ini, fim),
                      "regioes": [{"regiao": x.regiao, "indice_base": round(float(x.indice), 1), "nivel_base": x.nivel,
                                   "indice_cenario": round(float(c.loc[x.regiao, "indice"]), 1) if x.regiao in c.index else None,
                                   "nivel_cenario": c.loc[x.regiao, "nivel"] if x.regiao in c.index else None}
                                  for x in b.sort_values("regiao").itertuples()]})
    return saida


def _equipes(planos: list[dict]) -> dict:
    j = planejamento.resumo_json(planos)
    return {"nao_coberto_escala": j["nao_coberto_antes"], "nao_coberto_otimizado": j["nao_coberto_depois"],
            "recomendacoes": [t for p in j["periodos"] for t in p["recomendacoes"]]}


def simular(db: Session, params: dict, agora: datetime | None = None) -> dict:
    t0 = time.time()
    cfg = limites.carregar(db, forcar=True)
    mv, modelo = artefatos.ativo(db, "ocorrencias_regiao_hora")
    if modelo is None:
        raise CenarioInvalido("Ainda não há modelo de ocorrências treinado.")
    origem = pd.Timestamp(agora or datetime.now(timezone.utc)).tz_convert("UTC").floor("h")
    fim = origem + pd.Timedelta(hours=V.HORIZONTE_H)
    f = fontes(db)
    esc = planejamento.escala(db, origem - pd.Timedelta(hours=1), fim + pd.Timedelta(hours=1))
    if not esc.empty:
        esc["inicio_em"] = pd.to_datetime(esc.inicio_em, utc=True)
        esc["fim_em"] = pd.to_datetime(esc.fim_em, utc=True)
    f2, esc2, risco2, feito = aplicar(db, f, esc, params, origem, fim)
    base = _rodar(db, f, esc, origem, cfg, mv, modelo, prever.risco_alto_p1(db))
    cen = _rodar(db, f2, esc2, origem, cfg, mv, modelo, risco2, feito.pop("_escala_p3"))
    regioes = _resumo_regioes(base, cen)
    eq_b, eq_c = _equipes(base["planos"]), _equipes(cen["planos"])
    return {
        "origem": origem.isoformat(), "parametros": params, "aplicado": feito, "regioes": regioes,
        "periodos": _resumo_periodos(base, cen),
        "equipes": {"base": eq_b, "cenario": eq_c},
        "frases": frases(regioes, eq_b, eq_c, feito),
        "segundos": round(time.time() - t0, 1), "dados_sinteticos": True,
    }


def frases(regioes: list[dict], eq_b: dict, eq_c: dict, feito: dict) -> list[str]:
    """O que muda, em linguagem do gestor."""
    ob = sum(r["ocorrencias_base"] for r in regioes)
    oc = sum(r["ocorrencias_cenario"] for r in regioes)
    out = []
    if ob:
        out.append(f"Ocorrências previstas nas próximas 72 h: {_fmt(ob)} → {_fmt(oc)} ({_pct(oc, ob)})")
    mudou = [r for r in regioes if abs(r["indice_medio_cenario"] - r["indice_medio_base"]) >= 0.5
             or (r["diferenca_pct"] is not None and abs(r["diferenca_pct"]) >= 2)]
    if mudou:
        r = mudou[0]
        out.append(f"Maior mudança na região {r['regiao']}: {_pct(r['ocorrencias_cenario'], r['ocorrencias_base'])} de "
                   f"ocorrências; índice de risco médio {r['indice_medio_base']:.0f} → {r['indice_medio_cenario']:.0f}, máximo "
                   f"{NOME_NIVEL[r['nivel_max_base']]} ({r['indice_max_base']:.0f}) → "
                   f"{NOME_NIVEL[r['nivel_max_cenario']]} ({r['indice_max_cenario']:.0f})")
    pa, pc = sum(r["periodos_alto_base"] for r in regioes), sum(r["periodos_alto_cenario"] for r in regioes)
    if pa != pc:
        out.append(f"Períodos com risco alto ou muito alto (regiões × períodos): {pa} → {pc}")
    nb, nc = eq_b["nao_coberto_escala"], eq_c["nao_coberto_escala"]
    if nb or nc:
        var = f" ({_pct(nc, nb, 0)})" if nb else ""
        out.append(f"Risco não coberto com a escala como está: {_fmt(nb)} → {_fmt(nc)}{var}; "
                   f"seguindo a recomendação de equipes: {_fmt(eq_c['nao_coberto_otimizado'])}")
    for m in feito.get("manutencoes", [])[:3]:
        if m["prob_antes"] is not None and m["prob_depois"] is not None:
            out.append(f"Preventiva em {m['codigo']}: chance de falhar em 7 dias {m['prob_antes'] * 100:.0f}% → "
                       f"{m['prob_depois'] * 100:.0f}%")
    if not out:
        out.append("A mudança não altera as previsões de forma perceptível.")
    return out
