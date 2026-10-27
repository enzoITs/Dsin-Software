# Roteiro de demonstração — Cidade Preditiva

Cerca de 10 minutos. O mesmo roteiro está dentro do sistema: botão **Apresentar** no topo (ou `?apresentar` no endereço) abre um painel com o que mostrar e o que dizer em cada passo, e leva sozinho para a tela certa. PageDown e PageUp avançam e voltam (as teclas do passador de slides); Esc recolhe o painel.

## Antes de apresentar

1. **Banco novo, de 1 a 3 dias antes.** O gerador cria um grande show no Pacaembu (Centro, 38 mil pessoas, 20 h às 23h30) na primeira sexta depois do dia em que o banco foi criado, e a tela "Amanhã" mostra as próximas 72 h. Para a sexta 20 h aparecer, crie o banco na terça à noite, na quarta ou na quinta:

   ```bash
   podman compose down
   podman volume rm fogo_dbdata      # apaga o banco da demonstração
   podman compose up -d --build
   ```

   A primeira subida leva cerca de 1 min 30 s para os dados e uns 3 min para treinar os modelos (as telas de previsão mostram o progresso).

2. **Sem o banco novo**, cadastre o show na data que cair dentro das 72 h e recalcule:

   ```bash
   curl -X POST localhost:8000/eventos-cidade -H 'Content-Type: application/json' -d '{
     "nome": "Grande show no Pacaembu", "tipo": "show", "local_nome": "Estádio do Pacaembu",
     "lon": -46.6650, "lat": -23.5475, "publico_estimado": 38000,
     "inicio_em": "2026-10-30T20:00:00-03:00", "fim_em": "2026-10-30T23:30:00-03:00"}'
   curl -X POST localhost:8000/previsoes/recalcular
   ```

3. Confira: `podman compose exec api python -m scripts.verificar_padroes` (todos os padrões confirmados) e abra `/previsao/confianca` (modelos treinados).
4. Deixe abertas duas abas: `/previsao/briefing?apresentar` e `/central`.
5. Sem `ANTHROPIC_API_KEY` ou sem internet tudo funciona; o copiloto responde às perguntas prontas.

## Passos

### 1. O dia começa com o briefing — `/previsao/briefing`

- Mostrar o resumo (momento mais crítico do dia), os reforços para decidir, a manutenção preventiva e o acertômetro de ontem. O botão "Markdown" baixa o texto para mandar à equipe.
- Dizer: *"Às 6 h o gestor já sabe onde e quando o risco vai ser maior, o que precisa decidir e quanto o sistema acertou ontem."*

### 2. Amanhã: sexta às 20 h, Centro em risco muito alto — `/amanha`

- Arrastar o controle de horário até sexta, 20 h (ou apertar o play para ver as 72 h passarem). O Centro fica vermelho: show no Pacaembu somado à noite de sexta (padrão 1).
- Clicar na região: o Cartão de Previsão com os três títulos, **"O que estamos prevendo"**, **"Com base em quê"** e **"Como isso ajuda"**, os fatores em barras e o selo de qualidade contra a média histórica.
- Mostrar a linha de contexto: feriados, eventos e clima, editáveis.
- Dizer: *"O que estamos prevendo, com base em quê e como isso ajuda. Cada fator aparece com o peso que teve."*

### 3. A recomendação: reforçar o Centro — `/previsao/equipes`

- Risco não coberto com a escala atual × com a recomendada.
- A recomendação em texto direto: reforçar o Centro com equipes vindas das regiões mais calmas, só no período do show. As origens dependem da escala do dia; o otimizador respeita mínimo por região, órgão e máximo de deslocamentos.
- **Aceitar**: o turno é movido só naquele período e a decisão fica registrada (quem, quando). Mostrar que **Rejeitar** pede motivo.
- Dizer: *"O sistema recomenda; quem decide é a pessoa. Tudo fica registrado."*

### 4. E se...? — `/previsao/cenarios`

- Cancelar o show: o risco do Centro na sexta cai.
- Derrubar 5 câmeras do Centro: a cobertura cai e o índice sobe.
- Salvar o cenário com um nome.
- Dizer: *"Antes de decidir, o gestor testa a decisão. Os mesmos modelos rodam com e sem a mudança."*

### 5. Equipamentos em risco — `/previsao/equipamentos`

- Ranking de 7 dias: no topo, câmeras de uma marca, com mais de 18 meses, depois de chuva (padrão 4), e equipamentos com preventiva atrasada (padrão 7).
- Abrir um cartão: o fator "equipamento" e o fator "idade" pesam mais.
- Selecionar alguns e **abrir OS preventivas em lote**.
- Dizer: *"De cada 50 equipamentos que o modelo aponta, cerca de 8 falham na semana. Pela média histórica do tipo, 2."*

### 6 e 7. Na central: anomalia e alerta preventivo — `/central`

- Alerta de anomalia: um radar que passou a registrar cerca de 80% menos infrações, com o gráfico esperado × observado (padrão 12). Ele está "operacional" no inventário; só a anomalia mostra o problema.
- Alerta com a faixa **"Previsão"**: risco alto na região daqui a algumas horas, ou equipamento com alta chance de falhar e sem OS. "Ver previsão" abre o cartão.
- Ligar a camada **"Risco previsto (próximas 6 h)"**.
- Dizer: *"A central passa a ver o que ainda não aconteceu, com antecedência, e o que está estranho mesmo sem estar quebrado."*

### Extra (se houver tempo): tendências, furtos e expansão

- `/previsao/tendencias`: a região Leste cai abaixo da meta de 90% de disponibilidade (padrão 11); "seguindo o P1" volta para cima. Carga de manutenção das próximas 4 semanas.
- `/previsao/furtos` e `/previsao/expansao`: Brás e Itaquera com mais risco de furto, longe de câmeras (padrão 6), e onde uma câmera nova cobriria mais.
- Dizer: *"Prevê lugares e equipamentos, nunca pessoas."*

### 8. Confiança e padrões descobertos — `/previsao/confianca`

- Cada modelo ao lado da média histórica (backtest de 91 dias), calibração de P1, o que mais pesa.
- Acertômetro: previsto × real das últimas horas.
- Monitor dos modelos em operação.
- **Padrões plantados × descobertos**: 9 de 10 encontrados; o que falta (calor nos radares de rodovia) aparece como não encontrado, dito abertamente.
- Dizer: *"Os modelos não leram os padrões que plantamos nos dados e acharam quase todos. A confiança baixa é dita abertamente."*

### 9. Copiloto — `/previsao/copiloto`

- Perguntar "Onde o risco vai ser maior nas próximas 24 horas?" e "E se chover forte amanhã de manhã?".
- A resposta cita os cartões (`prev_N`), que abrem com um clique.
- Dizer: *"Funciona com ou sem IA: sem internet, responde às perguntas prontas com as mesmas consultas."*

### Fechamento — `/previsao/etica`

- Nunca pessoas; o humano decide; incerteza à mostra; dados sintéticos.
- Dizer: ***"PROMETHEUS agora enxerga o que pode acontecer amanhã, explica por quê e diz o que fazer."***

## Se algo der errado

| Sintoma | O que fazer |
|---|---|
| Telas de previsão dizem "treinando" | Esperar (cerca de 3 min no primeiro start) ou rodar `podman compose exec api python -m app.preditivo.treinar --todos` antes |
| Sexta 20 h fora das 72 h | Cadastrar o show na data certa (passo 2 da preparação) e recalcular |
| Nenhum alerta preventivo na central | `curl -X POST localhost:8000/previsoes/recalcular` refaz P2, P3, P4 e os alertas |
| Anomalia não aparece | `curl -X POST localhost:8000/anomalias/verificar`; as plantadas ficam visíveis por cerca de 28 dias depois da criação do banco |
| Copiloto sem IA | É esperado sem chave: usar as perguntas prontas |
| Reforço já aceito num ensaio | Recalcular o planejamento em `/previsao/equipes` gera novas recomendações |
