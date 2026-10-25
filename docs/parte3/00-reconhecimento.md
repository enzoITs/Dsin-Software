# Parte 3 — Fase 0: Reconhecimento

Levantamento feito em 25/10/2026 sobre o repositório e o banco do compose (seed gerado em 17/10/2026). Nenhum código de produção foi escrito.

**Resumo em quatro linhas**

1. A base das Partes 1 e 2 está sólida e serve para a Parte 3: 20 mil equipamentos, 57 mil mudanças de situação, 14 mil manutenções, motor de regras extensível, canal de eventos, mapa, APScheduler e IA com alternativa sem IA. Testes: 112 no backend e 13 no frontend, todos passando.
2. **O histórico atual é ruído puro.** As falhas se distribuem igualmente por hora, dia da semana, mês e marca. Nenhum modelo aprende algo com ele. O gerador com padrões plantados (Fase 2) é pré-requisito de tudo.
3. Faltam dados inteiros: ocorrências da cidade, clima, calendário, eventos, escala de agentes, histórico de sinais, contagem de infrações, posições históricas. Todos precisam ser sintetizados.
4. **O prazo é o maior risco:** a entrega é em cerca de 2 dias (27/10). O Núcleo completo (12 módulos) não cabe com qualidade nesse tempo. Na seção 5 proponho um Núcleo enxuto e a ordem de corte.

---

## 1. Stack real

| Camada | Tecnologia e versão |
|---|---|
| Backend | Python 3.12 (imagem `python:3.12-slim`, instalado com `uv`), FastAPI ≥ 0.115, SQLAlchemy 2, GeoAlchemy2, Alembic, Pydantic 2, APScheduler 3.x, httpx, Faker, Shapely 2, `anthropic` |
| Banco | PostgreSQL 16 + PostGIS 3.4 (`postgis/postgis:16-3.4`), porta 5433 no host |
| Canal de eventos | Redis 7 (pub/sub, opcional; sem ele, entrega em memória) + WebSocket `/ws/eventos` |
| Frontend | React 18, Vite 5, TypeScript 5.6, Tailwind 4.1, TanStack Query 5, Zustand 4, MapLibre 4.7, Recharts 2.13, @turf/circle, lucide-react |
| Testes | pytest (banco separado `atalaia_test`), vitest |
| IA | Claude (`claude-opus-5-5`) via `app/services/ia.py::_chamar`; sem chave, modo texto |
| Orquestração | `docker-compose.yml` com `db`, `redis`, `api` (hot reload), `simulador`, `web`. Na máquina de desenvolvimento roda com Podman |

Ainda **não há** pandas, NumPy, scikit-learn, LightGBM, statsmodels, SHAP, PuLP nem `holidays`. Todas têm wheels para Python 3.12 e funcionam offline depois de instaladas (o PuLP já traz o CBC). Custo estimado: cerca de 350 a 450 MB a mais na imagem do backend.

Estado do git: branch `main` **sem nenhum commit**. Tudo das Partes 1 e 2 está fora do controle de versão (ver pergunta 1).

Estrutura relevante:

```
backend/app/domain/      regras puras (saude.py, disponibilidade.py, limites.py, estados.py, catalogo.py)
backend/app/services/    motor.py (regras), central.py (consultas da central), simulacao.py, ia.py, resumo.py, barramento.py
backend/app/routers/     equipamentos, tipos, agentes, operacao, alertas, central, simulador, ia
backend/app/jobs.py      APScheduler: recálculo a cada 1 min, verificador do motor a cada 30 s
backend/scripts/         seed.py, preparar_central.py, simulador_telemetria.py
backend/alembic/         0001_inicial, 0002_central
frontend/src/central/    mapa, camadas, ficha, alertas, regiões, linha do tempo
```

---

## 2. Inventário de dados históricos

| Tabela | Volume | Período | Granularidade | Qualidade e observações |
|---|---|---|---|---|
| `equipamento` | 20.000 (CAM 5.677, RAD 2.844, TOT 2.783, PAT 2.483, VTR 2.328, MOT 1.211, VIA 1.158, CAN 770, VAF 373, BAL 373) | instalação de 10/2019 a 09/2026 | 1 linha por equipamento | Boa. Tem marca, modelo, idade, órgão, score com motivos. Cerca de 0,4% de duplicidades plantadas de propósito (marca em maiúsculas), que precisam ser normalizadas antes de virar variável |
| `historico_situacao` | 57.176 (33 mil operacional, 14,6 mil em manutenção, 7,9 mil mau funcionamento, 788 furtado, 568 desativado) | 10/2019 a 17/10/2026; cerca de 1.150 por mês nos últimos 18 meses | evento com timestamp | Coerente com a máquina de estados, **sem nenhum padrão** (ver seção 3). Somente inserção: um trigger recusa UPDATE e DELETE |
| `registro_manutencao` | 13.859 | 04/2021 a 10/2026 | evento | Só existe quando o equipamento sai de "em manutenção" para "operacional". **Não há registro das preventivas periódicas executadas**, então não dá para reconstruir o atraso de manutenção no passado |
| `plano_manutencao` | 19.873 (18.841 periódicos, 1.032 imediatos) | próxima data de 08/2026 a 10/2027 | estado atual | Só a próxima data. Sem histórico de datas anteriores |
| `ordem_servico` | 1.032 | 08 a 10/2026 | evento | Só as imediatas do seed |
| `alerta` | 5.284 (3.479 manutenção vencida, 1.472 próxima, 324 falha silenciosa, 6 incidentes, 3 furtos) | 17 a 24/10/2026 (uma semana) | evento | Curto demais para treinar. Útil como alvo da Central, não como histórico |
| `instantaneo` | 241 | 24/10/2026, 4 horas | 1 por minuto | Indicadores e regiões. Serve para a linha do tempo, não para treino |
| `agente` | 1.333 em 45 equipes, 5 regiões | estado atual | — | Sem escala e **sem histórico de posições** (só a última) |
| `regiao` / `bairro` | 5 regiões, 28 bairros (polígonos de Voronoi) | — | — | Região só tem 5 unidades: pouco para P2 e P3 |
| Sinais de telemetria | não guardados | — | — | Só o estado atual: `ultimo_sinal_em`, `metricas` (qualidade da câmera, bateria). Sem série histórica |
| Ocorrências da cidade, clima, calendário, eventos, escala, infrações por radar, ocupação do rotativo, uso de patinetes | **não existem** | — | — | Precisam ser criados e sintetizados |

Detalhe que afeta a reprodutibilidade: o seed calcula tudo a partir de `datetime.now()` no momento em que roda. Mesma semente em dias diferentes gera datas diferentes. O gerador da Parte 3 precisa de uma **data de referência** explícita (parâmetro, gravada no banco) para que "mesma semente, mesmos dados" seja verdade.

---

## 3. Diagnóstico do simulador e do seed

**Conclusão: os dados atuais são aleatórios, sem padrão. Um modelo treinado neles não aprende nada.** Consultas que comprovam:

| Teste | Resultado |
|---|---|
| Falhas (mau funcionamento) por hora do dia | 296 a 359 em todas as 24 horas, plano |
| Falhas por dia da semana | 1.087 a 1.185, plano |
| Mudanças de situação por mês (últimos 18 meses) | cerca de 1.150 por mês, plano. O pico de 08 a 10/2026 é efeito colateral do seed, que força a última transição para os últimos 60 dias |
| Falhas por câmera, por marca | Axis 0,39; Bosch 0,41; Hikvision 0,44; Intelbras 0,41: iguais |
| Falhas por idade, chuva ou temperatura | Não testável: não existe clima, e a quantidade de falhas é sorteada (0 a 3) independentemente da idade |

Como o seed gera o histórico: sorteia o estado final, sorteia de 0 a 3 ciclos de "falha → manutenção → operacional" e espalha esses eventos em intervalos iguais entre a instalação e hoje. Nada depende de marca, idade, clima, local ou manutenção.

Simulador de telemetria (`scripts/simulador_telemetria.py`): a cada 60 s manda presença e métricas; a cada 15 s, posições de móveis e agentes em passeio aleatório. 1% dos módulos fica sempre mudo (por hash do código). Com `--eventos`, gera falhas e furtos aleatórios. Também sem padrão temporal ou espacial.

`simulacao.py` (botão "Simular incidente") cria cenários pontuais (furto, falha, silêncio, queda de energia, degradação, região sem agentes) para a demonstração. É útil para a Parte 3 como gatilho de anomalias, mas não gera histórico.

---

## 4. Lacunas e como preencher

| Lacuna | Como preencher |
|---|---|
| Histórico de falhas sem padrão | O gerador recria o histórico de falhas e manutenções dos últimos 18 meses com os padrões 4, 5, 7 e 11. Como `historico_situacao` não aceita DELETE, a forma limpa é **o seed da Parte 1 chamar o gerador** para a vida de cada equipamento e recriar o banco (`compose down -v`). Ver pergunta 2 |
| Preventivas executadas e atrasos no passado | O gerador grava as preventivas executadas em `registro_manutencao` (com `plano_id`) e algumas com atraso. Assim "dias de atraso na data T" passa a ser calculável |
| Ocorrências da cidade | Nova tabela `ocorrencia` com 12 a 18 meses gerados (padrões 1, 2, 3, 6, 8). Estimativa de 150 a 250 mil linhas |
| Clima | `clima_hora` sintética (cerca de 13 mil horas), coerente com a estação de São Paulo: verão chuvoso à tarde, inverno seco e frio. Futuro editável |
| Calendário | `calendario` com a biblioteca `holidays` (BR, SP, São Paulo capital), funciona offline |
| Eventos | `evento_cidade`: jogos e shows em locais fixos (estádios, arenas), alguns acima de 10 mil pessoas. Cerca de 300 no período |
| Escala de agentes | `escala_agente` sintética a partir das 45 equipes: turnos por região. Base de P4 e da variável de exposição |
| Agentes presentes por região no passado | Derivado da escala gerada (não há histórico de posição). Vai para `ocorrencia.agentes_presentes_regiao` |
| Séries para anomalias (padrão 12) | Nova tabela agregada `serie_equipamento_hora` (ou diária) para um subconjunto: infrações por radar e disponibilidade por câmera. Gerar só para algumas centenas de equipamentos, para não explodir o volume |
| Rotativo e patinetes (padrões 9 e 10) | Só se X1 e X2 entrarem. Proponho deixar de fora (seção 5) |
| Granularidade espacial | 5 regiões é pouco para P2. Proponho prever por **bairro** (28) e agregar para região. O mapa pinta bairros, e a faixa lateral mostra regiões |
| Volume de equipamento × dia | 12,6 mil fixos × 540 dias ≈ 6,8 milhões de linhas, pesado para treinar em menos de 5 minutos. Proponho **equipamento × semana** (cerca de 1 milhão de linhas, alvo "falha nos próximos 7 dias") e para 30 dias a mesma base com outro alvo |
| Datas relativas a `now()` | Data de referência fixa, gravada numa tabela de metadados do gerador |

---

## 5. Plano adaptado

### Decisões de arquitetura propostas

- **Serviço preditivo como pacote do backend** (`backend/app/preditivo/`), reaproveitando modelos, sessão e configuração. Não um FastAPI separado.
- **Novo serviço no compose, `preditivo`**, com a mesma imagem: na primeira subida roda o gerador e o treino (com progresso gravado no banco e mostrado na interface) e depois executa as previsões em lote pelo APScheduler. Assim a `api` não trava treinando, e o hot reload continua funcionando.
- Previsões gravadas na tabela `previsao`; a API só lê. A previsão sob demanda (cenários) roda na `api` carregando os artefatos com joblib.
- Artefatos em `backend/modelos/` (fora do git, regeneráveis). Treinar na primeira subida, em vez de versionar artefatos: o histórico depende da data de referência, e treinar leva poucos minutos.
- Novas regras `PREVISAO_*` e `ANOMALIA_*` entram como novos valores de `TipoAlerta` no motor existente (migração aditiva do enum), reaproveitando `abrir`/`resolver` e o barramento.
- Fuso: dados em UTC, variáveis de hora e dia em `America/Sao_Paulo` (o `local()` da central já faz isso).
- Pesos e limites da Parte 3 no mesmo mecanismo de `limites.py` / `config_motor`.

### Fases e esforço relativo

Esforço em unidades relativas (1 = pequeno, 5 = grande). O total do Núcleo dá cerca de 35 unidades, o que **não cabe** em 2 dias com qualidade.

| Fase | Entrega | Esforço | No plano enxuto |
|---|---|---|---|
| 1 | Migração 0003: ocorrência, categorias, calendário, clima, evento, escala, previsão, recomendação, modelo_versao, backtest; botão "Registrar ocorrência" na Central | 3 | Sim, sem cenário e briefing |
| 2 | Gerador determinístico, 12 a 18 meses, com os padrões 1 a 8, 11 e 12 (sem 9 e 10); integração ao seed; testes dos padrões | 5 | Sim. É o coração da demonstração |
| 3 | Variáveis sem vazamento, baselines, backtest de origem móvel | 3 | Sim |
| 4 | P1 (LightGBM + calibração + SHAP traduzido) | 3 | Sim |
| 5 | P2 por bairro e hora (Poisson, intervalos por quantis) + P3 | 4 | Sim |
| 6 | P4 (demanda + PuLP, heurística gulosa de reserva) | 3 | Sim, versão simples |
| 7 | P5: três detectores | 3 | Só o de equipamento e o de região |
| 8 | Contrato, Cartão de Previsão, tela "Amanhã", ranking de risco, planejamento de equipes | 5 | Sim. Planejamento entra como painel dentro de "Amanhã" |
| 9 | Alertas preventivos, camada na Central, acertômetro, tela de confiança | 4 | Sim; acertômetro sobre o backtest e as previsões conferidas |
| 10 | C5, Q2, C1 | 4 | Q2 sim (é o argumento da demo); C5 já vem do aceitar/rejeitar; C1 só se sobrar |
| 11 | C4, C3 | 3 | C4 em modo texto se sobrar; C3 reaproveitando o "Perguntar" da Parte 2 |
| 12 | P6, P7, P8, C2 | 4 | Não |
| 13 | Extras | — | Só X7 (página de ética, quase só texto) |
| 14 | Documentação e roteiro | 2 | Sim, obrigatória |

Ordem de corte se o tempo apertar, do primeiro a sair ao último: C3 → C4 → C1 → detector de operação de P5 → otimização de P4 (fica só a heurística) → intervalos conformais (ficam só quantis). Não corto o gerador, P1, P2/P3, Cartão, "Amanhã", alertas preventivos e Q2.

---

## 6. Perguntas

1. **Git:** o repositório não tem nenhum commit. Posso fazer um commit inicial com as Partes 1 e 2, como estão, antes de começar? Sem isso, a regra "commit por fase" não tem base.
2. **Recriar o banco:** para o histórico ter padrões, a forma limpa é o seed da Parte 1 usar o gerador e recriar o banco (`compose down -v`, o que apaga os dados atuais da demonstração). A alternativa, sem apagar, é deixar o histórico atual intocado e gravar o histórico com padrões em tabelas novas, usadas só pela Parte 3. Isso deixa duas verdades no banco e a ficha do equipamento contaria uma história diferente da previsão. Recomendo recriar. Pode?
3. **Escopo:** com cerca de 2 dias até a entrega, aprova o **plano enxuto** da seção 5? Ou o prazo mudou?
4. **Unidade espacial:** posso prever por bairro (28) e agregar para as 5 regiões, em vez de prever direto por região?
5. **Padrões 9 e 10** (rotativo e patinetes) só servem aos extras X1 e X2. Posso tirá-los do gerador?
6. **Dados de agentes no tempo:** como não há histórico de posição, a presença passada de agentes por região vem da escala sintética. Aceitável?
7. **Imagem maior:** a Parte 3 acrescenta cerca de 400 MB à imagem do backend (LightGBM, SHAP, statsmodels, PuLP). Sem problema para a máquina do jurado?
