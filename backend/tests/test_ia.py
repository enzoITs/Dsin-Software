"""Recursos de IA com o modelo simulado: o que importa é a validação do que volta."""

import json

from app.services import ia


def test_sem_chave_responde_503(client):
    r = client.post("/busca", json={"texto": "câmeras no centro"})
    assert r.status_code == 503 and r.json()["detail"]["codigo"] == "ia_indisponivel"
    r = client.post("/ia/extrair-cadastro", data={"texto": "radar na paulista"})
    assert r.status_code == 503


def test_extracao_valida_e_descarta_o_que_nao_confere(client, monkeypatch):
    def falso(texto, imagem, media, tipos, bairros):
        assert "Centro" in bairros
        return {
            "tipo_id": 1, "marca": "Perkons", "modelo": "PK-Vel 300", "numero_serie": "PK-123",
            "dispositivo_iot_id": None,
            "atributos_json": json.dumps({"modalidade": "velocidade", "velocidade_maxima": 60,
                                          "faixas_monitoradas": 99, "inventado": 1}),
            "rua": "Avenida Paulista", "referencia": "oposto ao 181", "cep": "01310100", "bairro": "centro",
            "observacoes": ["Número de série parcialmente legível"],
        }
    monkeypatch.setattr(ia, "extrair_cadastro", falso)
    r = client.post("/ia/extrair-cadastro", data={"texto": "radar de 60 km/h na Av. Paulista, oposto ao 181"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["atributos"] == {"modalidade": "velocidade", "velocidade_maxima": 60}  # 99 faixas e chave inventada caem
    assert s["localizacao"]["cep"] == "01310-100"
    assert s["localizacao"]["bairro_id"] == 1 and s["localizacao"]["lon"] is not None
    assert any("Faixas" in o for o in s["observacoes"])


def test_busca_ignora_valores_fora_das_listas(client, monkeypatch):
    def falso(pergunta, tipos, orgaos, bairros):
        return {"tipo_ids": [2, 999], "situacoes": ["operacional"], "orgaos": ["cet", "XYZ"], "regioes": ["Centro"],
                "bairros": ["Pinheiros", "Atlântida"], "status_manutencao": ["proxima", "vencida"], "sem_sinal": False,
                "score_max": None, "atributos_json": json.dumps({"visao_noturna": False, "drop table": 1}), "texto": None,
                "interpretacao": ["Tipo: câmera", "Região: Centro"]}
    monkeypatch.setattr(ia, "interpretar_busca", falso)
    r = client.post("/busca", json={"texto": "câmeras sem visão noturna no Centro com manutenção vencendo"})
    p = r.json()["params"]
    assert p["tipo_id"] == ["2"] and p["orgao_id"] == ["1"] and p["bairro_id"] == ["2"]
    assert p["status_manutencao"] == ["proxima", "vencida"]
    assert json.loads(p["atributos"]) == {"visao_noturna": False}
    lista = client.get("/equipamentos", params={**p, "atributos": p["atributos"]})
    assert lista.status_code == 200
