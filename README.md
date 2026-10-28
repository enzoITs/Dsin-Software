# Atalaia — Inventário, Central de Operações e Cidade Preditiva

- **Parte 1 — Inventário inteligente:** equipamentos de segurança e trânsito e agentes de campo, com formulário que muda conforme o tipo, máquina de estados com automações, score de saúde explicado e painel de qualidade.
- **Parte 2 — Central de operações:** uma tela única com mapa vivo, indicadores, alertas priorizados e situação de cada região, alimentada por um motor que interpreta cada sinal recebido. Responde à pergunta do enunciado: "se algo estiver acontecendo na cidade agora, PROMETHEUS conseguirá perceber?".
- **Parte 3 — Cidade Preditiva:** previsões de falha de equipamentos, ocorrências e risco por região, reforço de equipes, anomalias e tendências, cada uma explicada, comparada com uma referência simples e transformada numa ação que o gestor aceita ou rejeita.

Documentos de origem: `Atalaia — Parte 1 Inventário Inteligente da Cidade.pdf` e `Atalaia — Parte 2 Solução da Central de Operações.pdf`.

## Subir tudo com um comando

Requisitos: Docker com Compose (ou Podman com `podman-compose`).

```bash
cp .env.example .env        # opcional: coloque ANTHROPIC_API_KEY para ligar a IA
docker compose up --build   # ou: podman compose up --build
```

Na primeira subida o banco é criado, o seed gera 20 mil equipamentos com anos de histórico, a central faz a linha de base e o gerador da Parte 3 cria 18 meses de história da cidade com padrões plantados (cerca de 1 min 30 s no total).

| Endereço | O que é |
|---|---|
| http://localhost:5173/previsao/briefing | **Cidade Preditiva** (Parte 3): briefing do dia; o menu leva às demais telas |
| http://localhost:5173/amanha | Risco previsto das próximas 72 h (Parte 3) |
| http://localhost:5173/central | **Central de operações** (Parte 2) |
| http://localhost:5173/central?sala=1 | Modo sala de situação (tela cheia para TV) |
| http://localhost:5173 | Inventário (gestor, operadores, técnicos) |
| http://localhost:5173/campo | Modo campo (celular: QR Code, situação, manutenção com foto e GPS) |
| http://localhost:8000/docs | API documentada (OpenAPI) |
| localhost:5433 | PostgreSQL + PostGIS (usuário, senha e banco: `atalaia`) |

Serviços do compose: `db` (PostgreSQL + PostGIS), `redis` (canal de eventos), `api` (FastAPI, motor e verificador), `simulador` (telemetria) e `web` (React).

O `simulador` faz a cidade "respirar": a cada 60 s manda presença e métricas dos equipamentos fixos (qualidade da imagem das câmeras, bateria dos patinetes) e a cada 15 s a posição dos móveis e dos agentes. Cerca de 1% dos módulos fica sempre mudo, para existirem falhas silenciosas reais.

### Sem internet ou sem IA

| Serviço externo | Se não estiver disponível |
|---|---|
| IA (sem `ANTHROPIC_API_KEY` ou sem rede) | Botões de IA do inventário desligados com aviso; resumo do turno e "perguntar ao painel" usam modelo de texto; o copiloto da Parte 3 responde às perguntas prontas. Previsões, briefing e cenários não dependem de IA |
| ViaCEP | CEP é opcional; o endereço é digitado |
| Tiles do OpenStreetMap | Mapa com fundo neutro; pontos, grupos e ícones continuam (são desenhados no navegador) |
| Redis | A API entrega os eventos em memória, no próprio processo |
| Câmera do celular sem HTTPS | Leitura do QR Code por upload de foto ou digitando o código |

As imagens precisam ser baixadas uma vez com internet; depois tudo roda offline, inclusive o botão "Simular incidente".

## Perfis

Não há login. O seletor no topo escolhe o perfil, enviado à API em cabeçalhos (`X-Perfil`, `X-Orgao-Id`, `X-Usuario`):

- **Gestor municipal** vê tudo, cria e edita tipos e ajusta os limites do motor.
- **Operador do órgão** cadastra e edita só o próprio órgão; na central, age só em alertas do próprio órgão.
- **Técnico** usa o modo campo do próprio órgão.
- **PROMETHEUS** envia `X-Perfil: prometheus`: lê tudo, registra ocorrências e recebe eventos por webhook, mas não decide nem altera cadastros.

Sem cabeçalho, a API assume o perfil de gestor, para a demonstração funcionar sem configuração. Como não há login, a API não deve ser exposta fora da rede da prefeitura sem autenticação na frente.

---

## Parte 3 — Cidade Preditiva

A Central da Parte 2 vê o que está acontecendo agora; a Parte 3 prevê o que deve acontecer nas próximas horas e semanas, explica por quê e diz o que fazer. Cinco regras valem para tudo:

1. Toda previsão vira uma ação (quem, onde, quando, o quê).
2. Toda previsão se explica (fatores em linguagem simples, dados usados).
3. Toda previsão prova que funciona (comparada com uma referência simples e com o que aconteceu).
4. O humano decide (Aceitar, Ajustar, Rejeitar com motivo; tudo registrado).
5. Prevê lugares, períodos e equipamentos, nunca pessoas.

O que cada modelo prevê, com que dados, como ajuda e quanto acerta: **[docs/parte3/previsoes.md](docs/parte3/previsoes.md)**.

### Os modelos

| Módulo | O que prevê | Resultado contra a referência (backtest) |
|---|---|---|
| P1 | Chance de cada equipamento falhar em 7 e 30 dias | Dos 50 mais apontados na semana, 17% falham (média do tipo: 4%) |
| P2 | Ocorrências por região e hora, 72 h | Erro médio 1,25 × 1,34 (média da mesma hora em 8 semanas) |
| P3 | Índice de risco 0–100 por região e período | Composto de P1, P2, cobertura, escala e contexto |
| P4 | Reforço de equipes (otimização) | Risco não coberto 48% menor nas 72 h |
| P5 | Anomalias em equipamentos e regiões | 6 de 6 anomalias plantadas, nenhum alarme falso |
| P6 | Disponibilidade em 30 e 90 dias | Erro 34% menor em 90 dias |
| P7 | Risco de furto em 30 dias | AUC 0,63 × 0,53 |
| P8 | Carga de manutenção, 4 semanas | Erro 28% menor |

### As telas

| Endereço | O que é |
|---|---|
| http://localhost:5173/previsao/briefing | **Briefing diário** (6 h): risco do dia, reforços, manutenções, anomalias, contexto e o acertômetro de ontem; baixa em Markdown. Aba com o relatório semanal |
| http://localhost:5173/amanha | **Amanhã**: mapa de risco das próximas 72 h, recomendações e contexto (feriados, eventos, clima editável) |
| http://localhost:5173/previsao/equipamentos | Equipamentos em risco de falha (7 e 30 dias), com OS preventiva em lote |
| http://localhost:5173/previsao/equipes | Planejamento de equipes: escala atual × recomendada |
| http://localhost:5173/previsao/cenarios | **Cenários "e se"**: evento novo ou cancelado, chuva, equipes a mais ou a menos, equipamentos fora, preventivas; compara com hoje e salva com nome |
| http://localhost:5173/previsao/tendencias | Disponibilidade prevista por região ("se nada mudar" × "seguindo o P1") e carga de manutenção |
| http://localhost:5173/previsao/furtos | Risco de furto por equipamento e bairro |
| http://localhost:5173/previsao/expansao | Onde uma câmera nova cobriria mais ocorrências e evitaria mais furtos |
| http://localhost:5173/previsao/fim-de-vida | Trocar ou consertar: risco atual × "como se fosse novo" |
| http://localhost:5173/previsao/decisoes | **Decisões e retorno**: quem decidiu o quê e por quê, e o que aconteceu depois |
| http://localhost:5173/previsao/copiloto | **Copiloto**: perguntas em português respondidas com os dados do sistema; com `ANTHROPIC_API_KEY`, o Claude consulta as previsões por ferramentas; sem chave, perguntas prontas |
| http://localhost:5173/previsao/confianca | **Confiança dos modelos**: backtest contra a referência, calibração, o que pesa, padrões descobertos × plantados, acertômetro, monitor dos modelos e retreino |
| http://localhost:5173/previsao/etica | Ética e limites |

Toda previsão aparece num **Cartão de Previsão** com três partes fixas: "O que estamos prevendo", "Com base em quê" e "Como isso ajuda", mais a qualidade do modelo contra a média histórica, a confiança (dita abertamente quando é baixa) e os botões Aceitar, Ajustar e Rejeitar. Aceitar executa: abre a OS preventiva ou move o turno só no período recomendado.

Na central, os **alertas preventivos** (risco alto na região nas próximas 6 h, equipamento com alta chance de falhar e sem OS, falta de agentes prevista, disponibilidade abaixo da meta) e as **anomalias** aparecem com visual próprio ("Previsão · previsto para… · em 3 h") e o botão "Ver previsão" abre o cartão. A camada "Risco previsto (próximas 6 h)" pinta as regiões pelo índice previsto. Esses alertas não pesam na saúde atual da região e se resolvem sozinhos quando a condição some.

**Primeiro start:** se ainda não há modelo treinado, a API treina sozinha em segundo plano (cerca de 3 minutos) e as telas de previsão mostram o progresso. Depois, o agendador refaz P2, P3 e P4 de hora em hora (com os alertas preventivos, o acertômetro e o retorno das decisões), P1, P6, P7 e P8 às 5h10, P5 a cada 5 minutos e o briefing às 6 h.

**Demonstração:** botão **Apresentar** no topo; o roteiro completo, com a preparação, está em [docs/parte3/roteiro-demo.md](docs/parte3/roteiro-demo.md).

### Dados sintéticos e padrões plantados

**Os dados da Parte 3 são sintéticos.** O seed e o gerador criam 18 meses de história (falhas, furtos, manutenções, cerca de 174 mil ocorrências, eventos, clima, escala de agentes e séries de radares e câmeras) com padrões conhecidos, descritos em [docs/parte3/padroes-plantados.md](docs/parte3/padroes-plantados.md). Os modelos não leem essa descrição: precisam redescobrir os padrões. Resultado: 9 encontrados e 1 não encontrado (calor nos radares de rodovia: o modelo vê o efeito diluído), em [docs/parte3/relatorio-descoberta.md](docs/parte3/relatorio-descoberta.md).

```bash
podman compose exec api python -m scripts.verificar_padroes        # confere cada padrão com consultas diretas
podman compose exec api python -m scripts.gerar_historico --forcar # refaz o histórico da cidade (mesmos dados)
podman compose exec api python -m app.preditivo.treinar --todos   # retreina tudo na hora (o mesmo que "Retreinar agora")
podman compose exec api python -m scripts.relatorio_descoberta     # refaz docs/parte3/relatorio-descoberta.md
```

Mesma semente e mesma data de referência geram os mesmos dados. Depois da subida, o `simulador` continua a história no modo contínuo: a cada 5 minutos gera as ocorrências das horas que passaram, com os mesmos padrões e o clima gravado no banco (inclusive o editado pelo operador), e uma vez por hora aplica pela API falhas, furtos e consertos sorteados pelos mesmos padrões.

### API da Parte 3

```
GET   /previsoes | /previsoes/{id}        contrato completo (POST /previsoes/{id}/decisao decide)
POST  /previsoes/recalcular               refaz P2, P3, P4 e alertas na hora
GET   /amanha | /amanha/regioes/{id}      tela "Amanhã"
GET   /equipamentos/risco | /equipamentos/{id}/risco   (POST /equipamentos/risco/ordens: OS em lote)
GET   /planejamento/equipes               (POST .../recalcular)
GET   /recomendacoes | /recomendacoes/retorno          (PATCH /recomendacoes/{id})
GET   /anomalias                          (POST /anomalias/verificar)
GET   /tendencias/disponibilidade | /tendencias/manutencao | /furtos/risco | /expansao/sugestoes
POST  /cenarios/simular                   (GET/POST /cenarios, GET/DELETE /cenarios/{id})
POST  /copiloto/perguntar                 (GET /copiloto/perguntas-prontas)
GET   /briefing/hoje | /briefing/{data}   (POST /briefing/gerar) | /relatorio/semanal(.md)
GET   /modelos | /modelos/acertometro | /modelos/padroes-descobertos | /modelos/monitor | /modelos/treino
POST  /modelos/treinar
GET   /risco-previsto                     camada da central
GET   /equipamentos/fim-de-vida
GET   /ocorrencias | /eventos-cidade | /clima/previsao | /calendario | /escala   (POST/PUT para registrar e editar)
```

### Documentos da Parte 3

| Documento | Conteúdo |
|---|---|
| [previsoes.md](docs/parte3/previsoes.md) | O que cada modelo prevê, com que dados, como ajuda e quanto acerta |
| [roteiro-demo.md](docs/parte3/roteiro-demo.md) | Roteiro da demonstração e preparação |
| [padroes-plantados.md](docs/parte3/padroes-plantados.md) | Os padrões que o gerador planta e como conferir |
| [relatorio-descoberta.md](docs/parte3/relatorio-descoberta.md) | O que os modelos encontraram × o que foi plantado |
| [decisoes.md](docs/parte3/decisoes.md) | Decisões técnicas e divergências da especificação, fase a fase |
| [etica-e-limites.md](docs/parte3/etica-e-limites.md) | O que o sistema não faz e por quê |
| [00-reconhecimento.md](docs/parte3/00-reconhecimento.md) | Reconhecimento inicial e plano |
| [uso-de-ia.md](docs/uso-de-ia.md) | Como a IA foi usada no desenvolvimento e dentro do sistema |
| [fluxograma.html](docs/fluxograma.html) | Fluxograma do sistema e catálogo filtrável de todas as funções (abra no navegador) |

---

## Parte 2 — Central de operações

### A tela

Tudo cabe numa tela: o gestor nunca troca de página para entender a cidade ou agir.

| Área | O que mostra |
|---|---|
| Indicadores (topo) | Total, operacionais, indisponíveis, disponibilidade, agentes ativos, alertas abertos por nível, sem sinal, manutenções vencidas, tempo até reconhecer. Cada um com a variação na última hora |
| Filtros (esquerda) | Tipo, situação, região e bairro, órgão, criticidade, sem sinal, manutenção, score e área desenhada no mapa. Ficam no endereço da página (dá para salvar ou mandar a visão) e valem para tudo |
| Mapa (centro) | Equipamentos, agentes e regiões; grupos com a cor da pior situação; camadas de calor e de cobertura das câmeras; ficha lateral com um clique |
| Alertas (direita) | Críticos fixos no topo, depois por nível; reconhecer, atribuir agente, abrir OS, silenciar, resolver. Aba de manutenção com a fila |
| Regiões (rodapé) | Da pior para a melhor: nota, estado, motivo principal, disponibilidade e agentes ativos. Clicar aproxima o mapa e aplica o filtro |

Ferramentas no topo: **Simular incidente**, **Resumo do turno**, **Perguntar** ("o que está acontecendo no Centro?"), **Linha do tempo** (volta o mapa até uma hora atrás) e **Sala de situação**.

### Motor de interpretação

Todo sinal passa pelas mesmas sete etapas (`backend/app/services/motor.py`): recebe, liga ao cadastro pelo `dispositivo_iot_id`, atualiza o estado atual (último sinal, posição, métricas), aplica as regras, calcula a criticidade com o contexto, cria ou atualiza o alerta (repetição só soma um contador) e publica o evento depois do commit. Um verificador a cada 30 s cuida do que não chega como sinal: silêncio, prazos de manutenção, agentes sem posição, regiões sem agentes e escalonamento.

| Regra | Dispara quando | Nível inicial |
|---|---|---|
| Furto | Situação muda para furtado, ou fixo manda posição a mais de 50 m do ponto de instalação | Crítica |
| Incidente correlacionado | 3 ou mais equipamentos com problema na mesma região em 15 min | Crítica |
| Mau funcionamento | Sinal de erro do dispositivo ou mudança de situação feita por técnico | Alta |
| Falha silenciosa | Operacional sem sinal há mais de 3 vezes o intervalo do tipo | Alta |
| Região descoberta | Região sem nenhum agente em atividade | Alta |
| Sinal degradado | Câmera com qualidade abaixo de 60% ou patinete com bateria abaixo de 15% | Média |
| Manutenção vencida | Data do plano passou sem execução | Média |
| Dispositivo não cadastrado | Sinal de um módulo que não existe no inventário | Média |
| Agente sem posição | Em atividade sem atualizar posição há mais de 10 min | Média |
| Manutenção próxima | Faltam 7 dias ou menos | Baixa (só na fila e na ficha) |

**Contexto** (cada fator sobe um nível, e o alerta mostra o porquê, ex.: "Alta → Crítica: sem outra câmera operacional em 500 m"): nenhum outro do mesmo tipo operacional e sem problema num raio de 500 m; região já em atenção; horário de pico da região. Manutenção planejada em andamento suprime o alerta; desativado ou não instalado não gera alerta.

**Ciclo de vida:** aberto → reconhecido ("estou vendo") → em atendimento (agente atribuído ou OS aberta) → resolvido (pelo operador ou sozinho: sinal voltou, situação voltou a operacional, equipamento voltou ao ponto). Crítico não reconhecido toca de novo a cada 2 min; alto não reconhecido em 10 min vira crítico. Silenciar exige motivo e vale no máximo 30 min.

Todos os limites (50 m, 3 vezes, 15 min, 15%, 500 m, penalidades do índice...) ficam em `backend/app/domain/limites.py` e podem ser trocados sem mexer no código: `PUT /central/configuracao` (só o gestor).

### Índice de saúde da região

Começa em 100: −25 por alerta crítico aberto, −10 por alto, −3 por médio (no máximo −15 no total), −1 por ponto percentual de disponibilidade abaixo de 90% e −20 se não há agente em atividade. Normal de 80 a 100, Atenção de 50 a 79, Crítica abaixo de 50. As regiões são agrupamentos de bairros guardados na tabela `regiao`; zonas oficiais da prefeitura substituem a tabela sem mudar código.

### Mapa

- **Forma = categoria:** círculo para fiscalização e controle, quadrado para monitoramento, triângulo para veículos, losango para agentes (na cor do órgão). A letra do tipo fica dentro da forma.
- **Cor = situação ou pior alerta:** verde operacional; amarelo manutenção próxima, em manutenção ou alerta médio; laranja mau funcionamento ou alerta alto; vermelho furtado ou alerta crítico; cinza desativado ou não instalado. Um símbolo pequeno (✓ ! ×) repete a informação para quem não distingue cores.
- **Idade do dado:** sem sinal há mais de 2 vezes o intervalo, o ponto fica esmaecido e tracejado. Móveis deixam um rastro dos últimos minutos.
- **Grupos:** o miolo tem a cor da pior situação dentro do grupo (um furto nunca some num grupo verde) e o anel mostra a proporção de cada cor. Grupos com alerta crítico pulsam.
- Ícones e grupos são desenhados no navegador: o mapa continua legível sem internet.

### Tempo real

A tela carrega o estado inicial pela API e depois só recebe mudanças pelo WebSocket `/ws/eventos` (alertas, feições de equipamentos que mudaram, posições). O motor publica no Redis e cada processo da API entrega aos seus painéis; indicadores e regiões são recalculados a cada 5 s. Um furto simulado aparece no painel em menos de 1 segundo.

### API da central

```
GET   /central/estado              estado inicial do mapa em GeoJSON (com filtros)
GET   /indicadores                 indicadores do topo, com a variação na última hora (com filtros)
GET   /regioes/saude               índice de cada região, da pior para a melhor (com filtros)
GET   /central/regioes.geojson     contorno das regiões
GET   /central/calor               alertas das últimas 24 h, para o mapa de calor
GET   /alertas                     por nível, estado, regra, região (filtros da central valem aqui)
GET   /alertas/{id}                detalhe, com os equipamentos de um incidente
PATCH /alertas/{id}                reconhecer, silenciar, resolver
POST  /alertas/{id}/atribuir       atribui agente (em atendimento)
POST  /alertas/{id}/ordem-servico  abre OS a partir do alerta
GET   /alertas/{id}/agentes-proximos
GET   /manutencao/fila             imediata, vencida (mais atrasada primeiro), próxima em 7 dias
GET   /linha-do-tempo              estado em um momento da última hora
GET   /resumo-turno                o que mudou na última hora
GET   /central/perguntar?q=        "o que está acontecendo no Centro?"
GET   /central/configuracao        limites do motor (PUT: gestor)
POST  /telemetria/sinal | /telemetria/sinais | /telemetria/agentes
POST  /simulacao/incidente         furto, falha, silencio, queda_energia, degradado, sem_agentes
POST  /simulacao/restaurar
WS    /ws/eventos
```

Sinal de telemetria: `{"dispositivo_iot_id": "...", "tipo": "presenca|posicao|erro|metrica", "lon": ..., "lat": ..., "valores": {"qualidade": 40}}`. Sem `tipo`, vale como presença (compatível com a Parte 1).

### Decisões tomadas na construção

O documento da Parte 2 deixou algumas escolhas para a implementação. As decisões abaixo são da equipe e fáceis de trocar:

| Ponto | Decisão | Motivo |
|---|---|---|
| Alertas que pesam no índice da região | Só os em estado **aberto** (reconhecidos, em atendimento ou silenciados saem da conta) | O índice responde "onde olhar primeiro"; o que já tem alguém cuidando deixa de puxar a atenção |
| Alertas médios no índice | −3 cada, com teto de −15 | Manutenção vencida é pendência administrativa numerosa; sem teto, toda região ficaria crítica só por isso |
| Linha de base | Na primeira subida, o que já estava errado entra como "pendência anterior à central" (reconhecido) | A central abre com a cidade em estado conhecido; só problemas novos tocam e pesam no índice. `python -m scripts.preparar_central --forcar` refaz |
| Furto por deslocamento | Abre alerta crítico, mas não muda a situação para furtado | Como na falha silenciosa da Parte 1, só uma pessoa confirma o furto |
| Furto e manutenção | Furto nunca é suprimido por manutenção em andamento | Um roubo durante a manutenção continua sendo roubo |
| Cobertura (500 m) | Conta só vizinhos do mesmo tipo operacionais e sem problema aberto | Numa queda de energia, a câmera ao lado também caiu |
| Falha silenciosa | 3 vezes o intervalo (antes, na Parte 1, era 1 vez); sem nenhum sinal ainda, conta a partir do cadastro | Segue o documento da Parte 2; equipamento recém-cadastrado não é silêncio |
| Linha do tempo | Situação e alertas reconstruídos do histórico; agentes só ao vivo | O histórico de posição dos agentes não é guardado |
| Grupos no mapa | Miolo com a pior cor e anel com as proporções | Com 20 mil equipamentos, quase todo grupo tem um furtado antigo; só a pior cor deixaria a cidade inteira vermelha |
| Simulação de silêncio | Sinais dos equipamentos parados pela simulação são descartados na entrada | O simulador pode ter um lote em trânsito, que "ressuscitaria" o equipamento |

### Demonstração (roteiro do documento)

1. Abrir `/central`: indicadores no topo, regiões em "Normal", agentes e móveis se movendo.
2. **Simular incidente → Furto de radar** numa região escolhida pelo jurado.
3. Em menos de um segundo: alerta crítico no topo, som, ponto vermelho pulsando e a região caindo para "Atenção" com o motivo ("1 radar furtado").
4. Clicar no alerta: a ficha abre no mapa com os 3 agentes mais próximos; **Atribuir**.
5. **Simular → Queda de energia**: vários equipamentos ficam em silêncio e surge um único alerta de incidente correlacionado; ligar a camada **Cobertura de câmeras** mostra os pontos cegos.
6. Aba **Manutenção** e **Resumo do turno**.
7. **Linha do tempo**: voltar alguns minutos para ver como o incidente começou.
8. **Restaurar tudo o que foi simulado** (no mesmo menu) devolve a cidade ao normal.

---

## Parte 1 — Inventário

### Regras principais

**Disponibilidade (regra única, calculada só na API):**
`operacionais / (operacionais + mau funcionamento + em manutenção + furtados)`. "Ainda não instalado" e "desativado" ficam fora da conta. Endpoint: `GET /indicadores/disponibilidade?agrupar=orgao|tipo|regiao|bairro`. A central usa o mesmo cálculo.

**Transições de situação** (qualquer outra é recusada com 422):

| Situação atual | Pode ir para |
|---|---|
| Ainda não instalado | Operacional, Desativado |
| Operacional | Mau funcionamento, Em manutenção, Furtado, Desativado |
| Mau funcionamento | Em manutenção, Furtado, Desativado |
| Em manutenção | Operacional, Furtado, Desativado |
| Furtado | Em manutenção (recuperado), Desativado |
| Desativado | Em manutenção (reativação) |

**Automações:** mau funcionamento cria plano de manutenção imediata, abre ordem de serviço e reduz o score; furto gera alerta crítico e evento para o órgão; manutenção concluída devolve a operacional (passando por "em manutenção") e recalcula o próximo plano periódico; desativado suspende os planos. A cada minuto um job marca manutenção próxima (7 dias) ou vencida e recalcula scores. Desde a Parte 2, os alertas passam todos pelo motor de interpretação.

**Histórico somente inserção:** um trigger no banco recusa `UPDATE` e `DELETE` em `historico_situacao`.

### Integração com o PROMETHEUS

- Mesma API das telas: `GET /equipamentos`, `/equipamentos/{id}`, `/indicadores`, `/indicadores/disponibilidade`, `/regioes/saude`, `/alertas`, `/qualidade`.
- `POST /telemetria/sinal` (ou `/telemetria/sinais` em lote) recebe presença, posição, erro e métricas pelo `dispositivo_iot_id`.
- Eventos: webhook para `WEBHOOK_URL` (mudanças de situação e alertas novos, atualizados e resolvidos), consulta em `GET /eventos?desde=<ISO>` e o WebSocket `/ws/eventos`.
- O `codigo_interno` (ex.: `RAD-0042`) é o identificador para alertas e métricas.

### Demonstração do inventário (3 minutos)

1. Inventário com 20 mil equipamentos: filtros e busca respondendo rápido.
2. **Tipos → Novo tipo**: "Semáforo inteligente", prefixo `SEM`, sinal esperado a cada **1 min**, campos "Fases" (inteiro, obrigatório) e "Botoeira para pedestre" (sim ou não). A prévia aparece enquanto edita; ao salvar, o cadastro abre com o formulário novo.
3. **Cadastrar → Preencher com IA**: foto de etiqueta ou "radar de 60 km/h na Av. Paulista, oposto ao 181". A ficha se preenche para revisão.
4. **Agentes → Novo agente** vinculado a uma moto (`MOT-...`) do mesmo órgão.
5. Na ficha de um equipamento operacional: **mau funcionamento** com motivo. Aparecem as automações (plano imediato, OS, score antes → depois, com os motivos).
6. Falha silenciosa: com o semáforo do passo 2 cadastrado com módulo IoT, pare o simulador para ele (`curl -X POST localhost:8000/simulador/parados/SEM-0001`). Em pouco mais de 3 minutos (3 vezes o intervalo) surge o alerta "possível falha silenciosa".
7. **Qualidade**: ranking de completude por órgão e lista de correções.

---

## Desenvolvimento

```bash
# Backend (com o banco do compose em pé: docker compose up -d db)
cd backend
uv venv -p 3.12 .venv && uv pip install -p .venv -r pyproject.toml
.venv/bin/alembic upgrade head && .venv/bin/python -m scripts.seed && .venv/bin/python -m scripts.preparar_central \
  && .venv/bin/python -m scripts.preparar_preditivo
.venv/bin/uvicorn app.main:app --reload
.venv/bin/python -m scripts.simulador_telemetria          # em outro terminal

# Frontend
cd frontend && npm install && npm run dev

# Testes (backend usa um banco separado, atalaia_test)
./scripts/check.sh
```

Depois de mudar o `package.json`, o container `web` pode continuar com o `node_modules` antigo (fica num volume). Recrie: `docker compose rm -sf web`, remova o volume `*_web_*` com `docker volume rm` e rode `docker compose up -d --build web`.

Estrutura:

- `backend/app/domain`: regras puras (estados, disponibilidade, saúde, silêncio, qualidade, **regras e limites do motor**).
- `backend/app/services`: **motor** de interpretação, consultas da **central**, **barramento** de eventos, **simulação** e **resumo**.
- `backend/app/routers`: a API (`central.py` e `alertas.py` são da Parte 2).
- `backend/scripts`: seed, preparação da central e da Parte 3, gerador de histórico, verificação dos padrões e simulador.
- `backend/app/preditivo`: Parte 3 (geradores e padrões plantados, variáveis, baselines e backtest, um arquivo por modelo `p1.py` a `p7.py`, otimização, cartões, alertas preventivos, cenários, copiloto, briefing, treino e agendador).
- `frontend/src/preditivo/` e `frontend/src/pages/` (Amanha, Confianca, Cenarios...): telas da Parte 3; `components/ModoApresentacao.tsx` guarda o roteiro da demonstração.
- `frontend/src/pages/Central.tsx` e `frontend/src/central/`: a tela da central (mapa, painéis, WebSocket).

Testes: 226 no backend (73 da Parte 1, 39 da Parte 2, 114 da Parte 3) e 24 no frontend. Na Parte 3: migrações, reprodutibilidade do gerador, cada padrão plantado conferido por consulta, variáveis sem vazamento, baselines, P1 e P2 superando as referências (o teste falha se não superarem), contrato com campos não vazios, índice de risco em casos conhecidos, otimização de equipes respeitando as restrições e heurística de reserva válida, anomalias plantadas encontradas e série normal sem alarme, decisões (rejeitar exige motivo, aceitar executa), alertas preventivos que disparam e se resolvem, acertômetro, cenários (menos equipes aumenta o risco não coberto, evento aumenta ocorrências perto), retorno das decisões, padrões descobertos, copiloto com e sem IA, briefing, P6, P7, P8, expansão e extras.

Como a IA foi usada no desenvolvimento e nos recursos do sistema: [docs/uso-de-ia.md](docs/uso-de-ia.md).
