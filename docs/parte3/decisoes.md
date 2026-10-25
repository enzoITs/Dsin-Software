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
