# Ética e limites da Cidade Preditiva

O Atalaia prevê **lugares, períodos e equipamentos**. Nunca pessoas. Este documento diz o que o sistema faz, o que ele se recusa a fazer, onde ele pode errar e como cada risco foi tratado. A mesma informação está na tela **Ética e limites** (`/previsao/etica`).

## 1. O que é previsto e o que não é

| Previsto | Unidade | Nunca previsto |
|---|---|---|
| Falha de equipamento (P1) | equipamento, 7 e 30 dias | quem vai cometer uma infração ou um crime |
| Ocorrências (P2) e índice de risco (P3) | região × hora | onde uma pessoa vai estar |
| Reforço de equipes (P4) | região × período | perfil, rosto, placa ou trajeto de alguém |
| Anomalias (P5) | equipamento ou região | comportamento individual |
| Disponibilidade (P6) e carga de manutenção (P8) | região, tipo, semana | desempenho de servidores ou agentes |
| Risco de furto (P7) | equipamento, 30 dias | suspeitos |
| Expansão de câmeras (C2) | célula de 400 m | vigilância dirigida a grupos ou pessoas |

Nenhuma tabela usada pelos modelos tem nome, documento, placa, imagem ou posição de pessoas. A escala de agentes entra como **número de agentes por região e hora**, nunca como agente identificado. Fora do escopo por decisão de projeto: reconhecimento facial, rastreamento de placas, bases policiais reais, previsão sobre indivíduos e qualquer decisão automática sem aprovação humana.

## 2. Viés de registro (o maior risco técnico)

**O problema.** Ocorrência registrada não é ocorrência acontecida. Onde há mais agentes, mais coisas são vistas e registradas. Um modelo ingênuo aprenderia "onde há agentes há ocorrências", mandaria mais agentes para lá e registraria ainda mais: um ciclo que se alimenta sozinho e concentra a fiscalização sempre nos mesmos lugares.

**O que foi feito.**

1. Cada ocorrência guarda `agentes_presentes_regiao` (quantos agentes estavam em turno na região na hora). O modelo de ocorrências (P2) usa isso como **exposição**: separa "aconteceu mais" de "foi mais visto".
2. Nos cenários "e se" (C1), **mudar o número de equipes não muda as ocorrências previstas**, só o índice de risco e o risco não coberto. Tirar equipes não "reduz ocorrências"; só deixa de vê-las.
3. A recomendação de reforço (P4) olha a demanda prevista e o risco **não coberto**, com teto de deslocamentos e mínimo por região: nenhuma região fica sem equipe para alimentar outra.
4. No histórico sintético, o viés foi plantado de propósito (até 25% a mais de registros onde há mais agentes) para que o sistema mostre que lida com ele.

**O que fica de limite.** A exposição corrige o efeito médio, não todos os casos. Numa cidade real, a validação teria de incluir fontes independentes do patrulhamento (chamadas ao 156, sensores, hospitais).

## 3. Furto de equipamento (P7) sem vigiar pessoas

O risco de furto usa só características do **ponto**: furtos de equipamento já registrados no bairro e a menos de 500 m, vandalismo de madrugada no bairro, distância até a câmera mais próxima, agentes de madrugada na região, tipo e idade do equipamento. As ações possíveis são sobre o ponto: incluir na ronda de madrugada, reforçar a fixação, avaliar uma câmera. O modelo tem uma **restrição monótona** (mais furtos por perto ou câmera mais longe nunca diminuem o risco) para não aprender regras sem sentido a partir de poucos casos.

A expansão de câmeras (C2) pontua células pelas ocorrências que passariam a ter cobertura e pelos furtos de equipamento evitados. Ela não usa nenhuma característica de quem mora ou circula na área.

## 4. O humano decide

- Toda recomendação tem **Aceitar, Ajustar e Rejeitar**. Rejeitar exige motivo; ajustar exige dizer o que mudou. Tudo fica registrado: quem, quando, motivo e o que foi executado (tela **Decisões**).
- O perfil automático (`prometheus`) **não pode decidir**: a API devolve 403.
- Aceitar executa só o que está escrito no cartão: abre a OS, move as equipes no período indicado ou abre as OS dos equipamentos da lista. Nada além disso.
- Os modelos não se retreinam sozinhos quando pioram: o monitor (X4) avisa e o gestor decide.
- O copiloto só lê e simula; não decide nem grava.

## 5. Transparência e incerteza

- Todo **Cartão de Previsão** responde às três perguntas do enunciado: o que estamos prevendo, com base em quê e como isso ajuda. Também traz os fatores que mais pesaram, em linguagem do gestor.
- Toda previsão tem **faixa** (90%), e o cartão diz a confiança: alta, moderada ou **baixa**. A baixa é dita abertamente, como acontece hoje com a tendência de disponibilidade em 30 dias, que é só 3% melhor que a média móvel.
- Todo modelo aparece **ao lado do baseline**, no backtest de origem móvel e na operação (acertômetro). Os testes automáticos falham se P1, P2 ou P7 não superarem o baseline.
- O monitor (X4) compara o desempenho na operação com o do backtest e avisa quando os dados mudam.

## 6. Dados sintéticos

Todos os dados da Parte 3 são **sintéticos**, gerados com padrões conhecidos (`padroes-plantados.md`). Os modelos não leem a descrição dos padrões, e a tela de confiança mostra quais foram redescobertos. Isso prova que o método funciona; **não** prova que os números valem para uma cidade real. Antes de uso real seria preciso:

1. Treinar e validar com dados reais, por pelo menos um ciclo anual.
2. Medir o viés de registro com fontes independentes.
3. Medir o desempenho separadamente por região, para ver se o modelo é pior em alguma, e corrigir.
4. Ter uma política pública sobre o uso das previsões, revisada periodicamente.

## 7. Limites conhecidos de cada módulo

| Módulo | Limite |
|---|---|
| P1 falha | Ordena bem (os 50 mais arriscados falham várias vezes mais que a média), mas a maioria das falhas ainda é acaso. Não substitui a manutenção preventiva |
| P2 ocorrências | Ganho moderado sobre a média histórica; eventos não cadastrados e mudanças bruscas não são previstos |
| P3 índice | Pesos fixos e configuráveis, não aprendidos. É uma síntese para decidir, não uma medida |
| P4 equipes | Só tão boa quanto a P2. Não considera trânsito real entre regiões |
| P5 anomalias | Precisa de semanas de série normal; uma anomalia que dura mais de metade da janela vira "o novo normal" |
| P6 disponibilidade | Em 30 dias ganha pouco da média móvel (dito no cartão); ganha mais em 90 dias. "Seguindo P1" é uma conta com eficácia de 50%, não um segundo modelo |
| P7 furto | Evento raro (cerca de 20 por mês): probabilidades pequenas e incertas. Não sabe a hora do furto |
| P8 carga | Horas por serviço e peças por corretiva vêm de configuração, não de dados |
| C2 expansão | Não sabe se há poste, energia ou visada no ponto: é sugestão para avaliar no local |
| X3 fim de vida | Vida útil por tipo vem de configuração; "como se fosse novo" é um contrafactual do modelo |
