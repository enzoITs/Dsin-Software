"""Previsões em lote, gravadas na tabela `previsao` para a API só ler.

Cada linha já traz tudo o que o Cartão de Previsão mostra: o que se prevê, com que dados, os
fatores, como ajuda, a ação recomendada e a qualidade do modelo contra o baseline.
"""

from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import delete, insert, text
from sqlalchemy.orm import Session

from app.domain import limites
from app.models import Previsao
from app.preditivo import artefatos, avaliacao, p1
from app.preditivo import variaveis as V


def hoje_local(agora: datetime | None = None) -> date:
    agora = agora or datetime.now(timezone.utc)
    return pd.Timestamp(agora).tz_convert(V.FUSO).date()


def qualidade(mv, metrica: str, menor_melhor: bool, cfg: dict) -> dict:
    m, b = (mv.metricas or {}).get(metrica), (mv.metricas_baseline or {}).get(metrica)
    return {"metrica": metrica.upper() if metrica == "auc" else metrica, "modelo": m, "baseline": b,
            "ganho_pct": avaliacao.ganho(m, b, menor_melhor), "avaliado_em": f"backtest de {cfg['prev_backtest_dias']} dias"}


def prever_p1(db: Session, f: V.Fontes | None = None, agora: datetime | None = None) -> int:
    """Probabilidade de falha em 7 e 30 dias de cada equipamento em operação, a partir da meia-noite de hoje."""
    cfg = limites.carregar(db, forcar=True)
    hoje = hoje_local(agora)
    corte = V.corte_local(hoje)
    f = f or V.carregar(db)
    linhas = V.equipamentos(f, [corte], alvo=False)
    if linhas.empty:
        return 0
    codigos = dict(db.execute(text("SELECT id, codigo_interno FROM equipamento")).all())
    reg_ids = dict(zip(f.bairros.regiao, f.bairros.regiao_id))
    total = 0
    for janela in (7, 30):
        mv, modelo = artefatos.ativo(db, f"falha_equipamento_{janela}d")
        if modelo is None:
            continue
        prob = modelo.prever(linhas)
        fat = p1.fatores(modelo, linhas)
        q = qualidade(mv, "auc", False, cfg)
        fim = corte + pd.Timedelta(days=janela)
        db.execute(delete(Previsao).where(Previsao.modulo == "P1", Previsao.horizonte_inicio == corte.to_pydatetime(),
                                          Previsao.horizonte_fim == fim.to_pydatetime()))
        valores = []
        for x, p, fs in zip(linhas.itertuples(), prob, fat):
            p = float(p)
            niv = p1.nivel(p, cfg["prev_p1_limites_nivel" if janela == 7 else "prev_p1_limites_nivel_30d"])
            lo, hi = p1.faixa(p)
            cod = codigos.get(x.id, str(x.id))
            regiao = str(x.regiao) if str(x.regiao) != "?" else None
            valores.append({
                "modulo": "P1", "alvo_tipo": "equipamento", "alvo_id": int(x.id), "regiao_id": reg_ids.get(regiao),
                "horizonte_inicio": corte.to_pydatetime(), "horizonte_fim": fim.to_pydatetime(), "valor": p,
                "faixa_inferior": lo, "faixa_superior": hi, "nivel": niv, "fatores": fs,
                "dados_considerados": p1.DADOS_CONSIDERADOS, "modelo_versao_id": mv.id,
                "detalhe": {
                    "o_que_preve": f"Probabilidade de falha de {cod} nos próximos {janela} dias",
                    "alvo": {"tipo": "equipamento", "id": int(x.id), "nome": cod, "regiao": regiao, "tipo_equipamento": str(x.prefixo)},
                    "como_ajuda": p1.COMO_AJUDA.get(str(x.prefixo), "Antecipar a manutenção evita que o equipamento pare quando mais se precisa dele"),
                    "acao_recomendada": p1.acao(p, niv, str(x.prefixo), cod, int(x.id), hoje),
                    "qualidade_do_modelo": q, "modelo": {"nome": mv.nome, "versao": mv.versao}, "janela_dias": janela,
                },
            })
        for i in range(0, len(valores), 5000):
            db.execute(insert(Previsao), valores[i:i + 5000])
        total += len(valores)
    db.commit()
    return total


# ---------------------------------------------------------------- P2 e P3

COMO_AJUDA_P2 = ("Saber onde e quando as ocorrências vão se concentrar permite posicionar equipes e "
                 "preparar a central antes do pico, em vez de reagir depois")
COMO_AJUDA_P3 = ("Resume num número o que vai exigir mais atenção em cada região, para decidir onde reforçar "
                 "equipes, antecipar manutenções e avisar a central")


def _eventos_por_regiao(f: V.Fontes, horas: pd.DatetimeIndex) -> dict[tuple, tuple[int, str]]:
    """(região, hora) -> (público, nome) do maior evento que influencia algum bairro da região na hora."""
    import shapely

    saida: dict[tuple, tuple[int, str]] = {}
    for ev in f.eventos.itertuples():
        a, b = ev.inicio_em - pd.Timedelta(hours=2), ev.fim_em + pd.Timedelta(hours=2)
        ativas = [h for h in horas if h + pd.Timedelta(hours=1) > a and h < b]
        if not ativas or ev.publico <= 0:
            continue
        pt = shapely.Point(ev.lon, ev.lat)
        regioes = {r for r, g in zip(f.bairros.regiao, f.bairros.geom) if g.distance(pt) * 105_000 <= ev.raio}
        for r in regioes:
            for h in ativas:
                if ev.publico > saida.get((r, h), (0, ""))[0]:
                    saida[(r, h)] = (int(ev.publico), str(ev.nome))
    return saida


def _situacao_regioes(db: Session, f: V.Fontes, origem: pd.Timestamp) -> dict[str, dict]:
    """Equipamentos fixos por região na origem: em serviço, fora de operação, em risco alto (última P1 de 7 dias)."""
    estado = V._estado_em(f.historico, origem)
    fixos = f.equipamentos[~f.equipamentos.movel & f.equipamentos.regiao.notna()].copy()
    fixos["estado"] = fixos.id.map(estado)
    fixos = fixos[fixos.estado.isin(["operacional", "mau_funcionamento", "em_manutencao", "furtado"])]
    risco = {i for (i,) in db.execute(text("""
        SELECT p.alvo_id FROM previsao p
        WHERE p.modulo = 'P1' AND p.nivel IN ('ALTO', 'MUITO_ALTO') AND p.horizonte_fim - p.horizonte_inicio = interval '7 days'
          AND p.horizonte_inicio = (SELECT max(horizonte_inicio) FROM previsao WHERE modulo = 'P1')"""))}
    fixos["risco"] = fixos.id.isin(risco) & (fixos.estado == "operacional")
    fixos["vig"] = fixos.prefixo.astype(str).isin(["CAM", "RAD"])
    saida = {}
    for reg, x in fixos.groupby("regiao"):
        v = x[x.vig]
        saida[reg] = {"fixos": len(x), "indisponiveis": int((x.estado != "operacional").sum()), "alto_risco": int(x.risco.sum()),
                      "vigilancia": len(v), "vigilancia_operando": int((v.estado == "operacional").sum()),
                      "vigilancia_risco": int(v.risco.sum())}
    return saida


def prever_p2_p3(db: Session, f: V.Fontes | None = None, agora: datetime | None = None) -> dict:
    """Ocorrências (P2) e índice de risco (P3) por região nas próximas 72 h, a partir da hora cheia atual."""
    from app.preditivo import p2, p3

    cfg = limites.carregar(db, forcar=True)
    mv, modelo = artefatos.ativo(db, "ocorrencias_regiao_hora")
    if modelo is None:
        return {"p2": 0, "p3": 0}
    agora = agora or datetime.now(timezone.utc)
    origem = pd.Timestamp(agora).tz_convert("UTC").floor("h")
    f = f or V.carregar(db)
    linhas = V.bairro_hora(f, [origem], alvo=False, semanas=cfg["prev_p2_semanas_baseline"])
    linhas["previsto"] = modelo.prever(linhas)
    fat = p2.fatores_regiao(modelo, linhas)
    reg = linhas.groupby(["em", "regiao", "regiao_id"], observed=True).agg(
        previsto=("previsto", "sum"), normal_hora=("media_mesma_hora", "sum"), agentes=("agentes", "first"),
        chuva_mm=("chuva_mm", "first"), hora=("hora", "first")).reset_index()
    lo, hi = modelo.faixa(reg.previsto.to_numpy())
    reg["lo"], reg["hi"] = lo, hi

    # Normal geral e gravidade das últimas 8 semanas, por região
    janela = f.ocorrencias[(f.ocorrencias.em < origem) & (f.ocorrencias.em >= origem - pd.Timedelta(weeks=8))]
    nome_reg = dict(zip(f.bairros.id, f.bairros.regiao))
    janela = janela.assign(regiao=janela.bairro_id.map(nome_reg))
    normal = (janela.groupby("regiao").size() / (8 * 7 * 24)).to_dict()
    grav = janela.groupby("regiao").gravidade.mean().to_dict()
    grav_cidade = float(janela.gravidade.mean()) if len(janela) else 2.0
    props = p2.proporcoes(f, origem)
    tempestade = f.clima.set_index("em").alerta_tempestade.to_dict()
    eventos = _eventos_por_regiao(f, pd.DatetimeIndex(reg.em.unique()))
    situacao = _situacao_regioes(db, f, origem)
    vazio = {"fixos": 0, "indisponiveis": 0, "alto_risco": 0, "vigilancia": 0, "vigilancia_operando": 0, "vigilancia_risco": 0}
    pesos = cfg["prev_p3_pesos"]
    q2 = qualidade(mv, "mae", True, cfg)
    q2["metrica"] = "MAE por região e hora"

    db.execute(text("DELETE FROM previsao WHERE modulo IN ('P2', 'P3') AND detalhe->>'origem' = :o"), {"o": origem.isoformat()})
    p2_linhas, p3_linhas, entradas = [], [], {}
    for x in reg.itertuples():
        regiao = str(x.regiao)
        ini = x.em.to_pydatetime()
        fim = (x.em + pd.Timedelta(hours=1)).to_pydatetime()
        local = x.em.tz_convert(V.FUSO)
        normal_h = float(x.normal_hora)
        razao = x.previsto / normal_h if normal_h > 0 else 1.0
        niv = "MUITO_ACIMA" if razao >= 1.5 else "ACIMA" if razao >= 1.15 else "ABAIXO" if razao < 0.85 else "NORMAL"
        pr = props[(props.regiao == regiao) & (props.util == (local.day_of_week < 5)) & (props.hora == local.hour)]
        cats = [{"categoria": c, "previstas": round(float(x.previsto * p_), 2)}
                for c, p_ in sorted(zip(pr.categoria, pr.proporcao), key=lambda t: -t[1])[:4]]
        ev_pub, ev_nome = eventos.get((regiao, x.em), (0, None))
        comum = {"origem": origem.isoformat(), "alvo": {"tipo": "regiao", "id": int(x.regiao_id), "nome": regiao, "regiao": regiao},
                 "hora_local": local.isoformat()}
        p2_linhas.append({
            "modulo": "P2", "alvo_tipo": "regiao", "alvo_id": int(x.regiao_id), "regiao_id": int(x.regiao_id),
            "horizonte_inicio": ini, "horizonte_fim": fim, "valor": float(x.previsto), "faixa_inferior": float(x.lo),
            "faixa_superior": float(x.hi), "nivel": niv, "fatores": fat.get((x.em, regiao), []),
            "dados_considerados": p2.DADOS_CONSIDERADOS, "modelo_versao_id": mv.id,
            "detalhe": {**comum, "o_que_preve": f"Ocorrências esperadas na região {regiao} em {local:%d/%m} das {local:%H} h às {(local + pd.Timedelta(hours=1)):%H} h",
                        "normal": round(normal_h, 2), "razao_normal": round(razao, 2), "por_categoria": cats,
                        "como_ajuda": COMO_AJUDA_P2,
                        "acao_recomendada": {"texto": "Ver a recomendação de equipes para este horário", "tipo": "VER_PLANEJAMENTO",
                                             "parametros": {"regiao_id": int(x.regiao_id), "inicio": ini.isoformat()}},
                        "qualidade_do_modelo": q2, "modelo": {"nome": mv.nome, "versao": mv.versao}},
        })
        s = situacao.get(regiao, vazio)
        base = dict(gravidade_media=grav.get(regiao, grav_cidade), gravidade_normal=grav_cidade, **s,
                    agentes=float(x.agentes), evento_publico=ev_pub, evento_nome=ev_nome, chuva_mm=float(x.chuva_mm),
                    tempestade=bool(tempestade.get(x.em, False)))
        fator = cfg["prev_agentes_por_ocorrencia"]
        e = p3.Entrada(previstas=float(x.previsto), normal=normal.get(regiao, 0.1), demanda_agentes=float(x.previsto) * fator, **base)
        e_lo = p3.Entrada(previstas=float(x.lo), normal=normal.get(regiao, 0.1), demanda_agentes=float(x.lo) * fator, **base)
        e_hi = p3.Entrada(previstas=float(x.hi), normal=normal.get(regiao, 0.1), demanda_agentes=float(x.hi) * fator, **base)
        entradas.setdefault((regiao, int(x.regiao_id), local.date(), p3.periodo_da_hora(local.hour)), []).append((ini, fim, e, e_lo, e_hi))
        p3_linhas.append(_linha_p3(p3.indice(e, pesos), p3.indice(e_lo, pesos), p3.indice(e_hi, pesos), int(x.regiao_id),
                                   regiao, ini, fim, comum, "hora", None, mv, q2, local))
    for (regiao, rid, dia, per), itens in entradas.items():
        ini, fim = itens[0][0], itens[-1][1]
        juntos = [p3.somar([i[k] for i in itens]) for k in (2, 3, 4)]
        local = pd.Timestamp(ini).tz_convert(V.FUSO)
        p3_linhas.append(_linha_p3(*(p3.indice(j, pesos) for j in juntos), rid, regiao, ini, fim,
                                   {"origem": origem.isoformat(), "alvo": {"tipo": "regiao", "id": rid, "nome": regiao, "regiao": regiao},
                                    "hora_local": local.isoformat(), "data_local": dia.isoformat()}, "periodo", per, mv, q2, local))
    db.execute(insert(Previsao), p2_linhas)
    db.execute(insert(Previsao), p3_linhas)
    db.commit()
    return {"p2": len(p2_linhas), "p3": len(p3_linhas)}


def _linha_p3(r: dict, r_lo: dict, r_hi: dict, rid: int, regiao: str, ini, fim, comum: dict, granularidade: str,
              periodo: str | None, mv, q2: dict, local: pd.Timestamp) -> dict:
    from app.preditivo import p3

    quando = (f"{p3.NOME_PERIODO[periodo].split(' (')[0].lower()} de {local:%d/%m}" if periodo
              else f"{local:%d/%m} das {local:%H} h às {(local + pd.Timedelta(hours=1)):%H} h")
    alto = r["nivel"] in ("ALTO", "MUITO_ALTO")
    acao = ({"texto": f"Reforçar a região {regiao} ({quando}): ver a recomendação de equipes", "tipo": "REFORCAR_EQUIPES",
             "parametros": {"regiao_id": rid, "inicio": ini.isoformat(), "fim": fim.isoformat()}}
            if alto else {"texto": "Nenhuma ação extra: manter a escala prevista", "tipo": "NENHUMA", "parametros": {}})
    return {
        "modulo": "P3", "alvo_tipo": "regiao", "alvo_id": rid, "regiao_id": rid, "horizonte_inicio": ini, "horizonte_fim": fim,
        "valor": r["indice"], "faixa_inferior": min(r_lo["indice"], r_hi["indice"]),
        "faixa_superior": max(r_lo["indice"], r_hi["indice"]), "nivel": r["nivel"],
        "fatores": [{"descricao": f"{c['nome']}: {c['descricao']}", "efeito": c["contribuicao"], "grupo": c["componente"]}
                    for c in sorted(r["componentes"], key=lambda c: -c["contribuicao"])],
        "dados_considerados": ["Ocorrências previstas por hora (P2)", "Risco de falha dos equipamentos (P1)",
                               "Equipamentos fora de operação agora", "Escala de agentes", "Eventos programados e previsão do tempo"],
        "modelo_versao_id": mv.id,
        "detalhe": {**comum, "granularidade": granularidade, "periodo": periodo,
                    "o_que_preve": f"Índice de risco da região {regiao}, {quando}",
                    "componentes": r["componentes"], "motivo_principal": r["motivo_principal"], "nivel_nome": r["nivel_nome"],
                    "como_ajuda": COMO_AJUDA_P3, "acao_recomendada": acao, "qualidade_do_modelo": q2,
                    "modelo": {"nome": "indice_risco_regiao", "versao": mv.versao}},
    }
