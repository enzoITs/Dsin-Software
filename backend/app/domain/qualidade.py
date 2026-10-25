"""Qualidade do inventário: completude dos cadastros e problemas encontrados, por órgão.

Transforma qualidade de dados em métrica de gestão: cada órgão vê o quanto do seu
cadastro está completo e a lista do que precisa corrigir.
"""

import re
from collections import defaultdict

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from app.models import Bairro, Cidade, Equipamento, Localizacao, Orgao, TipoEquipamento

DISTANCIA_SUSPEITA_KM = 60
EXEMPLOS = 8


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def avaliar(db: Session, orgao_id: int | None = None) -> dict:
    filtro_orgao = (Equipamento.orgao_id == orgao_id) if orgao_id else true()

    linhas = db.execute(
        select(
            Equipamento.id, Equipamento.codigo_interno, Equipamento.orgao_id, Equipamento.tipo_id,
            Equipamento.atributos, Equipamento.dispositivo_iot_id, Equipamento.data_instalacao,
            Equipamento.marca, Equipamento.numero_serie,
            Localizacao.equipamento_id.is_not(None).label("tem_loc"),
            Localizacao.geom.is_not(None).label("tem_geom"),
            Localizacao.cep, Localizacao.bairro_id, Localizacao.referencia,
            Cidade.tem_lista_bairros,
        )
        .outerjoin(Localizacao, Localizacao.equipamento_id == Equipamento.id)
        .outerjoin(Cidade, Cidade.id == Localizacao.cidade_id)
        .where(filtro_orgao)
    ).all()
    schemas = {t.id: t.schema_atributos for t in db.scalars(select(TipoEquipamento))}
    orgaos = {o.id: o for o in db.scalars(select(Orgao))}

    problemas: dict[str, dict] = {}

    def registrar(codigo: str, titulo: str, correcao: str, eid: int, cod: str, detalhe: str = ""):
        p = problemas.setdefault(codigo, {"codigo": codigo, "titulo": titulo, "correcao": correcao, "quantidade": 0, "exemplos": [], "_ids": set()})
        p["quantidade"] += 1
        p["_ids"].add(eid)
        if len(p["exemplos"]) < EXEMPLOS:
            p["exemplos"].append({"equipamento_id": eid, "codigo_interno": cod, "detalhe": detalhe})

    por_orgao = defaultdict(lambda: {"equipamentos": 0, "soma_completude": 0.0, "com_problema": set()})
    campos_vazios: dict[str, int] = defaultdict(int)

    for l in linhas:
        props = (schemas.get(l.tipo_id) or {}).get("properties", {})
        attrs = l.atributos or {}
        checks = {
            "módulo IoT": bool(l.dispositivo_iot_id),
            "data de instalação": l.data_instalacao is not None,
            "coordenadas": bool(l.tem_geom),
            "CEP": bool(l.cep),
            "referência": bool(l.referencia),
        }
        if l.tem_lista_bairros:
            checks["bairro"] = l.bairro_id is not None
        obrigatorios = set((schemas.get(l.tipo_id) or {}).get("required", []))
        for k, p in props.items():
            if k in obrigatorios:
                checks[p.get("title", k)] = attrs.get(k) not in (None, "", [])
        preenchidos = sum(checks.values())
        completude = preenchidos / len(checks)
        for nome, ok in checks.items():
            if not ok:
                campos_vazios[nome] += 1
        o = por_orgao[l.orgao_id]
        o["equipamentos"] += 1
        o["soma_completude"] += completude

        if not l.tem_geom:
            registrar("sem_coordenadas", "Sem coordenadas", "Marque o ponto no mapa para o equipamento aparecer na Central de Operações.", l.id, l.codigo_interno)
        if l.tem_lista_bairros and l.bairro_id is None:
            registrar("sem_bairro", "Sem bairro", "Abra o cadastro e salve: o bairro é sugerido pelo ponto no mapa.", l.id, l.codigo_interno)
        if not l.dispositivo_iot_id:
            registrar("sem_iot", "Sem módulo IoT", "Sem o ID do módulo o PROMETHEUS não sabe de quem é o sinal.", l.id, l.codigo_interno)

    # Mesmo número de série escrito de formas diferentes.
    grupos: dict[str, list] = defaultdict(list)
    for l in linhas:
        grupos[_norm(l.numero_serie)].append(l)
    for serie, itens in grupos.items():
        if len(itens) > 1:
            cods = ", ".join(i.codigo_interno for i in itens)
            for i in itens:
                registrar("duplicidade", "Possível duplicidade", "Mesmo número de série em mais de um cadastro. Mantenha um e desative os demais.",
                          i.id, i.codigo_interno, f"série {i.numero_serie} ({i.marca.strip()}) também em {cods}")

    # Marca escrita de formas diferentes ("PERKONS " e "Perkons").
    variantes: dict[str, set[str]] = defaultdict(set)
    contagem_marca: dict[str, int] = defaultdict(int)
    for l in linhas:
        variantes[_norm(l.marca)].add(l.marca)
        contagem_marca[l.marca] += 1
    for _, formas in variantes.items():
        if len(formas) > 1:
            padrao = max(formas, key=lambda f: contagem_marca[f])
            for l in linhas:
                if l.marca in formas and l.marca != padrao:
                    registrar("marca_variante", "Marca escrita de outro jeito", "Padronize o nome da marca para o mais usado.", l.id, l.codigo_interno, f"\"{l.marca}\" → \"{padrao}\"")

    # Coordenadas longe da cidade e bairro divergente do ponto (PostGIS).
    longe = db.execute(
        select(Equipamento.id, Equipamento.codigo_interno, Cidade.nome,
               (func.ST_DistanceSphere(Localizacao.geom, Cidade.centro) / 1000).label("km"))
        .join(Localizacao, Localizacao.equipamento_id == Equipamento.id)
        .join(Cidade, Cidade.id == Localizacao.cidade_id)
        .where(filtro_orgao, Localizacao.geom.is_not(None), Cidade.centro.is_not(None),
               func.ST_DistanceSphere(Localizacao.geom, Cidade.centro) > DISTANCIA_SUSPEITA_KM * 1000)
    ).all()
    for eid, cod, cidade, km in longe:
        registrar("coordenada_suspeita", "Coordenada suspeita", "Confira o ponto no mapa ou a cidade informada.", eid, cod, f"{km:.0f} km do centro de {cidade}")

    divergentes = db.execute(
        select(Equipamento.id, Equipamento.codigo_interno, Bairro.nome)
        .join(Localizacao, Localizacao.equipamento_id == Equipamento.id)
        .join(Bairro, Bairro.id == Localizacao.bairro_id)
        .where(filtro_orgao, Localizacao.geom.is_not(None), Bairro.geom.is_not(None),
               ~func.ST_Contains(Bairro.geom, Localizacao.geom))
    ).all()
    for eid, cod, bairro in divergentes:
        registrar("bairro_divergente", "Bairro diferente do ponto no mapa", "O bairro informado não contém o ponto. Corrija um dos dois.", eid, cod, f"informado: {bairro}")

    iguais = db.execute(
        select(func.array_agg(Equipamento.id), func.array_agg(Equipamento.codigo_interno))
        .join(Localizacao, Localizacao.equipamento_id == Equipamento.id)
        .join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
        .where(filtro_orgao, Localizacao.geom.is_not(None), TipoEquipamento.mobilidade == "fixo")
        .group_by(Localizacao.geom, Equipamento.tipo_id)
        .having(func.count() > 1)
    ).all()
    for ids, cods in iguais:
        for eid, cod in zip(ids, cods):
            registrar("coordenadas_iguais", "Mesmo ponto de outro equipamento do mesmo tipo", "Pode ser cadastro repetido ou ponto copiado.", eid, cod, ", ".join(cods))

    ids_por_orgao = {l.id: l.orgao_id for l in linhas}
    for p in problemas.values():
        for eid in p.pop("_ids"):
            if eid in ids_por_orgao:
                por_orgao[ids_por_orgao[eid]]["com_problema"].add(eid)

    ranking = []
    for oid, o in por_orgao.items():
        n = o["equipamentos"]
        compl = o["soma_completude"] / n if n else 0
        pct_prob = len(o["com_problema"]) / n if n else 0
        ranking.append({
            "orgao_id": oid, "sigla": orgaos[oid].sigla, "nome": orgaos[oid].nome, "equipamentos": n,
            "completude": round(compl, 4), "com_problema": len(o["com_problema"]),
            "percentual_com_problema": round(pct_prob, 4),
            # Nota de 0 a 100: completude pesa 70%, cadastros sem problema 30%.
            "nota": round(100 * (0.7 * compl + 0.3 * (1 - pct_prob)), 1),
        })
    ranking.sort(key=lambda r: -r["nota"])

    total = len(linhas)
    soma = sum(o["soma_completude"] for o in por_orgao.values())
    return {
        "total_equipamentos": total,
        "completude_geral": round(soma / total, 4) if total else None,
        "equipamentos_com_problema": sum(len(o["com_problema"]) for o in por_orgao.values()),
        "problemas": sorted(problemas.values(), key=lambda p: -p["quantidade"]),
        "campos_mais_vazios": [{"campo": k, "vazios": v} for k, v in sorted(campos_vazios.items(), key=lambda kv: -kv[1])[:8]],
        "ranking": ranking,
    }
