"""Padrões descobertos (Q2): o que os modelos aprenderam, comparado com o que foi plantado nos dados.

Os modelos nunca leem `padroes.py`. Aqui, depois do treino, perguntamos ao modelo pronto:
- P1 (falha): "e se este mesmo equipamento fosse mais velho / estivesse mais quente / com a preventiva
  atrasada?" (contrafactual sobre os equipamentos reais, uma variável por vez; é a dependência parcial
  do modelo). O efeito aprendido é a razão entre as probabilidades médias.
- P2 (ocorrências): o perfil por hora e dia que o modelo prevê nas últimas 4 semanas, ao lado do que
  aconteceu, e contrafactuais de chuva, evento e véspera de feriado.
- Padrões sem modelo próprio ainda (furtos, disponibilidade) ou de detectores (anomalias): consulta direta,
  dita como tal.

Só no fim o resultado é posto ao lado da regra plantada (lida de `padroes.py`, que é a "resposta da
prova"). Os dados são sintéticos: o relatório mostra que o método acha padrões reais quando eles existem.
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import EstadoPreditivo
from app.preditivo import artefatos, prever, verificacao
from app.preditivo import padroes as P
from app.preditivo import variaveis as V

ACHADO, FRACO = 1.3, 1.1


def _veredito(efeito: float | None, achado: float = ACHADO, fraco: float = FRACO) -> str:
    if efeito is None:
        return "sem_dados"
    return "encontrado" if efeito >= achado else "fraco" if efeito >= fraco else "nao_encontrado"


def _fmt(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def _media(modelo, df: pd.DataFrame, **valores) -> float:
    x = df.copy()
    for k, v in valores.items():
        x[k] = v
    return float(np.mean(modelo.prever(x)))


# ---------------------------------------------------------------- P1


def padroes_p1(modelo, eq: pd.DataFrame) -> tuple[list[dict], dict]:
    itens, curvas = [], {}
    cam = eq[eq.prefixo.astype(str) == "CAM"]
    fragil = cam[cam.marca.astype(str).str.strip() == P.MARCA_FRAGIL]
    outras = cam[cam.marca.astype(str).str.strip() != P.MARCA_FRAGIL]
    if len(fragil) and len(outras):
        def razao(df):
            return _media(modelo, df, idade_dias=730) / _media(modelo, df, idade_dias=300)
        rf, ro = razao(fragil), razao(outras)
        ef = rf / ro
        chuva = (_media(modelo, fragil, idade_dias=730, dias_chuva_forte_7d=2, chuva_ontem=15.0)
                 / _media(modelo, fragil, idade_dias=730, dias_chuva_forte_7d=0, chuva_ontem=0.0))
        itens.append({
            "padrao": 4, "titulo": "Câmeras de uma marca falham mais depois de 18 meses, sobretudo após chuva", "modulo": "P1",
            "metodo": "Contrafactual no modelo: as mesmas câmeras com 10 e com 24 meses de uso",
            "descoberto": (f"Para as câmeras {P.MARCA_FRAGIL.title()}, passar de 10 para 24 meses multiplica o risco previsto por "
                           f"{_fmt(rf)}; para as outras marcas, por {_fmt(ro)}. Chuva forte na semana multiplica o risco das "
                           f"{P.MARCA_FRAGIL.title()} antigas por {_fmt(chuva)}"),
            "efeito": round(ef, 2), "plantado": f"{_fmt(P.FATOR_FRAGIL, 0)}× depois de {P.MESES_FRAGIL} meses, mais "
                                                 f"{_fmt(P.FATOR_FRAGIL_CHUVA, 0)}× no dia seguinte a chuva forte",
            "veredito": _veredito(ef)})
        meses = list(range(0, 49, 6))
        curvas["idade_camera"] = [{"meses": m, "marca_fragil": _media(modelo, fragil, idade_dias=m * 30.4),
                                   "outras": _media(modelo, outras, idade_dias=m * 30.4)} for m in meses]

    rad = eq[eq.prefixo.astype(str) == "RAD"]
    rodovia = rad[rad.velocidade_maxima.fillna(0) >= P.VELOCIDADE_RODOVIA]
    urbano = rad[rad.velocidade_maxima.fillna(0) < P.VELOCIDADE_RODOVIA]
    if len(rodovia) and len(urbano):
        quente = dict(tmax_prevista_7d=36.0, tmax_7d=36.0, dias_calor_previstos_7d=4)
        ameno = dict(tmax_prevista_7d=27.0, tmax_7d=27.0, dias_calor_previstos_7d=0)
        rr = _media(modelo, rodovia, **quente) / _media(modelo, rodovia, **ameno)
        ru = _media(modelo, urbano, **quente) / _media(modelo, urbano, **ameno)
        itens.append({
            "padrao": 5, "titulo": "Radares de rodovia falham mais acima de 32 °C", "modulo": "P1",
            "metodo": "Contrafactual no modelo: os mesmos radares numa semana de 36 °C (4 dias quentes) e numa de 27 °C",
            "descoberto": f"Semana quente multiplica o risco previsto dos radares de rodovia por {_fmt(rr)} e dos urbanos por {_fmt(ru)}",
            "efeito": round(rr / ru, 2), "plantado": f"{_fmt(P.FATOR_CALOR, 0)}× nos dias acima de {P.TEMPERATURA_CALOR:.0f} °C, "
                                                     f"só radares com limite de {P.VELOCIDADE_RODOVIA} km/h ou mais",
            "veredito": _veredito(rr / ru)})
        temps = list(range(24, 39, 2))
        curvas["calor_radar"] = [{"temperatura": t,
                                  "rodovia": _media(modelo, rodovia, tmax_prevista_7d=float(t), tmax_7d=float(t),
                                                    dias_calor_previstos_7d=4 if t > P.TEMPERATURA_CALOR else 0),
                                  "urbano": _media(modelo, urbano, tmax_prevista_7d=float(t), tmax_7d=float(t),
                                                   dias_calor_previstos_7d=4 if t > P.TEMPERATURA_CALOR else 0)} for t in temps]

    com_plano = eq[eq.periodicidade.notna()]
    if len(com_plano):
        per = com_plano.periodicidade
        atrasado = com_plano.assign(atraso_preventiva=30.0, dias_desde_preventiva=per + 30)
        em_dia = com_plano.assign(atraso_preventiva=-5.0, dias_desde_preventiva=per - 5)
        r7 = float(np.mean(modelo.prever(atrasado))) / float(np.mean(modelo.prever(em_dia)))
        itens.append({
            "padrao": 7, "titulo": "Manutenção atrasada há mais de 15 dias dobra a chance de falhar", "modulo": "P1",
            "metodo": "Contrafactual no modelo: os mesmos equipamentos com a preventiva 30 dias atrasada e em dia",
            "descoberto": f"Preventiva atrasada 30 dias multiplica o risco previsto por {_fmt(r7)}",
            "efeito": round(r7, 2), "plantado": f"{_fmt(P.FATOR_ATRASO, 0)}× com atraso acima de {P.ATRASO_CRITICO_DIAS} dias",
            "veredito": _veredito(r7)})
        dias = list(range(-10, 46, 5))
        curvas["atraso"] = [{"dias": d, "risco": float(np.mean(modelo.prever(
            com_plano.assign(atraso_preventiva=float(d), dias_desde_preventiva=per + d))))} for d in dias]
    return itens, curvas


# ---------------------------------------------------------------- P2


def padroes_p2(modelo, linhas: pd.DataFrame) -> tuple[list[dict], dict]:
    itens, curvas = [], {}
    x = linhas.copy()
    x["previsto"] = modelo.prever(x)
    reg = x.groupby(["em", "regiao"], observed=True).agg(previsto=("previsto", "sum"), real=("ocorrencias", "sum"),
                                                         hora=("hora", "first"), dia=("dia_semana", "first"),
                                                         feriado=("feriado", "first")).reset_index()
    c = reg[reg.regiao == P.REGIAO_NOITE]
    noite = c.dia.isin(P.DIAS_NOITE) & c.hora.isin(list(P.HORAS_NOITE))
    resto = c.hora.isin(list(P.HORAS_NOITE)) & ~c.dia.isin(P.DIAS_NOITE)
    if noite.any() and resto.any():
        rm = c[noite].previsto.mean() / c[resto].previsto.mean()
        rr = c[noite].real.mean() / max(c[resto].real.mean(), 1e-9)
        itens.append({
            "padrao": 1, "titulo": "Centro: mais ocorrências sexta e sábado, 18 h às 23 h", "modulo": "P2",
            "metodo": "Previsões do modelo nas últimas 4 semanas: mesmas horas, sexta e sábado × demais dias",
            "descoberto": f"O modelo prevê {_fmt(rm)}× mais ocorrências no Centro nessas noites; nos dados, foram {_fmt(rr)}×",
            "efeito": round(float(rm), 2), "plantado": f"{_fmt(P.FATOR_NOITE)}× (perturbação {_fmt(P.FATOR_NOITE_PERTURBACAO)}×)",
            "veredito": _veredito(float(rm))})
        curvas["centro_por_hora"] = [{"hora": int(h), "previsto_sex_sab": float(g[g.dia.isin(P.DIAS_NOITE)].previsto.mean()),
                                      "real_sex_sab": float(g[g.dia.isin(P.DIAS_NOITE)].real.mean()),
                                      "previsto_outros": float(g[~g.dia.isin(P.DIAS_NOITE)].previsto.mean()),
                                      "real_outros": float(g[~g.dia.isin(P.DIAS_NOITE)].real.mean())}
                                     for h, g in c.groupby("hora")]

    util = reg[(reg.dia < 5) & ~reg.feriado.astype(bool) & reg.hora.between(6, 20)]
    pico = util.hora.isin(P.PICOS)
    if pico.any():
        rm = util[pico].previsto.mean() / util[~pico].previsto.mean()
        rr = util[pico].real.mean() / max(util[~pico].real.mean(), 1e-9)
        rush = x[(x.dia_semana < 5) & x.hora.isin(P.PICOS)]
        ves = _media(modelo, rush, vespera=True) / _media(modelo, rush, vespera=False) if len(rush) else None
        itens.append({
            "padrao": 8, "titulo": "Congestionamentos nos dias úteis, 7–9 h e 17–19 h, mais fortes em véspera de feriado",
            "modulo": "P2", "metodo": "Previsões do modelo nas horas de pico × demais horas do dia útil; contrafactual de véspera",
            "descoberto": (f"O modelo prevê {_fmt(rm)}× mais ocorrências nas horas de pico (nos dados, {_fmt(rr)}×)"
                           + (f"; véspera de feriado soma {_fmt((ves - 1) * 100, 0)}% nessas horas" if ves else "")),
            "efeito": round(float(rm), 2), "plantado": f"congestionamentos {_fmt(P.FATOR_PICO, 0)}× nas horas de pico, mais em véspera",
            "veredito": _veredito(float(rm))})

    seco = _media(modelo, x, chuva_mm=0.0)
    chuva = _media(modelo, x, chuva_mm=8.0)
    por_bairro = (x.assign(c=modelo.prever(x.assign(chuva_mm=8.0)), s=modelo.prever(x.assign(chuva_mm=0.0)))
                  .groupby("bairro", observed=True)[["c", "s"]].sum())
    por_bairro["extra"] = por_bairro.c - por_bairro.s
    top = por_bairro.sort_values("extra", ascending=False).head(5).index.astype(str).tolist()
    acertos = len(set(top) & set(P.BAIRROS_BAIXOS))
    itens.append({
        "padrao": 2, "titulo": "Chuva: mais acidentes e alagamentos em bairros baixos", "modulo": "P2",
        "metodo": "Contrafactual no modelo: as mesmas horas com 8 mm/h de chuva e secas",
        "descoberto": (f"Chuva de 8 mm/h aumenta as ocorrências previstas em {_fmt((chuva / seco - 1) * 100, 0)}%. "
                       f"Bairros que mais sobem: {', '.join(top)}"),
        "efeito": round(chuva / seco, 2),
        "plantado": f"acidentes {_fmt(P.FATOR_CHUVA_ACIDENTE)}×; alagamentos em {', '.join(P.BAIRROS_BAIXOS)}",
        "detalhe": f"{acertos} dos 4 bairros baixos plantados estão entre os 5 que mais sobem",
        "veredito": "encontrado" if chuva / seco >= FRACO and acertos >= 2 else _veredito(chuva / seco)})

    sem = _media(modelo, x, evento_publico=0.0, evento_dist_km=99.0)
    com = _media(modelo, x, evento_publico=30_000.0, evento_dist_km=0.5)
    itens.append({
        "padrao": 3, "titulo": "Eventos com mais de 10 mil pessoas: mais ocorrências num raio de 2 km", "modulo": "P2",
        "metodo": "Contrafactual no modelo: evento de 30 mil pessoas a 500 m × nenhum evento, por bairro e hora",
        "descoberto": f"Um evento de 30 mil pessoas acrescenta {_fmt(com - sem, 2)} ocorrências por hora em cada bairro próximo "
                      f"({_fmt((com / sem - 1) * 100, 0)}% a mais)",
        "efeito": round(com / sem, 2), "plantado": f"+{_fmt(P.EVENTO_POR_10MIL_HORA)} ocorrência por hora a cada 10 mil pessoas, "
                                                   f"de {P.HORAS_ANTES_DEPOIS} h antes a {P.HORAS_ANTES_DEPOIS} h depois",
        "veredito": _veredito(com / sem)})
    return itens, curvas


# ---------------------------------------------------------------- consultas (sem modelo próprio ainda)


def padroes_consulta(db: Session) -> list[dict]:
    itens = []
    try:
        ini, fim = verificacao.periodo(db)
    except Exception:
        return itens
    furtos = verificacao.p6_furtos(db, ini.to_pydatetime(), fim.to_pydatetime())
    itens.append({"padrao": 6, "titulo": "Furtos de equipamentos em dois bairros, de madrugada, longe de câmeras",
                  "modulo": "consulta", "metodo": "Consulta direta ao histórico (o modelo de risco de furto, P7, é da fase 12)",
                  "descoberto": f"{_fmt(furtos[0]['obtido'] * 100, 0)}% dos furtos em 2 de 28 bairros; neles, "
                                f"{_fmt(furtos[1]['obtido'] * 100, 0)}% entre 0 h e 5 h",
                  "efeito": None, "plantado": f"{', '.join(P.BAIRROS_FURTO)}, 0 h às 5 h, sem câmera a menos de {P.RAIO_CAMERA_M} m",
                  "veredito": "encontrado" if all(f["ok"] for f in furtos) else "fraco"})
    disp = verificacao.p11_regiao(db, ini.to_pydatetime(), fim.to_pydatetime())
    itens.append({"padrao": 11, "titulo": "Queda lenta de disponibilidade numa região sem preventiva", "modulo": "consulta",
                  "metodo": "Consulta direta à disponibilidade diária (a tendência P6 é da fase 12)",
                  "descoberto": disp["detalhe"].replace(".", ","), "efeito": None, "plantado": f"região {P.REGIAO_SEM_PREVENTIVA}",
                  "veredito": "encontrado" if disp["ok"] else "fraco"})
    plantadas = db.execute(text("SELECT valor FROM estado_preditivo WHERE chave = 'anomalias_plantadas'")).scalar() or []
    ids = {a["equipamento_id"] for a in plantadas}
    achadas = {i for (i,) in db.execute(text("""SELECT DISTINCT equipamento_id FROM alerta
                                                WHERE tipo::text = 'anomalia_equipamento' AND equipamento_id = ANY(:i)"""),
                                        {"i": list(ids)})} if ids else set()
    falsos = db.scalar(text("""SELECT count(DISTINCT equipamento_id) FROM alerta WHERE tipo::text = 'anomalia_equipamento'
                               AND NOT (equipamento_id = ANY(:i))"""), {"i": list(ids) or [0]})
    if ids:
        itens.append({"padrao": 12, "titulo": "Anomalias isoladas (radar que para de registrar, câmera que cai toda noite)",
                      "modulo": "P5", "metodo": "Alertas abertos pelos detectores de anomalia",
                      "descoberto": f"{len(achadas)} de {len(ids)} equipamentos com anomalia plantada foram apontados; "
                                    f"{falsos} outros equipamentos também",
                      "efeito": None, "plantado": f"{len(ids)} equipamentos", "veredito":
                          "encontrado" if len(achadas) == len(ids) else "fraco" if achadas else "nao_encontrado"})
    return itens


# ---------------------------------------------------------------- tudo, com cache


def _versoes(db: Session) -> str:
    return ",".join(v for (v,) in db.execute(text(
        "SELECT nome || ':' || versao FROM modelo_versao WHERE ativo AND nome IN "
        "('falha_equipamento_7d', 'ocorrencias_regiao_hora') ORDER BY nome")))


def calcular(db: Session, f: V.Fontes | None = None) -> dict:
    f = f or V.carregar(db)
    itens, curvas = [], {}
    _, m1 = artefatos.ativo(db, "falha_equipamento_7d")
    if m1 is not None:
        corte = V.corte_local(prever.hoje_local())
        eq = V.equipamentos(f, [corte], alvo=False)
        i1, c1 = padroes_p1(m1, eq)
        itens += i1
        curvas.update(c1)
    _, m2 = artefatos.ativo(db, "ocorrencias_regiao_hora")
    ate = db.scalar(text("SELECT valor->>'ate' FROM estado_preditivo WHERE chave = 'continuo'"))
    if m2 is not None and ate:
        fim = pd.Timestamp(ate).tz_convert("UTC").floor("h")
        origens = [fim - pd.Timedelta(days=d) for d in range(28, 0, -1)]
        linhas = V.bairro_hora(f, origens, horizonte=24, alvo=True)
        i2, c2 = padroes_p2(m2, linhas)
        itens += i2
        curvas.update(c2)
    itens += padroes_consulta(db)
    itens.sort(key=lambda i: i["padrao"])
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(), "versoes": _versoes(db), "padroes": itens, "curvas": curvas,
        "resumo": {v: sum(i["veredito"] == v for i in itens) for v in ("encontrado", "fraco", "nao_encontrado")},
        "aviso": ("Dados sintéticos: os padrões foram plantados de propósito no gerador e os modelos não leram essa "
                  "descrição. Encontrá-los mostra que o método funciona; numa cidade real, os padrões seriam outros."),
    }


def obter(db: Session, refazer: bool = False) -> dict:
    """Resultado em cache em `estado_preditivo`, refeito quando os modelos mudam."""
    from app.preditivo.backtest import json_limpo

    e = db.get(EstadoPreditivo, "padroes_descobertos")
    if e and not refazer and (e.valor or {}).get("versoes") == _versoes(db):
        return e.valor
    r = json_limpo(calcular(db))
    db.merge(EstadoPreditivo(chave="padroes_descobertos", valor=r))
    db.commit()
    return r
