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
