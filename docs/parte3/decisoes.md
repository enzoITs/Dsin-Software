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
