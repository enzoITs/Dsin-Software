"""Parte 2: motor de interpretação, ciclo de vida dos alertas, índice das regiões e indicadores.

Cada regra de detecção dispara com o evento certo e não dispara sem ele.
"""

import math
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text, update

from app.db import SessionLocal
from app.domain import derivados, limites
from app.models import Alerta, Equipamento, PlanoManutencao
from app.models.enums import TipoAlerta
from app.services import central, motor, simulacao
from tests.conftest import RADAR

R = TipoAlerta
# Pontos dentro do bairro "Centro" do conftest, a mais de 500 m um do outro.
PONTOS_CENTRO = [(-46.640, -23.550), (-46.628, -23.545), (-46.646, -23.557), (-46.623, -23.557)]


def metros_para_lon(m: float, lat: float) -> float:
    return m / (111320 * math.cos(math.radians(lat)))


@pytest.fixture
def equip(client):
    """Cria equipamento com módulo IoT e situação operacional."""
    seq = {"n": 0}

    def criar(lon=-46.64, lat=-23.55, tipo_id=1, atributos=None, **extra):
        seq["n"] += 1
        n = seq["n"]
        body = {**RADAR, "numero_serie": f"T-{n:04d}", "dispositivo_iot_id": f"IOT-C-{n}", "tipo_id": tipo_id,
                "localizacao": {**RADAR["localizacao"], "lon": lon, "lat": lat}, **extra}
        if atributos is not None:
            body["atributos"] = atributos
        r = client.post("/equipamentos", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    return criar


CAMERA = {"resolucao": "1080p"}


def abertos(client, **params):
    return client.get("/alertas", params={"incluir_baixa": True, **params}).json()["itens"]


def sinal(client, disp, **kw):
    return client.post("/telemetria/sinal", json={"dispositivo_iot_id": disp, **kw})


def com_db(fn):
    with SessionLocal() as db:
        res = fn(db)
        db.commit()
        return res


# ---------- Etapa 2: dispositivo não cadastrado ----------


def test_dispositivo_desconhecido_abre_um_alerta_e_soma_repeticoes(client):
    assert sinal(client, "FANTASMA-1").status_code == 404
    assert sinal(client, "FANTASMA-1").status_code == 404
    a = abertos(client, tipo="dispositivo_nao_cadastrado")
    assert len(a) == 1
    assert a[0]["nivel"] == "media" and a[0]["contador"] == 2 and a[0]["dispositivo_iot_id"] == "FANTASMA-1"


# ---------- Furto ----------


def test_furto_por_deslocamento_maior_que_50m(client, equip):
    e = equip()
    lon0, lat0 = -46.64, -23.55
    sinal(client, e["dispositivo_iot_id"], tipo="posicao", lon=lon0 + metros_para_lon(30, lat0), lat=lat0)
    assert abertos(client, tipo="furto") == []  # 30 m: dentro da tolerância
    r = sinal(client, e["dispositivo_iot_id"], tipo="posicao", lon=lon0 + metros_para_lon(300, lat0), lat=lat0)
    assert r.status_code == 200 and r.json()["alertas"]
    a = abertos(client, tipo="furto")
    assert len(a) == 1 and a[0]["nivel"] == "critica" and "deslocado 300 m" in a[0]["mensagem"]
    # A situação não muda sozinha: alguém confirma o furto.
    assert client.get(f"/equipamentos/{e['id']}").json()["situacao"] == "operacional"
    # Voltou ao ponto: o problema sumiu sozinho
    sinal(client, e["dispositivo_iot_id"], tipo="posicao", lon=lon0, lat=lat0)
    assert abertos(client, tipo="furto") == []


def test_furto_pela_situacao_e_critico(client, equip):
    e = equip()
    client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "furtado", "motivo": "BO 123"})
    a = abertos(client, tipo="furto")
    assert len(a) == 1 and a[0]["nivel"] == "critica"


def test_limite_de_distancia_vem_da_configuracao(client, equip):
    r = client.put("/central/configuracao", json={"furto_distancia_m": 500})
    assert r.status_code == 200
    e = equip()
    sinal(client, e["dispositivo_iot_id"], tipo="posicao", lon=-46.64 + metros_para_lon(300, -23.55), lat=-23.55)
    assert abertos(client, tipo="furto") == []
    assert client.put("/central/configuracao", json={"nao_existe": 1}).status_code == 422
    op = client.put("/central/configuracao", json={"furto_distancia_m": 50}, headers={"X-Perfil": "operador", "X-Orgao-Id": "1"})
    assert op.status_code == 403


# ---------- Mau funcionamento e criticidade pelo contexto ----------


def test_erro_do_dispositivo_sem_cobertura_sobe_um_nivel(client, equip):
    e = equip()
    sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-17"})
    a = abertos(client, tipo="mau_funcionamento")
    assert len(a) == 1
    assert a[0]["nivel_inicial"] == "alta" and a[0]["nivel"] == "critica"
    assert a[0]["motivos_nivel"] == ["Alta → Crítica: sem outro radar operacional em 500 m"]
    assert "E-17" in a[0]["mensagem"]


def test_erro_com_outro_radar_perto_fica_alta(client, equip):
    e = equip()
    equip(lon=-46.64 + metros_para_lon(200, -23.55), lat=-23.55)
    sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-17"})
    a = abertos(client, tipo="mau_funcionamento")
    assert a[0]["nivel"] == "alta" and a[0]["motivos_nivel"] == []


def test_um_alerta_por_equipamento_e_regra(client, equip):
    e = equip()
    for _ in range(3):
        sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-17"})
    a = abertos(client, tipo="mau_funcionamento")
    assert len(a) == 1 and a[0]["contador"] == 3


def test_mudanca_para_mau_funcionamento_gera_alerta_e_voltar_resolve(client, equip):
    e = equip()
    client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "mau_funcionamento", "motivo": "lente quebrada"})
    assert len(abertos(client, tipo="mau_funcionamento")) == 1
    client.post(f"/equipamentos/{e['id']}/registros-manutencao", json={"tecnico": "Ana", "resultado": "concluida"})
    assert abertos(client, tipo="mau_funcionamento") == []


def test_regiao_em_atencao_sobe_nivel(client, equip):
    a1 = equip(*PONTOS_CENTRO[0])
    a2 = equip(*PONTOS_CENTRO[1])
    client.patch(f"/equipamentos/{a1['id']}/situacao", json={"situacao": "furtado", "motivo": "BO 123"})  # Centro: -25 -> atenção
    sinal(client, a2["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-1"})
    a = abertos(client, tipo="mau_funcionamento")[0]
    assert any("região Centro já em atenção" in m for m in a["motivos_nivel"])


# ---------- Manutenção planejada suprime; desativado não gera ----------


def test_manutencao_planejada_em_andamento_suprime_alerta(client, equip):
    e = equip()
    r = client.post(f"/equipamentos/{e['id']}/planos-manutencao",
                    json={"tipo": "agendada", "proxima_data": central.local(datetime.now(timezone.utc), limites.PADRAO).date().isoformat()})
    assert r.status_code == 201
    sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-17"})
    assert abertos(client, tipo="mau_funcionamento") == []
    sinal(client, e["dispositivo_iot_id"], tipo="posicao", lon=-46.63, lat=-23.55)  # furto nunca é suprimido
    assert len(abertos(client, tipo="furto")) == 1


def test_desativado_nao_gera_alerta_e_resolve_os_abertos(client, equip):
    e = equip()
    sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-17"})
    assert abertos(client, tipo="mau_funcionamento")
    client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "desativado", "motivo": "fim da vida útil"})
    assert abertos(client, equipamento_id=e["id"]) == []
    sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-17"})
    assert abertos(client, tipo="mau_funcionamento") == []


# ---------- Falha silenciosa: 3 vezes o intervalo ----------


def _silenciar(eid: int, minutos: float):
    def f(db):
        db.execute(update(Equipamento).where(Equipamento.id == eid)
                   .values(ultimo_sinal_em=datetime.now(timezone.utc) - timedelta(minutes=minutos)))
        return motor.verificar_equipamentos(db, [eid])
    return com_db(f)


def test_falha_silenciosa_so_depois_de_3_vezes_o_intervalo(client, equip):
    e = equip()  # radar: intervalo de 15 min
    _silenciar(e["id"], 40)
    assert abertos(client, tipo="falha_silenciosa") == []
    _silenciar(e["id"], 46)
    a = abertos(client, tipo="falha_silenciosa")
    assert len(a) == 1 and a[0]["nivel_inicial"] == "alta"
    sinal(client, e["dispositivo_iot_id"])
    assert abertos(client, tipo="falha_silenciosa") == []
    assert client.get("/alertas", params={"abertos": False, "tipo": "falha_silenciosa"}).json()["itens"][0]["resolucao"] == "Sinal voltou"


# ---------- Sinal degradado ----------


def test_metrica_fora_da_faixa_e_volta(client, equip):
    e = equip(tipo_id=2, atributos=CAMERA)  # câmera
    sinal(client, e["dispositivo_iot_id"], tipo="metrica", valores={"qualidade": 80})
    assert abertos(client, tipo="sinal_degradado") == []
    sinal(client, e["dispositivo_iot_id"], tipo="metrica", valores={"qualidade": 40})
    a = abertos(client, tipo="sinal_degradado")
    assert len(a) == 1 and a[0]["nivel_inicial"] == "media"
    sinal(client, e["dispositivo_iot_id"], tipo="metrica", valores={"qualidade": 92})
    assert abertos(client, tipo="sinal_degradado") == []


def test_bateria_do_patinete_abaixo_de_15(client, equip):
    e = equip(tipo_id=7, atributos={"uso": "compartilhado"})
    sinal(client, e["dispositivo_iot_id"], tipo="metrica", valores={"bateria": 16})
    assert abertos(client, tipo="sinal_degradado") == []
    sinal(client, e["dispositivo_iot_id"], tipo="metrica", valores={"bateria": 12})
    assert len(abertos(client, tipo="sinal_degradado")) == 1


# ---------- Incidente correlacionado ----------


def test_tres_problemas_na_regiao_viram_um_incidente(client, equip):
    eqs = [equip(*p) for p in PONTOS_CENTRO[:2]]
    for e in eqs:
        sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-9"})
    assert abertos(client, tipo="incidente_correlacionado") == []  # 2 ainda não é incidente
    e3 = equip(*PONTOS_CENTRO[2])
    sinal(client, e3["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-9"})
    inc = abertos(client, tipo="incidente_correlacionado")
    assert len(inc) == 1 and inc[0]["nivel"] == "critica" and inc[0]["regiao"] == "Centro"
    agrupados = client.get("/alertas", params={"agrupar": True}).json()["itens"]
    assert [a["regra"] for a in agrupados] == ["incidente_correlacionado"]  # os membros ficam dentro
    detalhe = client.get(f"/alertas/{inc[0]['id']}").json()
    assert len(detalhe["lista_membros"]) == 3
    # Encerrar o incidente encerra os equipamentos dentro dele
    client.patch(f"/alertas/{inc[0]['id']}", json={"acao": "resolver", "motivo": "energia voltou"})
    assert abertos(client) == []


def test_problemas_antigos_nao_correlacionam(client, equip):
    eqs = [equip(*p) for p in PONTOS_CENTRO[:3]]
    for e in eqs[:2]:
        sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-9"})
    com_db(lambda db: db.execute(update(Alerta).values(criado_em=Alerta.criado_em - timedelta(minutes=20))))
    sinal(client, eqs[2]["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-9"})
    assert abertos(client, tipo="incidente_correlacionado") == []


# ---------- Ciclo de vida ----------


def test_ciclo_de_vida_reconhecer_silenciar_atribuir_os_resolver(client, equip):
    e = equip()
    sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-17"})
    a = abertos(client, tipo="mau_funcionamento")[0]
    assert a["estado"] == "aberto"
    r = client.patch(f"/alertas/{a['id']}", json={"acao": "reconhecer"})
    assert r.json()["estado"] == "reconhecido" and r.json()["reconhecido_em"]
    assert client.patch(f"/alertas/{a['id']}", json={"acao": "silenciar", "minutos": 10}).status_code == 422  # sem motivo
    assert client.patch(f"/alertas/{a['id']}", json={"acao": "silenciar", "motivo": "x", "minutos": 45}).status_code == 422
    r = client.patch(f"/alertas/{a['id']}", json={"acao": "silenciar", "motivo": "equipe já no local", "minutos": 30})
    assert r.status_code == 200 and r.json()["silenciado_ate"]

    ag = client.post("/agentes", json={"nome": "Ana Souza", "matricula": "CET9001", "categoria": "agente_transito", "orgao_id": 1}).json()
    r = client.post(f"/alertas/{a['id']}/atribuir", json={"agente_id": ag["id"]})
    assert r.status_code == 200 and r.json()["estado"] == "em_atendimento" and r.json()["agente"]["id"] == ag["id"]
    r = client.post(f"/alertas/{a['id']}/ordem-servico", json={})
    assert r.status_code == 200 and r.json()["ordem_servico_id"]
    assert client.post(f"/alertas/{a['id']}/ordem-servico", json={}).status_code == 409
    r = client.patch(f"/alertas/{a['id']}", json={"acao": "resolver", "motivo": "trocado o módulo"})
    assert r.json()["estado"] == "resolvido" and r.json()["resolucao"] == "trocado o módulo"
    assert client.patch(f"/alertas/{a['id']}", json={"acao": "reconhecer"}).status_code == 422


def test_operador_nao_age_em_alerta_de_outro_orgao(client, equip):
    e = equip()  # órgão 1
    sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-17"})
    a = abertos(client, tipo="mau_funcionamento")[0]
    r = client.patch(f"/alertas/{a['id']}", json={"acao": "reconhecer"}, headers={"X-Perfil": "operador", "X-Orgao-Id": "2"})
    assert r.status_code == 403


def test_escalonamento(client, equip):
    e = equip()
    equip(lon=-46.64 + metros_para_lon(200, -23.55), lat=-23.55)  # cobertura: alerta fica alta
    sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-17"})
    a = abertos(client, tipo="mau_funcionamento")[0]
    assert a["nivel"] == "alta"
    agora = datetime.now(timezone.utc)
    com_db(lambda db: motor.escalonar(db, agora + timedelta(minutes=9)))
    assert abertos(client, tipo="mau_funcionamento")[0]["nivel"] == "alta"
    com_db(lambda db: motor.escalonar(db, agora + timedelta(minutes=11)))
    a = abertos(client, tipo="mau_funcionamento")[0]
    assert a["nivel"] == "critica" and a["motivos_nivel"][-1] == "Alta → Crítica: não reconhecido em 10 min"
    # Crítico não reconhecido volta a tocar a cada 2 minutos
    st = com_db(lambda db: motor.escalonar(db, agora + timedelta(minutes=14)))
    assert st["tocados"] == 1
    # Reconhecido não escala nem toca
    client.patch(f"/alertas/{a['id']}", json={"acao": "reconhecer"})
    st = com_db(lambda db: motor.escalonar(db, agora + timedelta(minutes=30)))
    assert st == {"tocados": 0, "escalonados": 0}


# ---------- Agentes ----------


def _agente(client, nome, matricula, orgao_id=1, lon=None, lat=None):
    ag = client.post("/agentes", json={"nome": nome, "matricula": matricula, "categoria": "agente_transito", "orgao_id": orgao_id}).json()
    if lon is not None:
        client.post("/telemetria/agentes", json=[{"agente_id": ag["id"], "lon": lon, "lat": lat}])
    return ag


def test_agentes_mais_proximos_do_alerta(client, equip):
    e = equip()
    longe = _agente(client, "Agente Longe", "CET1", lon=-46.60, lat=-23.55)
    perto = _agente(client, "Agente Perto", "CET2", lon=-46.641, lat=-23.551)
    medio = _agente(client, "Agente Médio", "CET3", lon=-46.63, lat=-23.55)
    _agente(client, "Sem posição", "CET4")
    sinal(client, e["dispositivo_iot_id"], tipo="erro", valores={"codigo": "E-17"})
    a = abertos(client, tipo="mau_funcionamento")[0]
    prox = client.get(f"/alertas/{a['id']}/agentes-proximos").json()
    assert [p["id"] for p in prox] == [perto["id"], medio["id"], longe["id"]]
    assert prox[0]["distancia_m"] < 200


def test_regiao_descoberta_e_agente_sem_posicao(client):
    com_db(lambda db: motor.verificar_agentes(db, datetime.now(timezone.utc), {}))
    regs = {a["regiao"] for a in abertos(client, tipo="regiao_descoberta")}
    assert regs == {"Centro", "Oeste"}
    ag = _agente(client, "Ana", "CET7")  # em atividade, sem posição
    com_db(lambda db: motor.verificar_agentes(db, datetime.now(timezone.utc), {}))
    assert [a["agente_alvo_id"] for a in abertos(client, tipo="agente_sem_posicao")] == [ag["id"]]
    client.post("/telemetria/agentes", json=[{"agente_id": ag["id"], "lon": -46.64, "lat": -23.55}])
    assert abertos(client, tipo="agente_sem_posicao") == []
    com_db(lambda db: motor.verificar_agentes(db, datetime.now(timezone.utc), {}))
    assert {a["regiao"] for a in abertos(client, tipo="regiao_descoberta")} == {"Oeste"}


# ---------- Manutenção vencida e próxima ----------


def test_manutencao_vencida_e_proxima(client, equip):
    e = equip()
    with SessionLocal() as db:
        db.execute(update(PlanoManutencao).where(PlanoManutencao.equipamento_id == e["id"])
                   .values(proxima_data=date.today() - timedelta(days=3)))
        derivados.recalcular(db, [e["id"]])
        db.commit()
    a = abertos(client, tipo="manutencao_vencida")
    assert len(a) == 1 and a[0]["nivel"] == "media"
    with SessionLocal() as db:
        db.execute(update(PlanoManutencao).where(PlanoManutencao.equipamento_id == e["id"])
                   .values(proxima_data=date.today() + timedelta(days=5)))
        derivados.recalcular(db, [e["id"]])
        db.commit()
    assert abertos(client, tipo="manutencao_vencida") == []
    assert len(abertos(client, tipo="manutencao_proxima")) == 1
    # Baixa não aparece na lista principal
    assert client.get("/alertas").json()["total"] == 0
    fila = client.get("/manutencao/fila").json()
    assert fila["totais"]["proxima"] == 1 and fila["itens"][0]["codigo_interno"] == e["codigo_interno"]


# ---------- Índice das regiões e indicadores ----------


def test_indice_da_regiao_com_motivo(client, equip):
    e = equip()
    _agente(client, "Ana", "CET1", lon=-46.64, lat=-23.55)
    _agente(client, "Bia", "CET2", lon=-46.70, lat=-23.56)
    client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "furtado", "motivo": "BO 123"})
    regs = {r["regiao"]: r for r in client.get("/regioes/saude").json()}
    centro = regs["Centro"]
    # 1 crítico (-25); disponibilidade 0% (só um radar, furtado: -90)
    assert centro["alertas"]["critica"] == 1
    assert centro["nota"] == 0 and centro["estado"] == "critica"
    assert "1 radar furtado" in centro["motivo"]
    assert regs["Oeste"]["nota"] == 100
    # Reconhecido sai da conta do índice (alguém está cuidando)
    a = abertos(client, tipo="furto")[0]
    client.patch(f"/alertas/{a['id']}", json={"acao": "reconhecer"})
    centro = {r["regiao"]: r for r in client.get("/regioes/saude").json()}["Centro"]
    assert centro["alertas"]["critica"] == 0


def test_indicadores_batem_com_contagem_no_banco(client, equip):
    eqs = [equip(*p) for p in PONTOS_CENTRO]
    cam = equip(-46.70, -23.565, tipo_id=2, atributos=CAMERA)  # Pinheiros, região Oeste
    client.patch(f"/equipamentos/{eqs[0]['id']}/situacao", json={"situacao": "furtado", "motivo": "BO 123"})
    client.patch(f"/equipamentos/{eqs[1]['id']}/situacao", json={"situacao": "mau_funcionamento", "motivo": "teste"})
    client.patch(f"/equipamentos/{eqs[2]['id']}/situacao", json={"situacao": "desativado", "motivo": "teste"})
    _silenciar(cam["id"], 60)

    def banco(sql):
        with SessionLocal() as db:
            return db.execute(text(sql)).scalar()

    v = client.get("/indicadores").json()["valores"]
    assert v["total"] == banco("select count(*) from equipamento") == 5
    assert v["operacionais"] == banco("select count(*) from equipamento where situacao='operacional'") == 2
    assert v["indisponiveis"] == 2
    assert v["disponibilidade"] == 50.0  # 2 / (2 + 1 + 1); desativado fora da conta
    assert v["sem_sinal"] == 1
    assert v["alertas"]["critica"] == banco("select count(*) from alerta where resolvido_em is null and nivel='critica'")

    oeste = client.get("/indicadores", params={"regiao": "Oeste"}).json()["valores"]
    assert oeste["total"] == banco("select count(*) from localizacao where regiao='Oeste'") == 1
    # câmera sem outra por perto: o silêncio sobe de alta para crítica
    assert oeste["sem_sinal"] == 1 and oeste["alertas"]["alta"] + oeste["alertas"]["critica"] == 1
    cams = client.get("/indicadores", params={"tipo_id": 2}).json()["valores"]
    assert cams["total"] == 1 and sum(cams["alertas"].values()) == 1  # só o alerta da câmera, não o do radar
    # Mesmo cálculo de disponibilidade da Parte 1
    p1 = client.get("/indicadores/disponibilidade").json()["geral"]["disponibilidade"]
    assert round(p1 * 100, 2) == v["disponibilidade"]


def test_estado_do_mapa_respeita_filtros_e_cor_da_pior_situacao(client, equip):
    e1 = equip()
    e2 = equip(-46.70, -23.565, tipo_id=2, atributos=CAMERA)
    sinal(client, e1["dispositivo_iot_id"], tipo="posicao", lon=-46.63, lat=-23.55)  # furto: crítico
    est = client.get("/central/estado").json()
    props = {f["properties"]["i"]: f["properties"] for f in est["equipamentos"]["features"]}
    assert props[e1["id"]]["g"] == 4 and props[e1["id"]]["s"] == "operacional"  # cor do alerta, não só da situação
    assert props[e1["id"]]["f"] == "c" and props[e2["id"]]["f"] == "q"  # forma: fiscalização x monitoramento
    so_oeste = client.get("/central/estado", params={"regiao": "Oeste"}).json()
    assert [f["properties"]["i"] for f in so_oeste["equipamentos"]["features"]] == [e2["id"]]
    area = "-46.66 -23.56,-46.62 -23.56,-46.62 -23.54,-46.66 -23.54"
    na_area = client.get("/central/estado", params={"area": area}).json()
    assert [f["properties"]["i"] for f in na_area["equipamentos"]["features"]] == [e1["id"]]
    critico = client.get("/central/estado", params={"nivel": "critica"}).json()
    assert [f["properties"]["i"] for f in critico["equipamentos"]["features"]] == [e1["id"]]


# ---------- Linha do tempo, resumo, pergunta ----------


def test_linha_do_tempo_mostra_situacao_anterior(client, equip):
    e = equip()
    com_db(lambda db: db.execute(text("ALTER TABLE historico_situacao DISABLE TRIGGER tg_historico_somente_insercao")))
    com_db(lambda db: db.execute(text("UPDATE historico_situacao SET em = em - interval '30 minutes'")))
    com_db(lambda db: db.execute(update(Equipamento).values(criado_em=Equipamento.criado_em - timedelta(minutes=30))))
    com_db(lambda db: db.execute(text("ALTER TABLE historico_situacao ENABLE TRIGGER tg_historico_somente_insercao")))
    client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "furtado", "motivo": "BO 123"})
    agora = client.get("/linha-do-tempo", params={"minutos_atras": 0}).json()
    assert agora["equipamentos"] == []
    antes = client.get("/linha-do-tempo", params={"minutos_atras": 10}).json()
    assert antes["equipamentos"] == [{"i": e["id"], "s": "operacional"}]
    assert antes["indicadores"]["operacionais"] == 1 and antes["indicadores"]["disponibilidade"] == 100.0
    assert antes["alertas"] == []


def test_resumo_do_turno_sem_ia_usa_modelo_de_texto(client, equip):
    e = equip()
    client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "furtado", "motivo": "BO 123"})
    r = client.get("/resumo-turno").json()
    assert r["fonte"] == "modelo"
    assert "1 radar furtado no Centro" in r["texto"]


def test_perguntar_ao_painel_acha_a_regiao(client, equip):
    e = equip()
    client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "furtado", "motivo": "BO 123"})
    r = client.get("/central/perguntar", params={"q": "O que está acontecendo no Centro?"}).json()
    assert r["regiao"] == "Centro" and r["fonte"] == "modelo"
    assert "radar furtado" in r["texto"]
    r = client.get("/central/perguntar", params={"q": "e em Pinheiros?"}).json()
    assert r["regiao"] == "Oeste" and r["bairro"] == "Pinheiros"


# ---------- Simulação ----------


@pytest.fixture
def estado_simulacao(tmp_path, monkeypatch):
    monkeypatch.setattr(simulacao, "ARQUIVO", tmp_path / "simulacao.json")


def test_simular_queda_de_energia_e_restaurar(client, equip, estado_simulacao):
    for p in PONTOS_CENTRO:
        equip(*p)
    r = client.post("/simulacao/incidente", json={"tipo": "queda_energia", "regiao": "Centro", "quantidade": 3})
    assert r.status_code == 200, r.text
    regras_ = {a["regra"] for a in r.json()["alertas"]}
    assert regras_ == {"falha_silenciosa", "incidente_correlacionado"}
    assert all(a["simulado"] for a in r.json()["alertas"])
    # O simulador real descarta o equipamento parado; um lote em trânsito também é descartado
    parado = r.json()["afetados"][0]
    disp = client.get(f"/equipamentos/codigo/{parado}").json()["dispositivo_iot_id"]
    client.post("/telemetria/sinais", json=[{"dispositivo_iot_id": disp}])
    assert len(abertos(client, tipo="falha_silenciosa")) == 3
    r = client.post("/simulacao/restaurar")
    assert r.status_code == 200
    assert abertos(client) == []


def test_simular_furto_passa_pelo_motor(client, equip, estado_simulacao):
    e = equip()
    r = client.post("/simulacao/incidente", json={"tipo": "furto", "regiao": "Centro"})
    assert r.status_code == 200
    a = abertos(client, tipo="furto")
    assert len(a) == 1 and a[0]["equipamento_id"] == e["id"] and "deslocado" in a[0]["mensagem"]
    client.post("/simulacao/restaurar")
    assert abertos(client, tipo="furto") == []
    assert client.post("/simulacao/incidente", json={"tipo": "furto", "regiao": "Atlântida"}).status_code == 422
