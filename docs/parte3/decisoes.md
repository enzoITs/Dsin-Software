# Parte 3 — Decisões técnicas e divergências do documento

Onde a implementação se afastou da especificação para respeitar o código das Partes 1 e 2, ou por limitação encontrada. Atualizado a cada fase.

## Fase 0 (aprovadas)

| Ponto | Decisão | Motivo |
|---|---|---|
| Histórico | O seed da Parte 1 passa a usar o gerador com padrões, e o banco é recriado | O histórico antigo é ruído puro e `historico_situacao` não aceita DELETE. Duas versões do passado no banco confundiriam a ficha do equipamento |
| Unidade espacial de P2 | Previsão por bairro (28), somada por região (5) | 5 regiões são poucas para um modelo de contagem |
| Padrões 9 e 10 | Fora do gerador | Só serviam aos extras X1 e X2, fora do plano enxuto |
| Presença passada de agentes | Vem da escala sintética | Não existe histórico de posições |
| Escopo | Plano enxuto da Fase 0 (seção 5 de `00-reconhecimento.md`) | Prazo de cerca de 2 dias |

## Fase 1

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| Valores de enum | `SIMULADA`, `CENTRAL`, `PENDENTE`... em maiúsculas | `simulada`, `central`, `pendente`... em minúsculas | Padrão de todos os enums das Partes 1 e 2. Os códigos de categoria de ocorrência (`ACIDENTE`...) ficam em maiúsculas porque são dados de uma tabela-catálogo, não enum |
| Otimização de P4 | PuLP com CBC | `scipy.optimize.milp` (HiGHS) | O PuLP 4.x não traz mais o CBC embutido; o SciPy já vem com o scikit-learn e o HiGHS funciona offline |
| Serviço preditivo | Módulo ou FastAPI separado | Pacote `backend/app/preditivo/` dentro do backend | Reaproveita modelos, sessão e configuração |
| Regiões nas ocorrências | `regiao_id` | `regiao_id` e `bairro_id` (FK) | As tabelas da Parte 2 guardam a região pelo nome; a Parte 3 usa chave estrangeira, e as consultas juntam pelo nome quando preciso |
| Eventos da cidade | origem não especificada | Campo `simulado` separa os gerados dos cadastrados na interface | Permite limpar os sintéticos sem perder os cadastrados |
| Clima | "histórico sintético coerente com a estação" | O clima de cada dia é sorteado com semente que depende só da data. O histórico e a previsão padrão de um dia são o mesmo dia | Quando o modo contínuo chegar a um dia previsto, acontece o que foi previsto (a menos que o operador tenha editado) |
| Edição do clima | — | Horas editadas guardam `editado_por` e nunca são sobrescritas pela previsão automática | O gestor manda na previsão que digitou |
| Calendário | feriados pela biblioteca `holidays` | `holidays` (nacionais e SP) + municipais de São Paulo (25/01, Corpus Christi) + Carnaval como "facultativo" | A biblioteca não tem feriados municipais; o Carnaval muda a cidade mesmo sendo ponto facultativo |
| Dia de pagamento | 5º dia útil | 5º dia de segunda a sexta sem feriado | Sábado não conta, por simplicidade |
| Período escolar | — | Aproximado: de fevereiro (primeira segunda) a 10/07 e de 01/08 a 18/12, dias úteis | Calendário oficial muda todo ano |
| Ocorrência derivada de incidente correlacionado | — | Categoria `OUTROS`, gravidade 3 | Não há categoria específica; a descrição repete a do alerta |
| Imagem do backend | estimativa de 400 MB a mais | cerca de 520 MB a mais (1,07 GB no total) | O SHAP traz numba e llvmlite |
| Migrações em teste | — | `alembic/env.py` aceita uma conexão em `config.attributes["connection"]` | Permite testar subir e descer a 0003 num banco à parte |

## Fase 2

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| Onde fica o gerador | `scripts/gerar_historico.py` gera tudo | A vida dos equipamentos (falhas, furtos, manutenções) é gerada pelo seed da Parte 1, que chama `app/preditivo/gerador_equipamentos.py`. `scripts/gerar_historico.py` gera a cidade (clima, eventos, escala, ocorrências, séries) | `historico_situacao` não aceita DELETE nem UPDATE: o passado dos equipamentos precisa nascer certo junto com eles. Assim a ficha do equipamento e a previsão contam a mesma história |
| Período | 12 a 18 meses | 18 meses (540 dias) com padrões; antes disso, a vida do equipamento continua simples | Dá estações completas e espaço para backtest de 90 dias |
| Data de referência | — | Fim do histórico = dia da criação do banco (ou `--data-referencia`), gravado em `estado_preditivo` | O seed calculava tudo a partir de `now()`. Com a data fixa, mesma semente gera os mesmos dados |
| Estado final dos equipamentos | Seed sorteava o estado final | Só "não instalado" e "desativado" são sorteados; os demais saem da simulação | O estado atual precisa ser coerente com a história simulada |
| "Radar de rodovia" (padrão 5) | — | Radar de velocidade com limite de 80 km/h ou mais | O cadastro não tem o tipo de via; o limite de velocidade é o que mais se aproxima, e o modelo vê esse atributo |
| Marca do padrão 4 | "uma marca específica" | Hikvision (normalizada: as duplicidades com a marca em maiúsculas contam) | — |
| Padrão 11 | "região sem manutenção preventiva" | Leste deixa de fazer 92% das preventivas a partir de 1/3 do período, e o conserto fica mais lento | Queda lenta e visível, que nasce do mesmo mecanismo do padrão 7 |
| Conserto corretivo | — | Não conta como preventiva (não zera o atraso) | Do contrário, quem falha muito nunca fica atrasado, e o padrão 7 se esconde |
| Sinais agregados e posições de agentes | "sinais agregados, posições agregadas de agentes" | Sinais: séries por hora de 240 equipamentos (120 radares, 120 câmeras) nos últimos 60 dias, nova tabela `serie_equipamento_hora` (migração 0004). Agentes: escala por região (`escala_agente`) | Volume controlado; é o que P5 e P4 usam |
| Falha silenciosa no histórico | — | Não gerada; o alvo de P1 é a entrada em mau funcionamento | Silêncios não são guardados como série nas Partes 1 e 2; a câmera que cai toda noite (padrão 12) cobre o caso nas séries |
| Rotativo e patinetes | padrões 9 e 10 | Não gerados | Aprovado na Fase 0 |
| Viés de patrulhamento | `agentes_presentes_regiao` | Gravado em toda ocorrência gerada, e o próprio gerador registra um pouco mais onde há mais agentes (até 25%) | O viés existe nos dados, como na vida real, para os modelos terem de lidar com ele |
| Modo contínuo | "alimenta o simulador da Parte 2" | O simulador de telemetria chama o gerador a cada 5 minutos (ocorrências e séries das horas passadas) e aplica uma vez por hora as falhas, furtos e consertos pela API. Consertos só em equipamentos que o próprio gerador derrubou | O motor da Parte 2 reage como a um equipamento de verdade, e a demonstração manual não é desfeita pelo gerador |
| Clima no modo contínuo | — | O que acontece é o clima gravado no banco, inclusive o editado pelo operador | "Amanhã chove forte" vira histórico com chuva forte, e as previsões podem ser conferidas |
| Eventos futuros | — | Gerados para os próximos 30 dias (o modo contínuo estende), mais um grande show no Pacaembu na primeira sexta depois da data de referência | Entradas de P2 e roteiro da demonstração |
| Gravação | — | `COPY` do psycopg para ocorrências e séries | 160 mil ocorrências e 345 mil pontos de série em cerca de 20 s |

## Fase 3

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| Unidade de P1 | equipamento × dia | Equipamento × data de corte semanal (meia-noite local); alvos "falha nos próximos 7 dias" e "nos próximos 30 dias" | Diário daria 7 vezes mais linhas quase iguais; semanal treina em segundos e tem o mesmo poder (decidido na Fase 0) |
| Unidade de P2 | região × hora | Bairro × hora (28 bairros), somado por região na avaliação | Aprovado na Fase 0 |
| "Ocorrências nas últimas 1/24/168 h" | relativo à hora prevista | Relativo à **origem** da previsão (o momento em que ela é feita) | Para prever até 72 h à frente, as horas imediatamente anteriores à hora prevista ainda não aconteceram. Usar a hora prevista seria vazamento |
| Linhas de treino de P2 | — | Uma origem por dia (meia-noite), 72 horas previstas por origem; a mesma hora aparece com horizontes diferentes | O modelo aprende quanto a informação recente vale para cada horizonte |
| Previsão do tempo no histórico | — | Para dias passados, a "previsão" é o tempo que fez (previsão perfeita) | O histórico sintético não guarda previsões antigas. Na operação, as horas futuras vêm da previsão editável |
| Eventos, escala e calendário futuros | — | Usados como variáveis da hora prevista | São informação conhecida com antecedência, não vazamento |
| Variáveis de equipamento ausentes | silêncios recentes, tendência das métricas, score de saúde | Não usadas | As Partes 1 e 2 só guardam o valor atual (último sinal, métricas e score de agora). Usar o valor de hoje para um corte no passado seria vazamento |
| Furtos próximos | — | Furtos no mesmo bairro nos 90 dias antes do corte | Simples e sem vazamento |
| Tipo de equipamento no baseline de P1 | taxa histórica do tipo | Falhas do tipo nos 365 dias antes do corte ÷ (equipamentos em serviço × 365); probabilidade em N dias = 1 − (1 − taxa)^N | Janela e horizonte configuráveis |
| Horas de pico em P2 | — | 7 h, 8 h, 9 h, 17 h, 18 h e 19 h dos dias úteis | Mesmas faixas dos picos da Parte 2 |
| Métrica principal de P2 | MAE por região | MAE por **região e hora** (bairros somados); MAE por bairro guardado também | O gestor decide por região |
| Configuração | — | Parâmetros `prev_*` no mesmo mecanismo de limites da Parte 2 (`config_motor`, `PUT /central/configuracao`) | Nada fixo no código |
| Comando de treino | `python -m preditivo.treinar --todos` | `python -m app.preditivo.treinar --todos` (ou `--baselines`) | O pacote fica dentro de `app/` |
| Disponibilidade diária (base de P6) | — | Reconstruída do histórico de situação: operacionais ÷ em serviço (operacional, mau funcionamento, em manutenção, furtado) à meia-noite, por região | Não existe série histórica de disponibilidade nas Partes 1 e 2 |

### Baselines no backtest (banco de demonstração, semente 42, referência 25/10/2026)

Backtest de origem móvel nos últimos 91 dias, um corte por semana.

| Módulo | Baseline | Resultado |
|---|---|---|
| P1, 7 dias | Taxa de falha do tipo | AUC 0,597; Brier 0,0264; precisão nos 50 primeiros 3,8% (taxa base 2,7%) |
| P1, 30 dias | Taxa de falha do tipo | AUC 0,597; Brier 0,0961; precisão nos 50 primeiros 15,8% (taxa base 10,9%) |
| P2 | Média da mesma hora e dia da semana em 8 semanas | MAE por região e hora 1,29 (média real 2,50 ocorrências), erro 51,8%; no pico, MAE 1,89 |
| P6, 30 dias | Última média móvel de 30 dias | Erro médio de 0,53 ponto percentual |

## Fase 4 (P1)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| Modelo | LightGBM com regressão logística de comparação | LightGBM (250 árvores) e regressão logística (amostra de 150 mil linhas, one-hot), ambos avaliados no mesmo backtest | — |
| Calibração | isotônica ou Platt | Isotônica, ajustada nas últimas 4 semanas de cortes do treino (o LightGBM treina nas anteriores) | Calibração sempre em dados posteriores aos do treino, como na operação |
| SHAP | biblioteca SHAP | Contribuições TreeSHAP do próprio LightGBM (`pred_contrib`) | Mesmo cálculo, mais rápido e sem dependência extra em tempo de previsão. A biblioteca SHAP continua instalada para a Fase 10 (dependência parcial) |
| Fatores no cartão | barras de contribuição em linguagem do gestor | Variáveis agrupadas em 8 fatores (idade, equipamento, manutenção, falhas, chuva, calor, furtos, local). A diferença entre a probabilidade do equipamento e a de um equipamento típico é repartida entre os fatores na proporção das contribuições SHAP; a soma dá exatamente a diferença | Várias variáveis técnicas descrevem a mesma coisa para o gestor (atraso, dias desde a preventiva...) |
| Faixa da probabilidade | intervalo | Faixa de 90% (Wilson) para uma amostra de 300 casos com a mesma probabilidade | Lê-se "de cada 100 equipamentos assim, entre X e Y devem falhar" |
| Níveis | — | 7 dias: moderado a partir de 5%, alto de 12%, muito alto de 25%; 30 dias: 15%, 30%, 50% (configuráveis) | Taxa base de 2,7% em 7 dias e 11% em 30 dias |
| Backtest | origem móvel | Corte semanal nos últimos 91 dias (13 cortes em 7 dias, 9 em 30 dias), retreino a cada 2 cortes, treino com as 52 semanas anteriores cujo alvo já era conhecido no corte | Mantém o treino completo em cerca de 2 minutos |
| Previsões gravadas | tabela `previsao` | Uma por equipamento em operação e horizonte (7 e 30 dias), com o cartão completo em `detalhe`; refazer no mesmo dia substitui | A API só lê |
| Score de saúde e ficha | probabilidade na ficha e no score | Fica para a Fase 8 (telas) | Ordem do plano enxuto |

### Resultados de P1 no backtest (banco de demonstração)

| Horizonte | Métrica | Modelo | Regressão logística | Baseline (taxa do tipo) |
|---|---|---|---|---|
| 7 dias | AUC | **0,643** | 0,638 | 0,597 |
| 7 dias | Brier | **0,0262** | — | 0,0264 |
| 7 dias | Precisão nos 50 primeiros | **15,1%** | — | 3,8% (taxa base 2,7%) |
| 30 dias | AUC | **0,646** | 0,645 | 0,597 |
| 30 dias | Brier | **0,0928** | — | 0,0961 |
| 30 dias | Precisão nos 50 primeiros | **52,9%** | — | 15,8% (taxa base 10,9%) |

Peso médio dos fatores (P1, 7 dias): equipamento (marca e modelo) 39%, idade 19%, histórico de falhas 16%, manutenção 14%, local 5%, chuva 3%, calor 3%, furtos 1%. O teto de AUC é baixo de propósito: no gerador, cada equipamento tem uma fragilidade própria e a falha de um dia é um sorteio. O que importa para a decisão é o ranking: de cada 50 equipamentos apontados para a semana, cerca de 8 falham, contra 2 pelo baseline.

## Fase 5 (P2 e P3)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| Modelo de P2 | gradient boosting Poisson ou Tweedie | LightGBM Poisson por bairro × hora; a região é a soma dos bairros | Aprovado na Fase 0 |
| Intervalo de P2 | quantílica ou conformal | Conformal com escore normalizado (\|real − previsto\| ÷ √previsto), calibrado nas últimas 4 semanas do treino, por região e hora; depois o modelo é refeito com todas as origens | Um só modelo, cobertura medida no backtest |
| P2 por categoria | total e por categoria principal | O total previsto é repartido pela proporção de cada categoria na região, tipo de dia e hora nas 8 semanas anteriores | Um modelo por categoria triplicaria o treino; as proporções mudam pouco |
| Nível de P2 | — | Previsto ÷ normal da mesma hora: muito acima (≥ 1,5), acima (≥ 1,15), normal, abaixo (< 0,85) | Linguagem do gestor |
| "Normal da região" em P3 | — | Média de ocorrências por hora da região nas últimas 8 semanas (todas as horas), ponderada pela gravidade | Comparar com a mesma hora esconderia os picos que o gestor precisa ver (sexta à noite no Centro) |
| Notas dos componentes de P3 | — | Ocorrências: normal = 10, o dobro = 60, 2,8 vezes = 100. Equipamentos: 15% da região fora de operação ou em risco alto = 100. Cobertura: 75% das câmeras e radares operando sem risco = 100. Agentes: a escala cobre a demanda = 0, cobre 40% = 100. Externos: 40 mil pessoas, 10 mm/h de chuva ou alerta de tempestade = 100 | Escalas simples, iguais para todas as regiões, documentadas no código |
| Demanda de agentes | "uma equipe para cada N ocorrências" | 12 agentes-hora por ocorrência prevista na hora (configurável, `prev_agentes_por_ocorrencia`) | Calibrado para a escala média cobrir a demanda média |
| Faixa de P3 | — | Índice recalculado com os limites do intervalo de P2 | A incerteza do índice vem da incerteza das ocorrências |
| Períodos | 4 por dia | Madrugada (0 h às 6 h), manhã, tarde e noite; somas para contagens e agentes, máximos para eventos e chuva; o período em curso começa na origem | — |
| Previsões gravadas | — | De hora em hora: 360 de P2 (5 regiões × 72 h) e cerca de 425 de P3 (horas e períodos), com a origem no `detalhe`. Rodar de novo na mesma hora substitui | Previsões de origens diferentes ficam guardadas para o acertômetro |
| Escala sintética (correção da Fase 2) | — | Equipes distribuídas pelas regiões na proporção do número de bairros | A versão anterior, pela posição dos agentes, deixava Leste e Norte sem nenhuma equipe |

### Resultados de P2 no backtest (banco de demonstração)

| Métrica (região e hora) | Modelo | Baseline sazonal |
|---|---|---|
| MAE | **1,244** | 1,333 |
| Erro percentual | **46,1%** | 49,4% |
| MAE nas horas de pico | **1,905** | 2,000 |
| Cobertura do intervalo de 90% | 90% | — |

Por região (MAE): Centro 1,65 (baseline 1,78), Sul 1,33 (1,40), Oeste 1,23 (1,35), Leste 1,12 (1,21), Norte 0,89 (0,92). O erro quase não cresce com o horizonte (1,24 nas primeiras 24 h e 1,25 entre 48 e 72 h), porque o modelo se apoia no calendário e nas entradas futuras (eventos, clima, escala), não nas últimas horas. Com média de 2,5 ocorrências por região e hora, boa parte do erro é o sorteio natural das contagens.

Peso médio dos fatores de P2: hora e dia 49%, bairro 17%, padrão das últimas semanas 13%, agentes na escala 13% (efeito do viés de registro), eventos 3%, clima 2%.

## Fase 6 (P4)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| Solver | PuLP com CBC ou OR-Tools | `scipy.optimize.milp` (HiGHS), já decidido na Fase 1 | Funciona sem internet e já vem com o SciPy |
| Unidade de decisão | equipes por região e período | Cada turno da escala que toca o período é uma equipe com capacidade em agentes-hora (agentes × horas dentro do período). Os 4 períodos do dia são otimizados um a um | Um turno da noite que cruza a meia-noite conta só as horas de cada período |
| Demanda | "uma equipe para cada N ocorrências, ajustada pela gravidade" | Agentes-hora = ocorrências previstas (P2) × 12 (configurável). A gravidade entra pelo peso da região, que é 1 + índice de risco ÷ 50 | Mesma demanda usada no componente de agentes do P3, para os dois números baterem |
| Objetivo | minimizar o risco não coberto | Σ peso × agentes-hora que faltam, mais um custo pequeno por deslocamento (só se move uma equipe se isso ajudar) | Evita trocas sem ganho |
| Restrição de órgão | "órgão de cada equipe" | Cada região mantém ao menos uma equipe de cada órgão que já tinha no período (trânsito, guarda municipal, polícia militar) | Nenhuma região fica, por exemplo, sem agente de trânsito |
| Mínimo e máximo | mínimo por região, máximo de deslocamentos | Mínimo de 1 equipe (ou o que a região já tinha, se menos); no máximo 4 deslocamentos por período; regiões "fixas" (escolhidas pelo gestor) não cedem equipes | Configurável (`prev_p4_*`) e ajustável no recálculo |
| "Muito alto" sem reforço | proibido | Restrição de pelo menos uma equipe a mais; se ficar impossível, a otimização roda sem ela e o plano avisa | Nunca devolve "sem solução" ao gestor |
| Reserva | heurística gulosa | A cada passo, move a equipe que mais reduz o risco não coberto sem quebrar nenhuma restrição, com prioridade para regiões em risco muito alto; para quando nada mais ajuda | Usada se o HiGHS falhar ou passar de 10 s |
| Saída | texto direto | "Domingo (25/10), 18 h às 24 h: reforçar a região Centro com +1 equipe de trânsito (CET), vinda da região Norte (risco previsto baixo nesse horário). Motivo: Palmeiras x São Paulo com 38 mil pessoas; ocorrências esperadas 1,4× o normal do horário." | Uma recomendação pendente por destino e período; uma previsão P4 por região e período com o cartão completo. Recomendações pendentes de planos anteriores expiram |
| API | `GET /planejamento/equipes`, `POST .../recalcular` | Iguais; o recálculo aceita máximo de deslocamentos, mínimo por região e regiões fixas, e só grava (`salvar`) com perfil de gestor | — |

### Resultado de P4 (banco de demonstração, próximas 72 h a partir de 25/10, 12 h)

Risco não coberto (agentes-hora ponderados pelo risco), somando os 12 períodos: **1.731 com a escala atual → 637 com a recomendada (63% menor)**, com 17 recomendações de reforço e no máximo 4 deslocamentos por período. As madrugadas quase não mudam: há poucas equipes em turno, e as regiões que as têm não podem cedê-las sem ficar abaixo do mínimo. A otimização dos 12 períodos leva cerca de 0,5 s.

## Fase 7 (P5)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| Detectores | equipamento, região e operação | Equipamento e região. O de operação ficou fora | Primeiro item da ordem de corte aprovada na Fase 0 |
| Equipamento: método | STL e escore robusto; Isolation Forest no perfil diário | STL robusta (período de 24 h) nos 60 a 3 dias anteriores; nível e padrão do dia pelas medianas de toda a referência; escala = maior entre a dispersão robusta dos resíduos (MAD) e a raiz do esperado (contagens). Regras: **queda sustentada** (escore das últimas 24 h somadas ≤ −4 e menos da metade do esperado) e **queda recorrente** (horas com escore ≤ −4 e menos da metade do esperado, no mesmo horário, em 2 dias ou mais) | Com medianas, uma mudança só vira "o novo normal" se ocupar mais da metade da referência; por isso as anomalias plantadas há 25 e 30 dias continuam aparecendo. O escore das 24 h somadas é justo com radares de pouco movimento |
| Isolation Forest | detector | Segunda opinião: perfil diário (forma das 24 h, volume e horas abaixo do normal) de todos os equipamentos da métrica; o dia recente mais estranho que 95% dos dias de referência é marcado como atípico e mostrado junto da anomalia | O Isolation Forest isola qualquer dia diferente em poucas divisões (até uma queda isolada de uma hora) e não mede a intensidade; usado sozinho, daria alarmes falsos |
| Região | observado fora do intervalo de P2 por N horas | Acima do limite superior do intervalo de 90% de P2 por 3 horas seguidas (configurável, `prev_p5_horas_seguidas`); para cada hora, vale a previsão feita na origem mais recente antes dela | Só "acima" vira alerta; menos ocorrências que o previsto não é problema para a central |
| Alertas | regra `ANOMALIA_*` | Novos tipos `anomalia_equipamento` (nível inicial médio) e `anomalia_regiao` (alto) no motor da Parte 2; a migração 0005 já acrescenta também os 4 tipos `previsao_*` da Fase 9. O alerta guarda o gráfico esperado × observado das últimas 72 h (ou 24 h na região) e se resolve sozinho quando a série volta ao padrão | Mesmo ciclo de vida, central e canal de eventos das demais regras |
| Frequência | a cada 5 minutos | Agendador da API, a cada 5 minutos (cerca de 25 s para 240 séries) | — |
| Migração 0005 | reversível | Acrescenta valores ao enum `tipo_alerta`. Na volta, apaga os alertas desses tipos; os valores do enum ficam, sem uso | O PostgreSQL não remove valores de enum |
| API | `GET /anomalias` | `GET /anomalias` (abertas, ou todas com `abertas=false`) com o gráfico; `POST /anomalias/verificar` roda na hora (gestor) | — |

### Resultado de P5 (banco de demonstração)

As 6 anomalias plantadas (3 radares com queda de 80%, que começaram 2, 9 e 25 dias antes da data de referência, e 3 câmeras que caem toda noite desde 5, 12 e 30 dias antes) foram encontradas. Nenhum alarme falso entre as 240 séries. Exemplos de mensagem: "RAD-2698: 86% menos infrações registradas que o esperado nas últimas 24 h" e "CAM-5448: fora do ar todos os dias entre 0 h e 5 h (3 dias seguidos)".

## Fase 8 (contrato, Cartão de Previsão e telas)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| Contrato | campos de 6.1 | Todos, mais `confianca` (nível e aviso), `dados_sinteticos`, `recomendacao` (decisão registrada) e `extra` (dados próprios do módulo). `id` no formato `prev_<n>` e `previsao_id` numérico | O cartão precisa mostrar a decisão já tomada e dizer quando a confiança não é alta |
| Selo de qualidade | "acerta X% mais que a média histórica" | P1: "de cada 50 equipamentos que o modelo aponta, N falham; pela média histórica do tipo, M", mais o ganho de AUC. P2, P3 e P4: "erra X% menos que a média histórica", com o erro médio | A precisão nos 50 primeiros é o número que o gestor entende |
| Confiança | dizer abertamente quando é baixa | Alta (ganho ≥ 25% sobre o baseline), moderada (5% a 25%) ou baixa (< 5%), com o aviso no rodapé do cartão. Hoje P1 e P2 ficam em "moderada" | Honestidade: o ganho existe, mas boa parte do que acontece é acaso |
| Fatores no cartão | barras | Barras proporcionais, efeito em pontos percentuais (P1), ocorrências (P2) ou pontos do índice (P3); vermelho soma risco, verde reduz | — |
| Decisão | Aceitar, Ajustar, Rejeitar (com motivo) | `POST /previsoes/{id}/decisao` e `PATCH /recomendacoes/{id}`. Aceitar executa: abre a ordem de serviço preventiva (reaproveita a aberta, se houver) ou move os turnos na escala só no período recomendado (o resto do turno fica onde estava). Rejeitar exige motivo; ajustar exige o que mudou. Decidir duas vezes devolve 409; o PROMETHEUS não decide | O humano decide e tudo fica registrado (quem, quando, motivo, o que foi feito) |
| OS em lote | "abrir ordens de serviço preventivas" em lote | `POST /equipamentos/risco/ordens` com a lista de previsões | — |
| P4 sem trocas | — | Nova restrição: uma região não cede e recebe equipes no mesmo período | Na primeira tela, o otimizador trocava equipes entre duas regiões para aproveitar o tamanho delas; matematicamente válido, mas confuso para o gestor. Com a restrição, a redução do risco não coberto nas mesmas 72 h caiu de 52% para 46% |
| Tela "Amanhã" | mapa de 72 h com reprodução, faixa de regiões, recomendações, contexto editável, gráfico por região | `/amanha`, em tela cheia como a Central. Mapa das regiões pintado pelo índice da hora escolhida (controle deslizante e botão de reprodução); faixa de regiões ordenada pelo risco com o motivo; painel com as recomendações de reforço (cartões) e a aba da região (gráfico previsto, faixa de 90%, normal da hora e o que aconteceu nas horas passadas, mais os cartões dos períodos); linha de contexto com feriados, eventos e clima, com "Editar clima" e "Recalcular previsões" | — |
| Nomes no mapa | — | Sem rótulos de texto no mapa: o nome e o índice aparecem ao passar o mouse e na faixa de regiões | Rótulos do MapLibre exigem fontes baixadas de um servidor; a tela precisa funcionar sem internet |
| Recalcular | — | `POST /previsoes/recalcular` (gestor) refaz P2, P3 e P4 na hora | Depois de editar o clima ou cadastrar um evento, o gestor vê o efeito sem esperar a próxima hora |
| Outras telas | Equipamentos em risco; Planejamento de equipes | `/previsao/equipamentos` (ranking de 7 ou 30 dias, filtros por nível, tipo, região e código, seleção e OS em lote, cartão completo ao clicar) e `/previsao/equipes` (risco não coberto antes e depois, tabela por período e região, recálculo com limites ajustáveis, salvar como recomendações, aceitar ou rejeitar as pendentes) | Anomalias, Tendências, Cenários, Expansão, Confiança e Copiloto ficam para as fases seguintes |
| Ficha do equipamento | probabilidade na ficha | Seção "Risco de falha previsto" com os cartões de 7 e 30 dias | — |
| Score de saúde | P1 como novo fator do score | Não feito | O score é da Parte 1 e é recalculado a cada minuto; a probabilidade aparece ao lado dele, na ficha, sem mudar a regra já aprovada |

Testes novos: contrato completo na API, decisões (aceitar abre a OS; rejeitar exige motivo; ajustar; decidir duas vezes; o PROMETHEUS não decide), OS em lote, reforço aceito movendo o turno só no período, telas sem previsões; no frontend, o cartão sempre mostra os três títulos do enunciado, os botões e a decisão já tomada. Total: 197 testes no backend e 17 no frontend.

## Fase 9 (alertas preventivos, camada de risco, acertômetro e confiança)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| `PREVISAO_RISCO_REGIAO` | Alto ou Muito alto nas próximas 6 h | Último lote de P3 por hora; um alerta por região com a primeira hora em risco e o pico. Nível médio; Muito alto sobe para alto | Antecedência real: o alerta nasce quando a previsão sai, horas antes |
| `PREVISAO_FALHA_EQUIPAMENTO` | acima do limite e sem OS | P1 de 7 dias ≥ 25% (`prev_alerta_falha_prob`), equipamento operacional e sem OS aberta; no máximo os 15 de maior risco (`prev_alerta_falha_max`) | Com 20 mil equipamentos, sem teto a central seria inundada; o ranking completo fica na tela de risco |
| `PREVISAO_FALTA_AGENTES` | — | Período de P4 nas próximas 6 h em que a escala atual deixa pelo menos 20 agentes-hora e 30% da demanda descobertos, e o reforço ainda não foi aceito | Configurável (`prev_alerta_falta_*`) |
| `PREVISAO_DISPONIBILIDADE` | ao cruzar a meta | Feito na fase 12 (ver abaixo) | Depende de P6 |
| Visual | "previsto para...", antecedência, abre o cartão | Faixa "Previsão" com hora prevista e antecedência calculada na hora, borda tracejada e fundo próprio, botão "Ver previsão" (gaveta com o Cartão de Previsão); sem "Atribuir" | Não confundir com o que já está acontecendo |
| Saúde da região | — | Alertas preventivos não entram no índice de saúde da região | A saúde mede o presente |
| Resolução | — | Some a condição (período passou, risco baixou, OS aberta, reforço aceito): resolve sozinho. Roda depois de cada lote, a cada 5 minutos e logo depois de uma decisão | Mesmo ciclo de vida dos alertas da Parte 2 |
| Camada | "Risco previsto (próximas 6 h)" | Maior índice por hora de cada região nas próximas 6 h (`GET /risco-previsto`), tracejado na cor do nível; clique abre o cartão | — |
| Acertômetro (Q1) | toda previsão com valor real | `valor_real` conferido de hora em hora: P2 = ocorrências da região na hora; P1 = 1 se entrou em mau funcionamento na janela. P3 e P4 não têm um valor real único e herdam a qualidade de P2 | O índice e as equipes são decisões compostas, não contagens |
| Baseline no acertômetro | — | Para P2, a média da mesma hora e dia da semana em 8 semanas já guardada na previsão (`normal`) | A comparação usa o baseline que existia no momento da previsão |
| Tela "Confiança dos modelos" | — | `/previsao/confianca`: selo e métricas modelo × baseline (e × logística em P1), backtest semana a semana, calibração de P1, o que mais pesa, P3/P4/P5 explicados, acertômetro com previsto × real nas últimas 48 h e por antecedência, região e dia; aviso de amostra pequena | — |
| Agendador | P2, P3, P4 de hora em hora; P1 às 5 h | Igual (minuto 3 de cada hora; 5h10 locais). No start, refaz o que ficou atrasado | — |
| Primeiro start | gera e treina em < 5 min, com progresso | Se não há modelo, a API treina numa thread (cerca de 3 min) e as telas mostram a etapa (`GET /modelos/treino`). `POST /modelos/treinar` (gestor) retreina | O `--reload` do desenvolvimento mata a thread: o estado guarda o processo e um treino órfão é refeito no próximo start |
| Artefatos | — | Se o caminho gravado não existe (treinado em outro contêiner), procura pelo nome na pasta dos modelos | Portabilidade entre máquina e contêiner |

## Fase 10 (retorno das recomendações, padrões descobertos e cenários)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| C5: registro | decisões registradas | Já vinha da fase 8 (quem, quando, motivo, o que foi executado). Nova tela `/previsao/decisoes` com o histórico, a taxa de aceitação por tipo e os motivos de rejeição | — |
| C5: resultado comparado | resultado comparado | De hora em hora, quando o período termina, `recomendacao.resultado.retorno` guarda: no reforço de equipes, ocorrências registradas × previstas no destino; na OS preventiva, se o equipamento falhou dentro da janela (depois da decisão) e se a OS foi concluída. A tela compara aceitas × rejeitadas (`GET /recomendacoes/retorno`) | A comparação é observacional (o gestor não decide ao acaso), e a tela diz isso. Mais agentes também tendem a registrar mais ocorrências, o que a tela avisa |
| Q2: método | SHAP agregado, dependência parcial | O modelo pronto é interrogado: em P1, contrafactuais nos equipamentos reais (uma variável por vez), com curvas de dependência parcial (idade da câmera, temperatura do radar, atraso da preventiva); em P2, perfil previsto × real das últimas 4 semanas e contrafactuais de chuva, evento e véspera. A importância agregada (SHAP) já aparece na tela de confiança | Contrafactual dá um número comparável à regra plantada ("3,4× depois de 24 meses" contra "3× depois de 18 meses") |
| Q2: padrões sem modelo | — | 6 (furtos) e 11 (disponibilidade) por consulta direta, até P7 e P6 existirem (fase 12); 12 pelos alertas de P5. Cada linha diz como foi conferido | Honestidade sobre o que é aprendido e o que é contado |
| Q2: resultado | relatório de descoberta | `docs/parte3/relatorio-descoberta.md` (gerado por `python -m scripts.relatorio_descoberta`) e a seção na tela de confiança. No banco de desenvolvimento: 9 encontrados, 1 com sinal fraco (padrão 5) | O padrão 5 vale só em dias acima de 32 °C, que são poucos; com variáveis semanais de temperatura e horizonte de 7 dias, o modelo vê um efeito diluído (1,2× na rodovia contra 1,1× no urbano) |
| C1: mudanças | evento, clima, equipes, derrubar equipamentos, manutenções; salvar e nomear | Todas, combináveis, mais cancelar evento programado. `POST /cenarios/simular` não grava nada; `POST /cenarios` salva com nome o pedido e o resultado; `GET /cenarios`, `GET/DELETE /cenarios/{id}`, `GET /cenarios/opcoes` | — |
| C1: método | — | Fontes copiadas e alteradas em memória; P2, P3 e P4 rodam duas vezes (sem e com a mudança) da mesma hora, com os mesmos modelos (cerca de 5 s). A preventiva simulada recalcula a probabilidade de falha pelo modelo de P1 | A diferença é só da mudança |
| C1: equipes e ocorrências | — | Mudar o número de equipes não muda as ocorrências previstas: só o índice de risco (componente de agentes) e o risco não coberto | O modelo aprendeu que mais agentes registram mais ocorrências (viés de registro). Usar isso num cenário diria que tirar equipes "reduz ocorrências", o que é falso |
| Tabela `cenario` | — | Migração 0006, reversível | — |

## Fase 11 (briefing diário e copiloto)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| C4: quando | às 6 h | Agendador às 6 h (horário local); se a API sobe depois das 6 h sem o briefing do dia, ele é gerado no start. `GET /briefing/hoje` gera na hora se faltar; `POST /briefing/gerar` (gestor) refaz | — |
| C4: conteúdo | Markdown, com acertômetro | Seções: resumo, onde e quando o risco é maior hoje, reforços para decidir, manutenção preventiva, anomalias, contexto do dia (feriado, eventos, chuva), acertômetro de ontem (ocorrências previsto × real contra a média histórica, falhas do lote em andamento, decisões de ontem). Cada item que vem de uma previsão leva o id do cartão. Guardado na tabela `briefing` (migração 0007) com as seções e o Markdown; a tela `/previsao/briefing` mostra e baixa o `.md` | Montado só com dados do sistema, sem IA: sai igual todo dia e funciona sem internet |
| C3: com IA | copiloto com ferramentas que chamam a API | Loop de ferramentas com o Claude (`claude-opus-5-5`, esforço médio, fallback do servidor ligado), 9 ferramentas estritas que leem as mesmas consultas da API: risco por região, ocorrências previstas, equipamentos em risco, reforços, anomalias, alertas preventivos, qualidade dos modelos, contexto do dia e simulação de cenário. A resposta cita `[prev_N]` e a tela abre o cartão | As ferramentas chamam as funções internas (as mesmas dos endpoints), não HTTP: menos latência e nenhuma credencial a mais |
| C3: sem IA | modo sem LLM com perguntas prontas | 8 perguntas prontas respondidas por regras sobre as mesmas consultas (incluindo dois cenários prontos: chuva forte amanhã de manhã, 2 equipes a menos no Centro). Texto livre sem IA é associado a uma pronta por palavras-chave; sem correspondência, a resposta lista as prontas. Se a IA falhar, cai para esse modo e a tela diz por quê | A demonstração não depende de internet nem de chave |
| C3: limites | — | Só lê e simula; não decide nem grava; instrução de nunca falar de pessoas; até 8 passos de ferramenta por pergunta | Princípios 4 e 5 |
| Testes dependentes do relógio | — | Os testes do banco gerado passam a olhar só o lote de previsões mais recente e a avaliar P5 na data de referência do gerador | Uma suíte longa cruza a virada da hora (dois lotes de previsão); e, por medianas, uma anomalia que já dura mais da metade da janela de referência (cerca de 29 dias) vira o "novo normal" do equipamento. No banco de demonstração, gerado no dia da subida, as anomalias plantadas continuam visíveis por pelo menos 28 dias |

## Fase 12 (tendência de disponibilidade, risco de furto, carga de manutenção e expansão)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| P6: modelo | ETS 30/90 dias por tipo e região | ETS com tendência amortecida sobre as **médias semanais** das últimas 52 semanas, por região, cidade e tipo (fixos). Backtest de origem móvel em 30 e 90 dias contra a última média móvel de 30 dias | Na série diária, o ETS perde para a média móvel (o ruído do dia a dia domina). Na média semanal, ganha: no banco de desenvolvimento, erro de 0,45 × 0,47 ponto em 30 dias (3%, confiança baixa, dito no cartão) e 0,47 × 0,69 em 90 dias (32%); na Leste, que cai de verdade, 0,99 × 2,14 em 90 dias |
| P6: faixa | — | Erro absoluto de 90% do próprio modelo no backtest (conformal), interpolado de 0 (hoje) até 30 e 90 dias | Sem suposição de distribuição |
| P6: cenários | "se nada mudar" e "seguindo P1" | "Seguindo P1": as preventivas dos equipamentos de risco alto (P1 em 30 dias) evitam `prev_p6_eficacia_preventiva` (50%) das falhas esperadas deles; cada falha evitada deixa de tirar o equipamento de serviço pelo tempo médio de conserto da região nos últimos 90 dias, com rampa | 50% vem do próprio histórico: preventiva atrasada dobra o risco (padrão 7). É uma conta explicada, não um segundo modelo |
| P6: alerta | `PREVISAO_DISPONIBILIDADE` ao cruzar a meta | Região cuja previsão de 30 dias fica abaixo da meta (`saude_meta_disponibilidade`, 90%) em até `prev_alerta_disponibilidade_dias`; diz também onde ficaria seguindo o P1. Resolve sozinho quando a previsão volta para cima | — |
| P6: ação | — | `PRIORIZAR_MANUTENCAO`: aceitar abre OS preventiva (prioridade alta) para até 20 equipamentos de risco alto da região sem OS | O gestor decide; o sistema executa |
| P7: modelo | densidade espaço-temporal, cobertura de câmeras, agentes | LightGBM regularizado com furtos no bairro (90 e 365 dias) e a menos de 500 m, vandalismo de madrugada no bairro, distância até a câmera em operação mais próxima, agentes de madrugada na região, tipo e idade. **Restrição monótona**: mais furtos ou vandalismo por perto e câmera mais longe nunca reduzem o risco. Baseline: taxa histórica de furto do tipo | Furto é raro (cerca de 20 por mês). Sem a restrição, o modelo aprendia degraus sem sentido na distância da câmera e o contrafactual da expansão saía com o sinal trocado. AUC no backtest: 0,733 com a restrição, 0,746 sem, 0,59 o baseline |
| P7: hora | furtos de madrugada | O modelo é mensal e não tem hora; a madrugada aparece na descoberta por consulta e na ação ("ronda de madrugada") | A unidade da previsão é o equipamento em 30 dias |
| P7: ação | — | `INCLUIR_RONDA_NOTURNA` (registrada; quem executa é a operação) e, sem câmera a menos de 300 m, aponta a tela de Expansão | — |
| P8: método | falhas esperadas + preventivas por semana, tipo e região; técnicos-dia e peças | Corretivas = P1 de 7 dias na 1ª semana e o restante do P1 de 30 dias nas outras três; mais os equipamentos já parados; preventivas do plano na semana e as atrasadas divididas pelas 4 semanas (plano de zerar o atraso). Horas por tipo e kits de reparo por corretiva em configuração (`prev_p8_*`). Normal: horas executadas por semana nas últimas 8 semanas | Sem modelo próprio: P8 é uma soma explicável. A qualidade vem do backtest de P1 em 30 dias somado por tipo e região: erro de 4,35 falhas × 6,30 da taxa do tipo (31% melhor) |
| C2: método | expansão | Grade de 400 m; para cada célula sem câmera a menos de 300 m: ocorrências por mês ponderadas pela gravidade que passariam a ter câmera, e furtos evitados pelo contrafactual de P7 (os equipamentos a menos de 300 m com a câmera nova). Critérios: combinado (50/50, cada um em relação às melhores células), só ocorrências ou só furtos; 800 m entre sugestões; só câmeras | Uma escala única entre "ocorrência" e "furto" seria arbitrária; o gestor escolhe o critério e vê os dois números |
| Treino | — | `treinar --todos` inclui P6, P7 e P8 (cerca de 40 s a mais). Num banco treinado antes da fase 12, o start da API treina só o que falta, em segundo plano | Não obriga a retreinar tudo |
| Agendador | P6, P7, P8 às 5 h | Junto com P1 (5h10) | — |
| Descoberta (Q2) | — | Padrão 6 agora pelo P7 (bairros de maior risco previsto e contrafactual da câmera); padrão 11 pela tendência do P6 | Antes eram consultas diretas |
| Telas | Tendências, Expansão | `/previsao/tendencias` (disponibilidade com gráfico observado, previsto, faixa, meta e "seguindo P1"; carga de manutenção por semana e região), `/previsao/furtos` (ranking, bairros, cartão), `/previsao/expansao` (mapa e motivos). Ficha do equipamento mostra também o cartão de furto | — |

## Fase 13 (extras)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| X1 rotativo, X2 patinetes | extras | **Não feitos** | Os padrões 9 e 10 não foram plantados (decisão da fase 0); sem eles, os modelos não teriam o que mostrar |
| X3 fim de vida útil | — | `GET /equipamentos/fim-de-vida` e tela `/previsao/fim-de-vida`. Junta idade × vida útil do tipo (configuração `prev_x3_vida_util_anos`), falhas e dias parado no último ano, e o P1 de 30 dias como está e "como se fosse novo" (contrafactual: idade de um mês, sem falhas, preventiva em dia). Recomenda trocar se passou da vida útil, ou se a troca reduz o risco em 15 pontos e ele ficou 30 dias parado no ano | Separa desgaste de azar. No banco de desenvolvimento, as câmeras Hikvision antigas dominam a lista (padrão 4), sem que a regra conheça a marca |
| X4 monitor de modelos | — | `GET /modelos/monitor`, seção na tela de confiança e no relatório semanal. Por modelo: idade do treino (retreinar depois de 30 dias), desempenho das previsões conferidas contra o baseline comparado com o backtest, e deriva dos dados (ocorrências por hora, falhas por mil equipamentos, furtos por mês) contra o período de treino. Com menos de 3 dias de horas conferidas, P2 vai no máximo para "atenção" | Não retreina sozinho: o gestor decide. Amostra pequena não deve disparar retreino |
| X5 relatório semanal | — | `GET /relatorio/semanal` (e `.md`), aba na tela do briefing. Mesmo formato do briefing: acertômetro da semana, decisões e retorno, alertas preventivos e anomalias, tendências (P6, P8, P7, fim de vida) e saúde dos modelos | Gerado sob demanda, sem IA, sem tabela nova |
| X6 modo apresentação | — | Botão "Apresentar" (ou `?apresentar` na URL): painel com o roteiro da demonstração, o que mostrar e o que dizer em cada passo; navega sozinho para a tela do passo. PageDown e PageUp avançam e voltam (as teclas que os passadores de slide enviam); Esc recolhe | Setas conflitariam com o controle de horário da tela "Amanhã" |
| X7 ética e limites | página | Tela `/previsao/etica` e `docs/parte3/etica-e-limites.md` | — |

## Fase 14 (documentação e roteiro)

| Ponto | Especificação | Implementado | Motivo |
|---|---|---|---|
| Documentos | README, `previsoes.md`, `roteiro-demo.md`, `docs/uso-de-ia.md` | Os quatro; o README ganhou a seção completa da Parte 3 (modelos, telas, API, documentos) | — |
| Roteiro, passo 3 | "+2 equipes da Zona Sul" | O roteiro não fixa a origem nem o número de equipes | Saem da otimização com a escala do dia; fixar no texto faria a demonstração contradizer a tela |
| Roteiro, passo 2 | "Amanhã" sexta 20 h | O show do Pacaembu cai na primeira sexta depois da criação do banco; o roteiro manda criar o banco de 1 a 3 dias antes, ou cadastrar o show pela API e recalcular | A tela mostra 72 h |
| Roteiro, passos 6 e 7 | separados | Um passo só, na central | Anomalia e alerta preventivo ficam na mesma tela |
| Números dos documentos | — | `previsoes.md`, README e `relatorio-descoberta.md` refeitos com o banco de demonstração criado em 27/10 (antes eram do banco de desenvolvimento) | Os jurados veem o banco de demonstração. Mudanças: P4 reduz o risco não coberto em 48% (antes 63%); P7 tem AUC 0,63 × 0,53 (antes 0,73 × 0,59), porque furto é raro e poucos casos mudam a métrica; o padrão 5 passou de "sinal fraco" para "não encontrado" (efeito 1,2× tanto na rodovia quanto no urbano) |
| Roteiro, passo 2 (conferido no banco de demonstração) | Centro "Muito alto" na sexta às 20 h | Centro em risco **alto**: índice 69,5 às 18 h (pico) e 61 às 20 h; o roteiro aponta sexta, 18 h | O modelo não foi ajustado para o roteiro: com 38 mil pessoas, o índice fica no alto. Forçar "muito alto" contrariaria o princípio de mostrar a previsão como ela é |
