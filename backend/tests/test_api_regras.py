"""Regras que os jurados vão tentar quebrar, testadas pela API."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text, update

from app.db import SessionLocal, engine
from app.domain import derivados
from app.models import Equipamento, PlanoManutencao
from tests.conftest import RADAR


def mudar(client, eid, situacao, motivo="teste de regra"):
    return client.patch(f"/equipamentos/{eid}/situacao", json={"situacao": situacao, "motivo": motivo})


# ---------- Máquina de estados ----------


def test_transicao_recusada_pela_api(client, radar):
    e = radar()
    r = mudar(client, e["id"], "nao_instalado")
    assert r.status_code == 422
    assert r.json()["detail"]["codigo"] == "transicao_invalida"


def test_mudanca_exige_motivo(client, radar):
    e = radar()
    r = client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "em_manutencao", "motivo": ""})
    assert r.status_code == 422


def test_toda_mudanca_grava_historico_com_responsavel(client, radar):
    e = radar()
    client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "em_manutencao", "motivo": "preventiva"},
                 headers={"X-Usuario": "Maria"})
    hist = client.get(f"/equipamentos/{e['id']}/historico").json()
    assert hist[0]["situacao_nova"] == "em_manutencao"
    assert hist[0]["usuario"] == "Maria"
    assert hist[0]["motivo"] == "preventiva"
    assert hist[1]["situacao_anterior"] == "nao_instalado"  # cadastro já instalado


def test_historico_somente_insercao(client, radar):
    radar()
    with pytest.raises(Exception, match="somente insercao"):
        with engine.begin() as c:
            c.execute(text("UPDATE historico_situacao SET motivo = 'adulterado'"))
    with pytest.raises(Exception, match="somente insercao"):
        with engine.begin() as c:
            c.execute(text("DELETE FROM historico_situacao"))


# ---------- Automações ----------


def test_mau_funcionamento_abre_manutencao_os_e_reduz_score(client, radar):
    e = radar()
    r = mudar(client, e["id"], "mau_funcionamento", "lente quebrada")
    assert r.status_code == 200
    corpo = r.json()
    assert {"plano_manutencao_imediata_criado", "ordem_servico_aberta"} <= set(corpo["acoes"])
    assert corpo["equipamento"]["score_saude"] < e["score_saude"]
    assert any(m["chave"] == "falhas_90d" for m in corpo["equipamento"]["score_motivos"])
    planos = client.get(f"/equipamentos/{e['id']}/planos-manutencao").json()
    assert any(p["tipo"] == "imediata" and p["ativo"] for p in planos)
    ordens = client.get(f"/equipamentos/{e['id']}/ordens-servico").json()
    assert ordens[0]["status"] == "aberta" and ordens[0]["prioridade"] == "alta"


def test_furto_gera_alerta_critico_e_recuperacao_resolve(client, radar):
    e = radar()
    mudar(client, e["id"], "furtado", "não encontrado no local")
    alertas = client.get("/alertas", params={"tipo": "furto"}).json()["itens"]
    assert len(alertas) == 1 and alertas[0]["severidade"] == "critico"
    mudar(client, e["id"], "em_manutencao", "recuperado")
    assert client.get("/alertas", params={"tipo": "furto"}).json()["total"] == 0


def test_desativado_suspende_planos_e_sai_da_disponibilidade(client, radar):
    a = radar()
    b = radar(numero_serie="PK-0002", dispositivo_iot_id="IOT-TESTE-2")
    antes = client.get("/indicadores/disponibilidade").json()["geral"]
    assert antes["disponiveis"] == 2
    mudar(client, b["id"], "desativado", "fim da vida útil")
    planos = client.get(f"/equipamentos/{b['id']}/planos-manutencao").json()
    assert planos and not any(p["ativo"] for p in planos)
    depois = client.get("/indicadores/disponibilidade").json()["geral"]
    assert depois["disponibilidade"] == 1.0 and depois["fora_da_conta"] == 1
    assert a["id"] != b["id"]


def test_registro_concluido_volta_a_operacional_e_recalcula_periodico(client, radar):
    e = radar()
    mudar(client, e["id"], "mau_funcionamento", "sem leitura")
    r = client.post(f"/equipamentos/{e['id']}/registros-manutencao", json={"tecnico": "João", "descricao": "troca da lente"})
    assert r.status_code == 201, r.text
    assert r.json()["equipamento"]["situacao"] == "operacional"
    hist = [h["situacao_nova"] for h in client.get(f"/equipamentos/{e['id']}/historico").json()]
    assert hist[:2] == ["operacional", "em_manutencao"]  # passou por manutenção antes de voltar
    assert client.get(f"/equipamentos/{e['id']}/ordens-servico").json()[0]["status"] == "fechada"
    planos = client.get(f"/equipamentos/{e['id']}/planos-manutencao").json()
    periodico = next(p for p in planos if p["tipo"] == "periodica")
    assert periodico["proxima_data"] == (date.today() + timedelta(days=180)).isoformat()
    assert not any(p["ativo"] for p in planos if p["tipo"] == "imediata")


def test_sem_conserto_desativa(client, radar):
    e = radar()
    mudar(client, e["id"], "mau_funcionamento", "queimado")
    r = client.post(f"/equipamentos/{e['id']}/registros-manutencao",
                    json={"tecnico": "João", "resultado": "sem_conserto", "descricao": "placa queimada"})
    assert r.json()["equipamento"]["situacao"] == "desativado"


def test_manutencao_vencida_e_proxima(client, radar):
    e = radar()
    with SessionLocal() as db:
        db.execute(update(PlanoManutencao).where(PlanoManutencao.equipamento_id == e["id"])
                   .values(proxima_data=date.today() - timedelta(days=5)))
        derivados.recalcular(db, [e["id"]])
        db.commit()
    d = client.get(f"/equipamentos/{e['id']}").json()
    assert d["status_manutencao"] == "vencida"
    assert any(m["texto"] == "manutenção atrasada há 5 dias" and m["pontos"] == -18 for m in d["score_motivos"])
    with SessionLocal() as db:
        db.execute(update(PlanoManutencao).where(PlanoManutencao.equipamento_id == e["id"])
                   .values(proxima_data=date.today() + timedelta(days=7)))
        derivados.recalcular(db, [e["id"]])
        db.commit()
    assert client.get(f"/equipamentos/{e['id']}").json()["status_manutencao"] == "proxima"


# ---------- Falha silenciosa ----------


def test_falha_silenciosa_gera_alerta_sem_mudar_situacao_e_sinal_resolve(client, radar):
    e = radar()
    with SessionLocal() as db:
        db.execute(update(Equipamento).where(Equipamento.id == e["id"])
                   .values(ultimo_sinal_em=datetime.now(timezone.utc) - timedelta(minutes=46)))  # > 3 x 15 min
        derivados.recalcular(db, [e["id"]])
        db.commit()
    d = client.get(f"/equipamentos/{e['id']}").json()
    assert d["situacao"] == "operacional" and d["sem_sinal"] is True
    alertas = client.get("/alertas", params={"tipo": "falha_silenciosa"}).json()
    assert alertas["total"] == 1
    r = client.post("/telemetria/sinal", json={"dispositivo_iot_id": "IOT-TESTE-1"})
    assert r.json()["alerta_resolvido"] is True
    assert client.get("/alertas", params={"tipo": "falha_silenciosa"}).json()["total"] == 0


def test_sinal_de_modulo_desconhecido(client):
    assert client.post("/telemetria/sinal", json={"dispositivo_iot_id": "NAO-EXISTE"}).status_code == 404


# ---------- Unicidade ----------


def test_serie_unica_por_marca(client, radar):
    radar()
    r = client.post("/equipamentos", json={**RADAR, "dispositivo_iot_id": "IOT-OUTRO"})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "serie_duplicada"
    ok = client.post("/equipamentos", json={**RADAR, "marca": "Velsis", "dispositivo_iot_id": "IOT-OUTRO"})
    assert ok.status_code == 201
    assert ok.json()["avisos"][0]["codigo"] == "possivel_duplicidade"


def test_dispositivo_iot_unico(client, radar):
    radar()
    r = client.post("/equipamentos", json={**RADAR, "numero_serie": "OUTRA"})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "iot_duplicado"


# ---------- Schemas por tipo ----------


def test_atributos_validados_pelo_schema(client):
    r = client.post("/equipamentos", json={**RADAR, "atributos": {"modalidade": "voo", "faixas_monitoradas": 2}})
    assert r.status_code == 422
    assert r.json()["detail"]["detalhes"][0]["campo"] == "modalidade"
    r = client.post("/equipamentos", json={**RADAR, "atributos": {"modalidade": "velocidade"}})
    assert r.json()["detail"]["detalhes"][0]["campo"] == "faixas_monitoradas"


SEMAFORO = {
    "nome": "Semáforo inteligente", "prefixo": "SEM", "categoria": "Sinalização", "mobilidade": "fixo",
    "icone": "traffic-light", "intervalo_sinal_esperado_min": 5, "periodicidade_padrao_dias": 60,
    "schema_atributos": {
        "type": "object", "required": ["fases"],
        "properties": {
            "fases": {"type": "integer", "title": "Fases", "minimum": 2, "maximum": 8},
            "botoeira_pedestre": {"type": "boolean", "title": "Botoeira para pedestre"},
        },
    },
}


def test_tipo_criado_pela_interface_valida_equipamentos(client):
    t = client.post("/tipos-equipamento", json=SEMAFORO)
    assert t.status_code == 201, t.text
    tid = t.json()["id"]
    base = {**RADAR, "tipo_id": tid, "marca": "Digicon", "numero_serie": "SEM-1", "dispositivo_iot_id": None}
    assert client.post("/equipamentos", json={**base, "atributos": {"fases": 1}}).status_code == 422
    r = client.post("/equipamentos", json={**base, "atributos": {"fases": 3, "botoeira_pedestre": True}})
    assert r.status_code == 201
    assert r.json()["codigo_interno"] == "SEM-0001"


def test_schema_invalido_recusado(client):
    ruim = {**SEMAFORO, "schema_atributos": {"type": "object", "properties": {"x": {"type": "banana"}}}}
    assert client.post("/tipos-equipamento", json=ruim).status_code == 422


def test_so_gestor_cria_tipo(client):
    r = client.post("/tipos-equipamento", json=SEMAFORO, headers={"X-Perfil": "operador", "X-Orgao-Id": "1"})
    assert r.status_code == 403


def test_mudanca_de_schema_que_quebra_cadastros_e_recusada(client, radar):
    radar()
    tipo = client.get("/tipos-equipamento/1").json()
    novo = {**tipo, "schema_atributos": {**tipo["schema_atributos"], "required": ["modalidade", "faixas_monitoradas", "sentido"]}}
    r = client.put("/tipos-equipamento/1", json=novo)
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "schema_incompativel"


# ---------- Localização ----------


def test_bairro_sugerido_pelo_ponto(client, radar):
    e = radar()
    assert e["localizacao"]["bairro"] == "Centro"
    assert any(a["codigo"] == "bairro_sugerido" for a in e["avisos"])


def test_bairro_divergente_avisa_sem_bloquear(client, radar):
    e = radar(localizacao={**RADAR["localizacao"], "bairro_id": 2})
    assert e["localizacao"]["bairro"] == "Pinheiros"
    assert any(a["codigo"] == "bairro_divergente" for a in e["avisos"])


def test_coordenada_fora_do_brasil_avisa(client, radar):
    e = radar(localizacao={**RADAR["localizacao"], "lon": 2.35, "lat": 48.85})
    assert any(a["codigo"] == "fora_do_brasil" for a in e["avisos"])


def test_cep_e_bairro_opcionais(client, radar):
    e = radar(localizacao={"cidade_id": 1, "rua": "Rodovia dos Bandeirantes", "referencia": "KM 23"})
    assert e["localizacao"]["cep"] is None
    assert any(a["codigo"] == "sem_coordenadas" for a in e["avisos"])


# ---------- Perfis ----------


def test_operador_nao_altera_outro_orgao(client, radar):
    e = radar()  # órgão 1
    r = client.patch(f"/equipamentos/{e['id']}/situacao", json={"situacao": "em_manutencao", "motivo": "x x x"},
                     headers={"X-Perfil": "operador", "X-Orgao-Id": "2"})
    assert r.status_code == 404  # nem enxerga


# ---------- Agentes ----------


def test_agente_com_veiculo_movel(client):
    moto = client.post("/equipamentos", json={
        **RADAR, "tipo_id": 9, "marca": "Honda", "modelo": "XRE 300", "numero_serie": "9CHASSI0001",
        "dispositivo_iot_id": "IOT-MOTO", "atributos": {"placa": "ABC1D23", "prefixo": "M-1001"},
    })
    assert moto.status_code == 201, moto.text
    ag = {"nome": "Ana Souza", "matricula": "cet1", "categoria": "agente_transito", "orgao_id": 1,
          "veiculo_id": moto.json()["id"]}
    r = client.post("/agentes", json=ag)
    assert r.status_code == 201, r.text
    assert r.json()["veiculo"]["placa"] == "ABC1D23"
    r2 = client.post("/agentes", json={**ag, "matricula": "cet2"})
    assert r2.status_code == 409 and r2.json()["detail"]["codigo"] == "veiculo_em_uso"


def test_agente_nao_aceita_equipamento_fixo_como_veiculo(client, radar):
    e = radar()
    r = client.post("/agentes", json={"nome": "Ana Souza", "matricula": "x1", "categoria": "agente_transito",
                                      "orgao_id": 1, "veiculo_id": e["id"]})
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "veiculo_invalido"
