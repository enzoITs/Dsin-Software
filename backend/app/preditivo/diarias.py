"""Previsões diárias da fase 12, gravadas na tabela `previsao` junto com as de P1 (lote das 5 h).

- P6: disponibilidade dos fixos em 30 e 90 dias por região, cidade e tipo, com os cenários
  "se nada mudar" e "seguindo P1".
- P7: probabilidade de furto de cada equipamento em 30 dias.
- P8: carga de manutenção (corretivas esperadas e preventivas programadas) por semana, região e tipo
  nas próximas 4 semanas, em técnicos-dia e peças.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, text
from sqlalchemy.orm import Session

from app.domain import limites
from app.models import Previsao
from app.preditivo import artefatos, p6, p7
from app.preditivo import variaveis as V
from app.preditivo.prever import hoje_local, qualidade

NOME_TIPO = {"CAM": "Câmeras", "RAD": "Radares", "TOT": "Totens do rotativo", "BAL": "Balanças", "CAN": "Cancelas",
             "VIA": "Sensores de via", "VAF": "Painéis de mensagem"}


def _p1_ultimo(db: Session) -> pd.DataFrame:
    """Último lote de P1: probabilidade de falha em 7 e 30 dias e o nível em 30 dias, por equipamento."""
    r = db.execute(text("""
        SELECT alvo_id id, valor, nivel, horizonte_fim - horizonte_inicio = interval '7 days' sete FROM previsao
        WHERE modulo = 'P1' AND horizonte_inicio = (SELECT max(horizonte_inicio) FROM previsao WHERE modulo = 'P1')"""))
    df = pd.DataFrame(r.fetchall(), columns=["id", "valor", "nivel", "sete"])
    if df.empty:
        return pd.DataFrame(columns=["id", "p7", "p30", "nivel30"])
    a = df[df.sete].rename(columns={"valor": "p7"})[["id", "p7"]]
    b = df[~df.sete].rename(columns={"valor": "p30", "nivel": "nivel30"})[["id", "p30", "nivel30"]]
    return a.merge(b, on="id", how="outer")


def _apagar(db: Session, modulo: str, inicio: datetime) -> None:
    db.execute(delete(Previsao).where(Previsao.modulo == modulo, Previsao.horizonte_inicio == inicio))


def _inserir(db: Session, valores: list[dict]) -> None:
    for i in range(0, len(valores), 5000):
        db.execute(insert(Previsao), valores[i:i + 5000])


# ---------------------------------------------------------------- P6

def calcular_p6(db: Session, f: V.Fontes, hoje, cfg: dict, mv) -> list[dict]:
    corte = V.corte_local(hoje)
    meta = cfg["saude_meta_disponibilidade"] / 100
    q90 = (mv.metricas or {}).get("q90", {})
    q = {"metrica": "erro médio em 30 dias (pontos percentuais)", "modelo": (mv.metricas or {}).get("mae_pp"),
         "baseline": (mv.metricas_baseline or {}).get("mae_pp"), "avaliado_em": f"backtest de {cfg['prev_backtest_dias']} dias"}
    inicio = hoje - timedelta(days=p6.DIAS_HISTORICO + 5)
    reg = V.disponibilidade_diaria(f, inicio, hoje).assign(grupo="regiao")
    tip = V.disponibilidade_diaria(f, inicio, hoje, por="prefixo")
    tip = tip[tip.regiao != "Cidade"].assign(grupo="tipo")
    serie = pd.concat([reg, tip], ignore_index=True)

    eq = f.equipamentos[~f.equipamentos.movel & f.equipamentos.regiao.notna()][["id", "regiao", "prefixo"]].copy()
    eq["prefixo"] = eq.prefixo.astype(str)
    p1 = _p1_ultimo(db).merge(eq, on="id")
    alto = p1[p1.nivel30.isin(["ALTO", "MUITO_ALTO"])]
    atrasadas = pd.DataFrame(db.execute(text("""
        SELECT p.equipamento_id id FROM plano_manutencao p JOIN equipamento e ON e.id = p.equipamento_id
        WHERE p.tipo = 'periodica' AND p.ativo AND p.proxima_data < :h
          AND e.situacao IN ('operacional', 'mau_funcionamento', 'em_manutencao')"""), {"h": hoje}).fetchall(),
        columns=["id"]).merge(eq, on="id")
    sem_os = set(db.scalars(text("SELECT equipamento_id FROM ordem_servico WHERE status = 'aberta'")))
    conserto_reg = p6.dias_conserto(f, corte)
    conserto_tip = p6.dias_conserto(f, corte, por="prefixo")
    reg_ids = dict(zip(f.bairros.regiao, f.bairros.regiao_id))
    efic = cfg["prev_p6_eficacia_preventiva"]
    dias = max(p6.HORIZONTES)
    meia = p6.faixa(q90, dias)
    linhas = []
    for (grupo, nome), x in serie.groupby(["grupo", "regiao"]):
        x = x.sort_values("dia")
        hist = x.disponibilidade.to_numpy()
        if len(hist) < 60 or np.isnan(hist[-1]):
            continue
        atual, em_servico = float(hist[-1]), int(x.em_servico.iloc[-1])
        prev = p6.prever_serie(hist, dias)
        if grupo == "regiao" and nome == "Cidade":
            sel, a_sel, conserto, alvo_tipo = alto, atrasadas, conserto_reg.get("Cidade", 0), "cidade"
        elif grupo == "regiao":
            sel, a_sel, conserto, alvo_tipo = alto[alto.regiao == nome], atrasadas[atrasadas.regiao == nome], conserto_reg.get(nome, 0), "regiao"
        else:
            sel, a_sel, conserto, alvo_tipo = alto[alto.prefixo == nome], atrasadas[atrasadas.prefixo == nome], conserto_tip.get(nome, 0), "tipo"
        esperadas = float(sel.p30.sum())
        ganho = p6.ganho_seguindo_p1(esperadas * efic, conserto, em_servico, dias)
        seguindo = np.clip(prev + ganho, 0, 1)
        abaixo = np.nonzero(prev < meta)[0]
        abaixo_p1 = np.nonzero(seguindo < meta)[0]
        nome_alvo = NOME_TIPO.get(nome, nome) if grupo == "tipo" else nome
        rid = reg_ids.get(nome) if alvo_tipo == "regiao" else None
        onde = (f"da região {nome}" if alvo_tipo == "regiao" else "da cidade" if alvo_tipo == "cidade"
                else f"de {nome_alvo.lower()} da cidade")
        ids_acao = [int(i) for i in sel.sort_values("p30", ascending=False).id if int(i) not in sem_os][:20]
        historico = [{"dia": d.isoformat(), "valor": round(float(v), 4)} for d, v in zip(x.dia.iloc[-180:], hist[-180:])]
        previsto = [{"dia": (hoje + timedelta(days=k + 1)).isoformat(), "valor": round(float(prev[k]), 4),
                     "inferior": round(float(max(prev[k] - meia[k], 0)), 4), "superior": round(float(min(prev[k] + meia[k], 1)), 4),
                     "seguindo_p1": round(float(seguindo[k]), 4)} for k in range(dias)]
        for h in p6.HORIZONTES:
            v = float(prev[h - 1])
            niv = p6.nivel(v, atual, meta)
            fim = corte + pd.Timedelta(days=h)
            quando = (hoje + timedelta(days=h)).strftime("%d/%m")
            if niv == "ABAIXO_META" and (ids_acao or len(a_sel)):
                acao = {"texto": (f"Priorizar a manutenção {onde}: abrir OS preventiva para os {len(ids_acao)} equipamentos "
                                  f"de risco alto e pôr em dia as {len(a_sel)} preventivas atrasadas"),
                        "tipo": "PRIORIZAR_MANUTENCAO", "parametros": {"equipamento_ids": ids_acao, "grupo": nome,
                                                                     "alvo_tipo": alvo_tipo, "preventivas_atrasadas": len(a_sel)}}
            elif niv == "ATENCAO":
                acao = {"texto": f"Acompanhar {onde}: incluir os equipamentos de risco alto na próxima rota de preventiva",
                        "tipo": "NENHUMA", "parametros": {}}
            else:
                acao = {"texto": "Nenhuma ação extra: manter a manutenção programada", "tipo": "NENHUMA", "parametros": {}}
            linhas.append({
                "modulo": "P6", "alvo_tipo": alvo_tipo, "alvo_id": rid, "regiao_id": rid,
                "horizonte_inicio": corte.to_pydatetime(), "horizonte_fim": fim.to_pydatetime(), "valor": v,
                "faixa_inferior": max(v - float(meia[h - 1]), 0), "faixa_superior": min(v + float(meia[h - 1]), 1),
                "nivel": niv, "fatores": p6.fatores(atual, v, len(sel), float(ganho[h - 1]), len(a_sel), conserto,
                                                    conserto_reg.get("Cidade", 0)),
                "dados_considerados": p6.DADOS_CONSIDERADOS, "modelo_versao_id": mv.id,
                "detalhe": {
                    "o_que_preve": f"Disponibilidade dos equipamentos fixos {onde} em {quando} (daqui a {h} dias)",
                    "alvo": {"tipo": alvo_tipo, "id": rid, "nome": nome_alvo, "regiao": nome if alvo_tipo == "regiao" else None,
                             "grupo": nome},
                    "como_ajuda": p6.COMO_AJUDA, "acao_recomendada": acao, "qualidade_do_modelo": q,
                    "modelo": {"nome": mv.nome, "versao": mv.versao}, "horizonte_dias": h, "meta": meta, "atual": atual,
                    "em_servico": em_servico, "seguindo_p1": float(seguindo[h - 1]),
                    "cruza_meta_em": (hoje + timedelta(days=int(abaixo[0]) + 1)).isoformat() if len(abaixo) else None,
                    "cruza_meta_seguindo_p1_em": (hoje + timedelta(days=int(abaixo_p1[0]) + 1)).isoformat() if len(abaixo_p1) else None,
                    "falhas_evitaveis": round(esperadas * efic, 1), "eficacia_preventiva": efic, "dias_conserto": round(conserto, 1),
                    "historico": historico if h == 30 else None, "previsto": previsto if h == 30 else None,
                },
            })
    return linhas


def prever_p6(db: Session, f: V.Fontes | None = None, agora: datetime | None = None) -> int:
    cfg = limites.carregar(db, forcar=True)
    mv, _ = artefatos.ativo(db, "disponibilidade_regiao")
    if mv is None:
        return 0
    hoje = hoje_local(agora)
    f = f or V.carregar(db)
    linhas = calcular_p6(db, f, hoje, cfg, mv)
    _apagar(db, "P6", V.corte_local(hoje).to_pydatetime())
    _inserir(db, linhas)
    db.commit()
    return len(linhas)


# ---------------------------------------------------------------- P7

def prever_p7(db: Session, f: V.Fontes | None = None, agora: datetime | None = None) -> int:
    cfg = limites.carregar(db, forcar=True)
    mv, modelo = artefatos.ativo(db, "furto_equipamento_30d")
    if modelo is None:
        return 0
    hoje = hoje_local(agora)
    corte = V.corte_local(hoje)
    f = f or V.carregar(db)
    ctx = p7.contexto(db, f)
    x = p7.variaveis(f, ctx, [corte], alvo=False)
    if x.empty:
        return 0
    prob = modelo.prever(x)
    fat = p7.fatores(modelo, x)
    q = qualidade(mv, "auc", False, cfg)
    codigos = dict(db.execute(text("SELECT id, codigo_interno FROM equipamento")).all())
    reg_ids = dict(zip(f.bairros.regiao, f.bairros.regiao_id))
    nomes_b = dict(zip(f.bairros.id, f.bairros.bairro))
    fim = corte + pd.Timedelta(days=p7.JANELA)
    _apagar(db, "P7", corte.to_pydatetime())
    valores = []
    for r, p, fs in zip(x.itertuples(), prob, fat):
        p = float(p)
        niv = p7.nivel(p, cfg["prev_p7_limites_nivel"])
        cod = codigos.get(r.id, str(r.id))
        regiao = str(r.regiao) if isinstance(r.regiao, str) else None
        bairro = nomes_b.get(r.bairro_id)
        valores.append({
            "modulo": "P7", "alvo_tipo": "equipamento", "alvo_id": int(r.id), "regiao_id": reg_ids.get(regiao),
            "horizonte_inicio": corte.to_pydatetime(), "horizonte_fim": fim.to_pydatetime(), "valor": p,
            "faixa_inferior": max(0.0, p * 0.5), "faixa_superior": min(1.0, p * 1.8), "nivel": niv, "fatores": fs,
            "dados_considerados": p7.DADOS_CONSIDERADOS, "modelo_versao_id": mv.id,
            "detalhe": {
                "o_que_preve": f"Probabilidade de furto de {cod} nos próximos {p7.JANELA} dias",
                "alvo": {"tipo": "equipamento", "id": int(r.id), "nome": cod, "regiao": regiao, "bairro": bairro,
                         "tipo_equipamento": r.prefixo},
                "como_ajuda": p7.COMO_AJUDA, "acao_recomendada": p7.acao(niv, cod, int(r.id), float(r.dist_camera_m), regiao),
                "qualidade_do_modelo": q, "modelo": {"nome": mv.nome, "versao": mv.versao}, "janela_dias": p7.JANELA,
                "dist_camera_m": round(float(r.dist_camera_m)), "furtos_500m_365d": int(r.furtos_500m_365d),
                "vezes_a_media": round(p / max(modelo.taxa_treino, 1e-6), 1),
            },
        })
    _inserir(db, valores)
    db.commit()
    return len(valores)


# ---------------------------------------------------------------- P8

SEMANAS_P8 = 4


def _horas(cfg_horas: dict, prefixo: str) -> float:
    return float(cfg_horas.get(prefixo, cfg_horas["padrao"]))


def carga(db: Session, f: V.Fontes, hoje, cfg: dict) -> pd.DataFrame:
    """Uma linha por equipamento × semana com corretivas esperadas, preventivas, horas e peças."""
    corte = V.corte_local(hoje)
    estado = V._estado_em(f.historico, corte)
    eq = f.equipamentos[["id", "prefixo", "regiao", "movel"]].copy()
    eq["prefixo"] = eq.prefixo.astype(str)
    eq["regiao"] = eq.regiao.fillna("?")
    eq["estado"] = eq.id.map(estado)
    p1 = _p1_ultimo(db)
    partes = []
    # Corretivas esperadas: P1 em 7 dias na primeira semana; o restante dos 30 dias espalhado nas outras três
    x = p1.merge(eq, on="id")
    p7_, p30_ = x.p7.fillna(0).to_numpy(), x.p30.fillna(0).to_numpy()
    for k in range(SEMANAS_P8):
        pk = p7_ if k == 0 else np.clip(p30_ - p7_, 0, 1) * 7 / 23
        partes.append(pd.DataFrame({"id": x.id, "prefixo": x.prefixo, "regiao": x.regiao, "semana": k, "corretivas": pk,
                                    "var": pk * (1 - pk), "preventivas": 0.0, "pendentes": 0.0, "atrasadas": 0.0}))
    # Já parados à espera de conserto: entram na primeira semana
    parados = eq[eq.estado == "mau_funcionamento"]
    partes.append(pd.DataFrame({"id": parados.id, "prefixo": parados.prefixo, "regiao": parados.regiao, "semana": 0,
                                "corretivas": 0.0, "var": 0.0, "preventivas": 0.0, "pendentes": 1.0, "atrasadas": 0.0}))
    prev = pd.DataFrame(db.execute(text("""
        SELECT p.equipamento_id id, p.proxima_data FROM plano_manutencao p JOIN equipamento e ON e.id = p.equipamento_id
        WHERE p.tipo = 'periodica' AND p.ativo AND p.proxima_data < :fim
          AND e.situacao IN ('operacional', 'mau_funcionamento', 'em_manutencao')"""),
        {"fim": hoje + timedelta(weeks=SEMANAS_P8)}).fetchall(), columns=["id", "proxima_data"])
    if len(prev):
        prev = prev.merge(eq[["id", "prefixo", "regiao"]], on="id")
        cols = ["id", "prefixo", "regiao", "semana", "corretivas", "var", "preventivas", "pendentes", "atrasadas"]
        atrasada = prev.proxima_data < hoje
        no_prazo = prev[~atrasada].assign(semana=[(d - hoje).days // 7 for d in prev.proxima_data[~atrasada]])
        partes.append(no_prazo.assign(corretivas=0.0, var=0.0, preventivas=1.0, pendentes=0.0, atrasadas=0.0)[cols])
        # Atrasadas: o plano é zerar o atraso nas 4 semanas, um quarto por semana
        for k in range(SEMANAS_P8):
            partes.append(prev[atrasada].assign(semana=k, corretivas=0.0, var=0.0, preventivas=1 / SEMANAS_P8, pendentes=0.0,
                                                atrasadas=1 / SEMANAS_P8)[cols])
    df = pd.concat(partes, ignore_index=True)
    hc, hp = cfg["prev_p8_horas_corretiva"], cfg["prev_p8_horas_preventiva"]
    df["h_corr"] = df.prefixo.map(lambda t: _horas(hc, t))
    df["h_prev"] = df.prefixo.map(lambda t: _horas(hp, t))
    df["horas"] = (df.corretivas + df.pendentes) * df.h_corr + df.preventivas * df.h_prev
    df["var_horas"] = df["var"] * df.h_corr ** 2
    pecas = cfg["prev_p8_pecas_por_corretiva"]
    df["pecas"] = (df.corretivas + df.pendentes) * df.prefixo.map(lambda t: float(pecas.get(t, pecas["padrao"])))
    return df


def normal_semanal(f: V.Fontes, hoje, cfg: dict, semanas: int = 8) -> dict[str, float]:
    """Horas de manutenção executadas por semana nas últimas `semanas`, por região (e na cidade)."""
    corte = V.corte_local(hoje)
    r = f.registros[(f.registros.em < corte) & (f.registros.em >= corte - pd.Timedelta(weeks=semanas))]
    r = r.merge(f.equipamentos[["id", "prefixo", "regiao"]], left_on="equipamento_id", right_on="id")
    hc, hp = cfg["prev_p8_horas_corretiva"], cfg["prev_p8_horas_preventiva"]
    r["horas"] = [_horas(hp if pv else hc, str(t)) for pv, t in zip(r.preventiva, r.prefixo)]
    saida = {str(k): float(v) / semanas for k, v in r.groupby(r.regiao.fillna("?")).horas.sum().items()}
    saida["Cidade"] = float(r.horas.sum()) / semanas
    return saida


def calcular_p8(db: Session, f: V.Fontes, hoje, cfg: dict, mv) -> list[dict]:
    corte = V.corte_local(hoje)
    df = carga(db, f, hoje, cfg)
    jornada = cfg["prev_p8_horas_dia"]
    normal = normal_semanal(f, hoje, cfg)
    reg_ids = dict(zip(f.bairros.regiao, f.bairros.regiao_id))
    m, b = (mv.metricas or {}) if mv else {}, (mv.metricas_baseline or {}) if mv else {}
    q = {"metrica": "erro médio de falhas em 30 dias por tipo e região", "modelo": m.get("mae"), "baseline": b.get("mae"),
         "avaliado_em": f"backtest de {cfg['prev_backtest_dias']} dias (herda o P1)"}
    linhas = []
    grupos = [(r, df[df.regiao == r]) for r in sorted(df.regiao.unique()) if r != "?"] + [("Cidade", df)]
    for nome, x in grupos:
        for k in range(SEMANAS_P8):
            s = x[x.semana == k]
            ini = corte + pd.Timedelta(weeks=k)
            fim = ini + pd.Timedelta(weeks=1)
            horas = float(s.horas.sum())
            td = horas / jornada
            sd = float(np.sqrt(s.var_horas.sum())) / jornada
            norm_td = normal.get(nome, 0) / jornada
            razao = td / norm_td if norm_td > 0 else 1.0
            niv = "MUITO_ACIMA" if razao >= 1.5 else "ACIMA" if razao >= 1.15 else "ABAIXO" if razao < 0.85 else "NORMAL"
            por_tipo = []
            for t, y in s.groupby("prefixo"):
                por_tipo.append({"tipo": t, "nome": NOME_TIPO.get(t, t), "corretivas": round(float(y.corretivas.sum()), 1),
                                 "pendentes": int(y.pendentes.sum()), "preventivas": round(float(y.preventivas.sum())),
                                 "tecnicos_dia": round(float(y.horas.sum()) / jornada, 1), "pecas": round(float(y.pecas.sum()), 1)})
            por_tipo.sort(key=lambda t: -t["tecnicos_dia"])
            corr, pend, prev = float(s.corretivas.sum()), int(s.pendentes.sum()), round(float(s.preventivas.sum()))
            atras = round(float(s.atrasadas.sum()) * SEMANAS_P8)
            td_corr = float(((s.corretivas) * s.h_corr).sum()) / jornada
            td_pend = float((s.pendentes * s.h_corr).sum()) / jornada
            td_prev = float((s.preventivas * s.h_prev).sum()) / jornada
            rotulo = f"semana de {ini:%d/%m} a {(fim - pd.Timedelta(days=1)):%d/%m}"
            fatores = [{"descricao": f"{corr:.0f} falhas esperadas pelo risco de falha (P1)", "efeito": round(td_corr, 1), "grupo": "corretivas"},
                       {"descricao": f"{prev} preventivas programadas"
                        + (f", incluindo um quarto das {atras} atrasadas (plano de zerar o atraso em {SEMANAS_P8} semanas)" if atras else ""),
                        "efeito": round(td_prev, 1), "grupo": "preventivas"}]
            if pend:
                fatores.append({"descricao": f"{pend} equipamentos já parados à espera de conserto", "efeito": round(td_pend, 1),
                                "grupo": "pendentes"})
            fatores.sort(key=lambda z: -z["efeito"])
            alvo_tipo = "cidade" if nome == "Cidade" else "regiao"
            rid = reg_ids.get(nome)
            onde = "na cidade" if nome == "Cidade" else f"na região {nome}"
            pecas = round(float(s.pecas.sum()))
            acao = ({"texto": (f"Planejar {td:.0f} técnicos-dia {onde} na {rotulo} (normal: {norm_td:.0f}) e separar cerca de "
                               f"{pecas} kits de reparo"), "tipo": "PLANEJAR_MANUTENCAO",
                     "parametros": {"regiao": nome, "inicio": ini.isoformat(), "tecnicos_dia": round(td, 1), "pecas": pecas}}
                    if niv in ("ACIMA", "MUITO_ACIMA") else
                    {"texto": f"Manter a equipe de manutenção {onde} (carga prevista dentro do normal)", "tipo": "NENHUMA", "parametros": {}})
            linhas.append({
                "modulo": "P8", "alvo_tipo": alvo_tipo, "alvo_id": rid, "regiao_id": rid,
                "horizonte_inicio": ini.to_pydatetime(), "horizonte_fim": fim.to_pydatetime(), "valor": td,
                "faixa_inferior": max(td - 1.645 * sd, 0), "faixa_superior": td + 1.645 * sd, "nivel": niv, "fatores": fatores,
                "dados_considerados": ["Risco de falha em 7 e 30 dias de cada equipamento (P1)", "Plano de manutenção preventiva",
                                       "Equipamentos parados à espera de conserto", "Tempo de serviço por tipo de equipamento"],
                "modelo_versao_id": mv.id if mv else None,
                "detalhe": {
                    "o_que_preve": f"Carga de manutenção {onde} na {rotulo}, em técnicos-dia",
                    "alvo": {"tipo": alvo_tipo, "id": rid, "nome": nome, "regiao": None if nome == "Cidade" else nome},
                    "como_ajuda": ("Dimensiona a equipe técnica e as peças semanas antes, para a manutenção não virar fila "
                                   "nem deixar equipamentos parados esperando"),
                    "acao_recomendada": acao, "qualidade_do_modelo": q,
                    "modelo": {"nome": "carga_manutencao", "versao": mv.versao if mv else None}, "semana": k,
                    "origem": corte.isoformat(), "rotulo": rotulo,
                    "corretivas": round(corr, 1), "pendentes": pend, "preventivas": prev, "preventivas_atrasadas": atras, "pecas": pecas,
                    "normal_tecnicos_dia": round(norm_td, 1), "razao_normal": round(razao, 2), "por_tipo": por_tipo,
                    "horas": round(horas, 1), "jornada_h": jornada,
                },
            })
    return linhas


def prever_p8(db: Session, f: V.Fontes | None = None, agora: datetime | None = None) -> int:
    cfg = limites.carregar(db, forcar=True)
    mv, _ = artefatos.ativo(db, "carga_manutencao")
    hoje = hoje_local(agora)
    f = f or V.carregar(db)
    linhas = calcular_p8(db, f, hoje, cfg, mv)
    corte = V.corte_local(hoje)
    db.execute(text("DELETE FROM previsao WHERE modulo = 'P8' AND detalhe->>'origem' = :o"), {"o": corte.isoformat()})
    _inserir(db, linhas)
    db.commit()
    return len(linhas)


def avaliar_p8(previsoes_p1_30d: pd.DataFrame) -> dict:
    """Qualidade de P8 pelo backtest de P1 em 30 dias: falhas por corte, tipo e região, previstas × reais."""
    x = previsoes_p1_30d.groupby(["corte", "regiao", "prefixo"], observed=True)[["y", "p", "p_base"]].sum().reset_index()
    err, err_b = (x.p - x.y).abs(), (x.p_base - x.y).abs()
    tot = max(float(x.y.sum()), 1e-9)
    return {"modelo": {"mae": float(err.mean()), "erro_pct": float(err.sum() / tot * 100), "n": int(len(x))},
            "baseline": {"mae": float(err_b.mean()), "erro_pct": float(err_b.sum() / tot * 100), "n": int(len(x))},
            "por_corte": [{"data_corte": pd.Timestamp(c).date(), "mae": float((g.p - g.y).abs().mean()),
                           "mae_baseline": float((g.p_base - g.y).abs().mean()), "falhas": int(g.y.sum())}
                          for c, g in x.groupby("corte")]}


def lote(db: Session, f: V.Fontes | None = None, agora: datetime | None = None) -> dict:
    f = f or V.carregar(db)
    return {"p6": prever_p6(db, f, agora), "p7": prever_p7(db, f, agora), "p8": prever_p8(db, f, agora)}
