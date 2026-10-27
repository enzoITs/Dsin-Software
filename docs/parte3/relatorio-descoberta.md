# Relatório de descoberta dos padrões plantados

Gerado em 2026-10-27 00:30 (UTC) com os modelos `falha_equipamento_7d:2026-10-25.3,ocorrencias_regiao_hora:2026-10-25.1`.

> Dados sintéticos: os padrões foram plantados de propósito no gerador e os modelos não leram essa descrição. Encontrá-los mostra que o método funciona; numa cidade real, os padrões seriam outros.

Como foi feito: depois do treino, cada modelo é interrogado sem acesso à descrição dos padrões. Em P1, os mesmos equipamentos reais passam por contrafactuais (uma variável muda por vez: idade, temperatura da semana, atraso da preventiva), o que equivale à dependência parcial do modelo. Em P2, comparamos o que o modelo previu nas últimas 4 semanas por hora e dia com o que aconteceu, e aplicamos contrafactuais de chuva, evento e véspera. Padrões sem modelo próprio ainda são conferidos por consulta direta, e isso está dito na linha. Só no fim cada resultado é posto ao lado da regra plantada (`app/preditivo/padroes.py`).

Resultado: **9 encontrados**, 1 com sinal fraco, 0 não encontrados.

| # | Padrão | Veredito | O que o sistema achou | O que foi plantado | Como |
|---|---|---|---|---|---|
| 1 | Centro: mais ocorrências sexta e sábado, 18 h às 23 h | Encontrado | O modelo prevê 1,8× mais ocorrências no Centro nessas noites; nos dados, foram 2,5× | 2,2× (perturbação 3,5×) | P2: Previsões do modelo nas últimas 4 semanas: mesmas horas, sexta e sábado × demais dias |
| 2 | Chuva: mais acidentes e alagamentos em bairros baixos | Encontrado | Chuva de 8 mm/h aumenta as ocorrências previstas em 28%. Bairros que mais sobem: Lapa, Ipiranga, Bom Retiro, Casa Verde, Bela Vista. 4 dos 4 bairros baixos plantados estão entre os 5 que mais sobem | acidentes 1,4×; alagamentos em Casa Verde, Bom Retiro, Ipiranga, Lapa | P2: Contrafactual no modelo: as mesmas horas com 8 mm/h de chuva e secas |
| 3 | Eventos com mais de 10 mil pessoas: mais ocorrências num raio de 2 km | Encontrado | Um evento de 30 mil pessoas acrescenta 0,46 ocorrências por hora em cada bairro próximo (83% a mais) | +0,9 ocorrência por hora a cada 10 mil pessoas, de 2 h antes a 2 h depois | P2: Contrafactual no modelo: evento de 30 mil pessoas a 500 m × nenhum evento, por bairro e hora |
| 4 | Câmeras de uma marca falham mais depois de 18 meses, sobretudo após chuva | Encontrado | Para as câmeras Hikvision, passar de 10 para 24 meses multiplica o risco previsto por 3,4; para as outras marcas, por 1,1. Chuva forte na semana multiplica o risco das Hikvision antigas por 1,1 | 3× depois de 18 meses, mais 2× no dia seguinte a chuva forte | P1: Contrafactual no modelo: as mesmas câmeras com 10 e com 24 meses de uso |
| 5 | Radares de rodovia falham mais acima de 32 °C | Sinal fraco | Semana quente multiplica o risco previsto dos radares de rodovia por 1,2 e dos urbanos por 1,1 | 4× nos dias acima de 32 °C, só radares com limite de 80 km/h ou mais | P1: Contrafactual no modelo: os mesmos radares numa semana de 36 °C (4 dias quentes) e numa de 27 °C |
| 6 | Furtos de equipamentos em dois bairros, de madrugada, longe de câmeras | Encontrado | 40% dos furtos em 2 de 28 bairros; neles, 99% entre 0 h e 5 h | Brás, Itaquera, 0 h às 5 h, sem câmera a menos de 300 m | consulta: Consulta direta ao histórico (o modelo de risco de furto, P7, é da fase 12) |
| 7 | Manutenção atrasada há mais de 15 dias dobra a chance de falhar | Encontrado | Preventiva atrasada 30 dias multiplica o risco previsto por 1,7 | 2× com atraso acima de 15 dias | P1: Contrafactual no modelo: os mesmos equipamentos com a preventiva 30 dias atrasada e em dia |
| 8 | Congestionamentos nos dias úteis, 7–9 h e 17–19 h, mais fortes em véspera de feriado | Encontrado | O modelo prevê 1,7× mais ocorrências nas horas de pico (nos dados, 1,8×); véspera de feriado soma 13% nessas horas | congestionamentos 4× nas horas de pico, mais em véspera | P2: Previsões do modelo nas horas de pico × demais horas do dia útil; contrafactual de véspera |
| 11 | Queda lenta de disponibilidade numa região sem preventiva | Encontrado | Leste: 97,5% → 89,6%; outras: queda mediana de 0,4 pontos | região Leste | consulta: Consulta direta à disponibilidade diária (a tendência P6 é da fase 12) |
| 12 | Anomalias isoladas (radar que para de registrar, câmera que cai toda noite) | Encontrado | 6 de 6 equipamentos com anomalia plantada foram apontados; 0 outros equipamentos também | 6 equipamentos | P5: Alertas abertos pelos detectores de anomalia |

Critério: efeito aprendido de 1,3× ou mais = encontrado; entre 1,1× e 1,3× = sinal fraco.

Os padrões 9 e 10 (rotativo e patinetes) ficaram fora do plano enxuto. A mesma análise aparece na tela Confiança dos modelos, com os gráficos de dependência parcial.
