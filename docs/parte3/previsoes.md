# Previsões do Atalaia

O enunciado pede para "deixar claro o que está sendo previsto, quais informações foram consideradas e como essa previsão pode ajudar na tomada de decisão". Este documento responde a essas três perguntas para cada módulo, e mostra quanto cada um acerta contra uma referência simples.

> **Os dados são sintéticos.** Os números abaixo vêm do backtest no banco de demonstração criado em 27/10/2026 (`scripts/gerar_historico.py`, semente fixa, 18 meses); a tela Confiança dos modelos mostra os do banco em uso, que mudam um pouco com a data de criação. Numa cidade real, os padrões e as métricas seriam outros. Detalhes de cada escolha estão em [decisoes.md](decisoes.md).

## Regras que valem para todas

1. **Toda previsão vira uma ação**: quem, onde, quando e o quê (abrir OS preventiva, mover uma equipe, incluir ronda, priorizar manutenção).
2. **Toda previsão se explica**: os fatores aparecem como barras, em linguagem do gestor, com o peso de cada um.
3. **Toda previsão prova que funciona**: cada modelo é comparado com uma referência simples (baseline) num backtest de origem móvel de pelo menos 90 dias, e cada previsão é guardada para ser conferida com o que aconteceu (acertômetro).
4. **O humano decide**: Aceitar, Ajustar ou Rejeitar (com motivo). Nada é executado sem decisão, e tudo fica registrado.
5. **Lugares, períodos e equipamentos, nunca pessoas.** Ver [etica-e-limites.md](etica-e-limites.md).

Só entram dados disponíveis no momento da previsão. Um teste automatizado (`tests/test_variaveis.py`) acrescenta falhas, furtos, manutenções e ocorrências depois do corte e exige que nenhuma variável mude (só os alvos).

## Contrato de previsão

Toda previsão, de qualquer módulo, sai no mesmo formato (`GET /previsoes/{id}`) e aparece no mesmo **Cartão de Previsão**:

| Campo | O que é |
|---|---|
| `id`, `modulo`, `modelo {nome, versao}`, `gerado_em` | Identificação (`prev_123`, `P1`...) |
| `o_que_preve` | Frase do que está sendo previsto ("Chance de este radar entrar em mau funcionamento nos próximos 7 dias") |
| `alvo {tipo, id, nome, regiao}` | Equipamento, região ou bairro |
| `horizonte {inicio, fim}` | Período coberto |
| `valor`, `faixa {inferior, superior}`, `nivel` | Número previsto, faixa de 90% e nível (baixo, moderado, alto, muito alto) |
| `dados_considerados[]` | Fontes usadas ("histórico de falhas do equipamento", "previsão de chuva"...) |
| `fatores[{descricao, efeito}]` | O que empurrou o valor para cima ou para baixo |
| `como_ajuda` | Para que serve a previsão |
| `acao_recomendada {texto, tipo, parametros}` | O que fazer |
| `qualidade_do_modelo {metrica, modelo, baseline, avaliado_em}` | Quanto o modelo acerta contra a referência |
| `confianca` | Alta, moderada ou baixa, com aviso quando não é alta |
| `recomendacao` | A decisão já tomada (quem, quando, motivo) |

O cartão tem três títulos fixos: **"O que estamos prevendo"**, **"Com base em quê"** e **"Como isso ajuda"**.

## Resumo

| Módulo | O que prevê | Para quem | Modelo | Referência | Resultado |
|---|---|---|---|---|---|
| P1 | Chance de cada equipamento falhar em 7 e 30 dias | Manutenção | LightGBM calibrado | Taxa de falha do tipo | Dos 50 mais apontados, 17% falham na semana (referência: 4%) |
| P2 | Ocorrências por região e hora, 72 h | Operação | LightGBM Poisson por bairro | Média da mesma hora e dia nas últimas 8 semanas | Erro médio 1,25 × 1,34 por região e hora |
| P3 | Índice de risco 0–100 por região e período | Gestor | Fórmula sobre P1, P2, escala e contexto | Herda de P2 | Faixas Baixo, Moderado, Alto, Muito alto |
| P4 | Reforço de equipes por região e período | Gestor | Programação linear inteira | Escala atual | Risco não coberto 48% menor nas 72 h |
| P5 | Equipamentos e regiões fora do padrão | Central | STL + escore robusto, Isolation Forest | — | 6 de 6 anomalias plantadas achadas, nenhum alarme falso em 240 séries |
| P6 | Disponibilidade por região e tipo em 30 e 90 dias | Gestor | ETS amortecido nas médias semanais | Última média móvel de 30 dias | Erro 0,45 × 0,68 ponto em 90 dias |
| P7 | Chance de furto de cada equipamento em 30 dias | Operação | LightGBM com restrição monótona | Taxa de furto do tipo | AUC 0,63 × 0,53 |
| P8 | Carga de manutenção por semana, tipo e região (4 semanas) | Manutenção | Soma de P1 e do plano de preventivas | Taxa de falha do tipo | Erro 4,27 × 5,96 falhas em 30 dias |

---

## P1 — Risco de falha de equipamento

**O que estamos prevendo:** a probabilidade de cada equipamento em operação entrar em mau funcionamento nos próximos 7 e 30 dias.

**Com base em quê:** tipo, marca e modelo; idade; falhas anteriores (90 e 365 dias); dias desde a última manutenção e atraso da preventiva; chuva e calor da semana (clima previsto); furtos e vandalismo por perto; bairro. Os fatores do cartão agrupam as variáveis em 8 ideias (idade, equipamento, manutenção, falhas, chuva, calor, furtos, local), repartindo a diferença para um equipamento típico pelas contribuições SHAP.

**Como isso ajuda:** a equipe de manutenção vai primeiro onde a falha é mais provável, antes de o equipamento parar. Ação: **abrir OS preventiva** (um clique, ou em lote na tela Equipamentos em risco). Equipamentos acima de 25% em 7 dias e sem OS viram alerta preventivo na Central.

**Quanto acerta** (13 cortes semanais em 91 dias):

| Horizonte | Métrica | Modelo | Regressão logística | Taxa do tipo |
|---|---|---|---|---|
| 7 dias | AUC | **0,643** | 0,642 | 0,602 |
| 7 dias | Brier | **0,0255** | — | 0,0257 |
| 7 dias | Falham entre os 50 primeiros | **16,9%** | — | 4,2% |
| 30 dias | AUC | **0,638** | 0,638 | 0,596 |
| 30 dias | Brier | **0,0913** | — | 0,0941 |
| 30 dias | Falham entre os 50 primeiros | **51,8%** | — | 16,2% |

A AUC é modesta de propósito: cada equipamento tem uma fragilidade própria e a falha de um dia é sorteio. O que serve à decisão é o ranking: de cada 50 equipamentos apontados para a semana, cerca de 8 falham, contra 2 pela média do tipo. Confiança dita no cartão: moderada.

Telas: `/previsao/equipamentos`, ficha do equipamento, Central. API: `GET /equipamentos/risco`, `GET /equipamentos/{id}/risco`, `POST /equipamentos/risco/ordens`.

## P2 — Ocorrências por região e hora

**O que estamos prevendo:** quantas ocorrências (acidentes, congestionamentos, alagamentos, furtos de equipamento...) cada região deve ter em cada hora das próximas 72 h, com faixa de 90% e a divisão por categoria.

**Com base em quê:** hora, dia da semana, feriado e véspera; bairro; ocorrências das últimas semanas; eventos da cidade (público e distância); clima previsto (chuva, temperatura, tempestade); agentes na escala. A previsão é feita por bairro (28) e somada por região (5).

**Como isso ajuda:** mostra onde e quando a demanda vai subir, para posicionar equipes antes. Alimenta P3, P4 e o detector de anomalias de região.

**Quanto acerta** (região e hora):

| Métrica | Modelo | Média da mesma hora e dia (8 semanas) |
|---|---|---|
| Erro médio (MAE) | **1,252** | 1,337 |
| Erro percentual | **46,4%** | 49,6% |
| MAE nas horas de pico | **1,909** | 2,016 |
| Cobertura da faixa de 90% | 90% | — |

O erro quase não cresce com o horizonte (1,25 nas primeiras 24 h e entre 48 e 72 h). Com média de 2,7 ocorrências por região e hora, boa parte do erro é o sorteio natural das contagens. Atenção ao fator "agentes na escala": mais agentes registram mais ocorrências (viés de registro). Por isso os cenários nunca usam P2 para dizer que tirar equipes "reduz ocorrências".

API: `GET /previsoes?modulo=P2`, `GET /amanha/regioes/{id}`.

## P3 — Índice de risco por região e período

**O que estamos prevendo:** um índice de 0 a 100 por região, para cada hora e para os quatro períodos do dia (madrugada, manhã, tarde, noite).

**Com base em quê:** 40% ocorrências previstas (P2) ponderadas pela gravidade, contra o normal da região; 20% equipamentos indisponíveis ou em risco alto (P1); 15% cobertura prevista de câmeras e radares; 15% agentes da escala contra a demanda; 10% fatores externos (eventos, chuva, tempestade). Faixas: Baixo 0–24, Moderado 25–49, Alto 50–74, Muito alto 75–100. A faixa do índice vem do intervalo de P2.

**Como isso ajuda:** um número só para saber onde olhar primeiro amanhã. Pinta o mapa da tela "Amanhã" e a camada "Risco previsto (próximas 6 h)" da Central; Alto ou Muito alto nas próximas 6 h vira alerta preventivo.

**Quanto acerta:** o índice não tem um valor real único para comparar; herda a qualidade de P2, e o cartão diz isso. Testes conferem casos conhecidos e que os componentes somam o índice.

Telas: `/amanha`, Central. API: `GET /amanha`, `GET /risco-previsto`.

## P4 — Reforço de equipes

**O que estamos prevendo:** quantos agentes-hora cada região vai precisar em cada período (12 por ocorrência prevista, configurável) e qual a melhor redistribuição da escala.

**Com base em quê:** P2 (demanda), P3 (peso da região), escala de agentes por turno e órgão. A otimização (`scipy.optimize.milp`) minimiza o risco não coberto respeitando: mínimo de uma equipe por região, no máximo 4 deslocamentos por período, cada região mantém ao menos uma equipe de cada órgão que já tinha, nenhuma região "Muito alto" sem reforço, uma região não cede e recebe no mesmo período, regiões fixadas pelo gestor não cedem. Se a otimização falhar, uma heurística gulosa faz o plano.

**Como isso ajuda:** recomendação em texto direto, por exemplo "Domingo (25/10), 18 h às 24 h: reforçar a região Centro com +1 equipe de trânsito (CET), vinda da região Norte (risco previsto baixo nesse horário). Motivo: Palmeiras x São Paulo com 38 mil pessoas; ocorrências esperadas 1,4× o normal do horário." Aceitar move o turno só naquele período.

**Resultado:** nas 72 h a partir da criação do banco de demonstração, risco não coberto de 2.891 com a escala atual para 1.510 com a recomendada (48% menor), com 12 reforços. O número muda a cada hora, com a escala e as ocorrências previstas. Período sem reforço possível nas próximas 6 h vira alerta `PREVISAO_FALTA_AGENTES`.

Tela: `/previsao/equipes`. API: `GET /planejamento/equipes`, `POST /planejamento/equipes/recalcular`.

## P5 — Anomalias

**O que estamos detectando:** equipamentos cuja série (infrações de radar, horas no ar de câmera) saiu do padrão mesmo sem estar quebrada, e regiões com mais ocorrências do que a faixa de P2 permitia.

**Com base em quê:** no equipamento, decomposição STL (24 h) dos 60 a 3 dias anteriores com escore robusto, para queda sustentada (24 h) ou recorrente (mesmo horário em 2 dias ou mais); o Isolation Forest no perfil diário dá uma segunda opinião. Na região, o observado acima da faixa de 90% de P2 por 3 horas seguidas.

**Como isso ajuda:** um radar que para de registrar infrações ou uma câmera que cai toda noite passam despercebidos no painel de "operacional". O alerta mostra o gráfico esperado × observado e se resolve sozinho quando a série volta ao normal.

**Resultado:** as 6 anomalias plantadas (3 radares com 80% menos infrações, 3 câmeras que caem toda noite) encontradas; nenhum alarme falso nas 240 séries. Roda a cada 5 minutos.

API: `GET /anomalias`.

## P6 — Tendência de disponibilidade

**O que estamos prevendo:** a disponibilidade de cada região e tipo nos próximos 30 e 90 dias, em dois cenários: "se nada mudar" e "seguindo o P1" (fazendo as preventivas recomendadas).

**Com base em quê:** médias semanais das últimas 52 semanas (ETS com tendência amortecida); para "seguindo o P1", as falhas esperadas dos equipamentos de risco alto e o tempo médio de conserto da região.

**Como isso ajuda:** semanas antes, mostra a região que vai cruzar a meta de 90% (alerta `PREVISAO_DISPONIBILIDADE`) e quanto as preventivas evitam. Ação: priorizar manutenção (abre OS para até 20 equipamentos de risco alto da região).

**Quanto acerta:** erro de 0,38 × 0,46 ponto em 30 dias (17% menor) e 0,45 × 0,68 em 90 dias (34% menor). Na região Leste, que cai de verdade, 1,07 × 2,34 em 90 dias.

Tela: `/previsao/tendencias`. API: `GET /tendencias/disponibilidade`.

## P7 — Risco de furto

**O que estamos prevendo:** a chance de cada equipamento ser furtado nos próximos 30 dias.

**Com base em quê:** furtos no bairro (90 e 365 dias) e a menos de 500 m, vandalismo de madrugada no bairro, distância até a câmera em operação mais próxima, agentes de madrugada na região, tipo e idade. Restrição monótona: mais furtos por perto ou câmera mais longe nunca reduzem o risco.

**Como isso ajuda:** ação "incluir na ronda noturna" e, quando não há câmera a menos de 300 m, indicação na tela de Expansão.

**Quanto acerta:** AUC 0,634 contra 0,528 da taxa de furto do tipo. Furto é raro (taxa de 0,15% em 30 dias): entre os 50 apontados, 2,9% são furtados, contra 0,4% pela taxa do tipo. A confiança é dita no cartão; o banco de desenvolvimento chegou a AUC 0,73, e a diferença mostra quanto o resultado depende de poucos casos.

Tela: `/previsao/furtos`. API: `GET /furtos/risco`.

## P8 — Carga de manutenção

**O que estamos prevendo:** corretivas e preventivas esperadas por semana, tipo e região nas próximas 4 semanas, em técnicos-dia e kits de reparo.

**Com base em quê:** P1 (7 dias na primeira semana, o restante de 30 dias nas outras), equipamentos já parados, plano de preventivas e atraso acumulado.

**Como isso ajuda:** planejar técnicos e peças antes do pico.

**Quanto acerta:** no backtest de P1 em 30 dias somado por tipo e região, erro de 4,27 falhas contra 5,96 da taxa do tipo (28% melhor).

API: `GET /tendencias/manutencao`.

---

## Usos das previsões

| Recurso | O que faz | Onde |
|---|---|---|
| Cenários "e se" (C1) | Roda P2, P3 e P4 com e sem uma mudança (evento novo ou cancelado, chuva, equipes, equipamentos fora, preventivas) e compara | `/previsao/cenarios`, `POST /cenarios/simular` |
| Expansão (C2) | Onde uma câmera nova cobriria mais ocorrências e evitaria mais furtos (contrafactual de P7) | `/previsao/expansao`, `GET /expansao/sugestoes` |
| Copiloto (C3) | Perguntas em português respondidas com as mesmas consultas; com ou sem IA | `/previsao/copiloto`, `POST /copiloto/perguntar` |
| Briefing diário (C4) | Às 6 h: risco do dia, reforços, preventivas, anomalias, contexto e acertômetro de ontem, em Markdown | `/previsao/briefing`, `GET /briefing/hoje` |
| Retorno das decisões (C5) | O que aconteceu depois de cada decisão, aceitas × rejeitadas | `/previsao/decisoes`, `GET /recomendacoes/retorno` |
| Acertômetro (Q1) | Cada previsão de P1 e P2 conferida com o valor real, contra a referência | `/previsao/confianca`, `GET /modelos/acertometro` |
| Padrões descobertos (Q2) | O que os modelos aprenderam × o que foi plantado | [relatorio-descoberta.md](relatorio-descoberta.md), `GET /modelos/padroes-descobertos` |
| Fim de vida útil (X3) | Trocar ou consertar: risco atual × risco "como se fosse novo" | `/previsao/fim-de-vida` |
| Monitor dos modelos (X4) | Idade do treino, desempenho em operação, deriva dos dados | `GET /modelos/monitor` |
| Relatório semanal (X5) | Resumo da semana no formato do briefing | `GET /relatorio/semanal.md` |

## Quando rodam

| O quê | Quando |
|---|---|
| P2, P3, P4, alertas preventivos, acertômetro, retorno | De hora em hora (minuto 3) |
| P1, P6, P7, P8 | Todo dia às 5h10 |
| P5 | A cada 5 minutos |
| Briefing | Às 6 h (ou no start, se faltar) |
| Cenários, copiloto | Sob demanda |
| Treino completo | No primeiro start (cerca de 3 min, com progresso na tela) ou `python -m app.preditivo.treinar --todos` |

Os limites (níveis de P1, 12 agentes-hora por ocorrência, máximo de deslocamentos, limites dos alertas...) ficam na configuração (`prev_*`) e podem ser trocados sem mexer no código.
