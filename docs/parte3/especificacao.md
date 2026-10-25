# Especificação da Parte 3 — Cidade Preditiva (resumo de referência)

Cópia condensada do prompt da Parte 3, guardada no repositório para consulta entre sessões. O texto original tem o mesmo conteúdo com mais exemplos.

## Princípios

1. Toda previsão vira uma ação (quem, onde, quando, o quê).
2. Toda previsão se explica (fatores em linguagem simples, dados usados).
3. Toda previsão prova que funciona (comparada com baseline e com o que aconteceu).
4. O humano decide (aceitar, ajustar, rejeitar, registrado).
5. Prever lugares, períodos e equipamentos, nunca pessoas.

Exigência do enunciado: "deixar claro o que está sendo previsto, quais informações foram consideradas e como essa previsão pode ajudar na tomada de decisão".

## Regras de trabalho

Partes 1 e 2 são a fonte da verdade (divergências em `decisoes.md`); não quebrar testes; migrações aditivas e reversíveis; Núcleo antes de Diferenciais antes de Extras; `docker compose up` funciona sem internet; semente fixa; sem vazamento (validação temporal); limites e pesos em configuração; commit e resumo por fase (com métricas); interface e docs em português do Brasil.

## Escopo

Núcleo: D1 ocorrências e histórico com padrões; D2 calendário, eventos, clima; D3 variáveis e baselines; P1 risco de falha de equipamento (7 e 30 dias); P2 ocorrências por região e hora (72 h); P3 índice de risco por região e período; P4 reforço de agentes; P5 anomalias; U1 contrato e Cartão de Previsão; U2 tela "Amanhã"; U3 alertas preventivos na Central; Q1 acertômetro.

Diferenciais: P6 tendência de disponibilidade; P7 risco de furto; P8 carga de manutenção; C1 cenários "e se"; C2 expansão; C3 copiloto; C4 briefing diário; C5 retorno das recomendações; Q2 descoberta dos padrões plantados.

Extras: X1 rotativo; X2 patinetes; X3 fim de vida útil; X4 monitor de modelos; X5 relatório semanal; X6 modo apresentação; X7 página "Ética e limites".

## Dados

- `ocorrencia`: categoria (ACIDENTE, CONGESTIONAMENTO, ESTACIONAMENTO_IRREGULAR, VEICULO_QUEBRADO, ALAGAMENTO, SEMAFORO_APAGADO, FURTO_EQUIPAMENTO, VANDALISMO, PERTURBACAO, OUTROS), gravidade 1–4, início/fim, geom, região, bairro, origem, equipamento/alerta, `agentes_presentes_regiao`.
- `calendario`, `evento_cidade` (tipo, local, público, raio), `clima_hora` (temperatura, chuva, tempestade; futuro editável).
- Gerador `scripts/gerar_historico.py`, determinístico, 12 a 18 meses, com padrões plantados documentados em `padroes-plantados.md`:
  1. Centro: mais ocorrências sexta e sábado, 18 h às 23 h.
  2. Chuva: acidentes cerca de +40%; alagamentos em bairros baixos específicos.
  3. Eventos com mais de 10 mil pessoas: mais ocorrências num raio de 2 km, de 2 h antes a 2 h depois.
  4. Câmeras de uma marca falham muito mais depois de 18 meses de instalação, sobretudo após chuva.
  5. Radares de rodovia falham mais com temperatura acima de 32 °C.
  6. Furtos de equipamentos em dois bairros, de madrugada, em pontos sem câmera próxima.
  7. Manutenção atrasada há mais de 15 dias: o dobro de chance de falhar.
  8. Congestionamentos em dias úteis 7–9 h e 17–19 h, mais fortes em véspera de feriado.
  9. e 10. Rotativo e patinetes (fora do plano enxuto).
  11. Queda lenta de disponibilidade numa região sem manutenção preventiva.
  12. Anomalias isoladas (radar que para de registrar infrações, câmera que cai toda noite).
  Ruído realista em tudo. Modo contínuo alimenta o simulador com os mesmos padrões.
- Variáveis por equipamento × dia e região × hora, só com dados até o momento da previsão (teste automatizado). Baselines: P1 taxa histórica do tipo; P2 média da mesma hora e dia da semana nas últimas 8 semanas; P6 última média móvel de 30 dias.

## Contrato de previsão (U1)

Campos: id, modulo, o_que_preve, alvo {tipo, id, nome, regiao}, horizonte {inicio, fim}, valor, faixa {inferior, superior}, nivel, dados_considerados[], fatores[{descricao, efeito}], como_ajuda, acao_recomendada {texto, tipo, parametros}, qualidade_do_modelo {metrica, modelo, baseline, avaliado_em}, modelo {nome, versao}, gerado_em.

Cartão: títulos fixos "O que estamos prevendo", "Com base em quê", "Como isso ajuda"; fatores como barras; botões Aceitar, Ajustar, Rejeitar (com motivo); selo de qualidade versus baseline; confiança baixa dita abertamente.

## Módulos

- P1: LightGBM + regressão logística de comparação, calibração, SHAP traduzido; AUC, Brier, calibração, precisão nos 50 primeiros; ranking, OS preventiva em um clique, probabilidade na ficha e no score de saúde.
- P2: gradient boosting Poisson/Tweedie por região × hora, 72 h, total e por categoria; intervalos por quantis ou conformal; MAE versus sazonal ingênuo, picos à parte.
- P3: índice 0–100 = 40% ocorrências previstas ponderadas pela gravidade versus normal; 20% equipamentos em risco ou indisponíveis; 15% cobertura prevista; 15% agentes da escala versus demanda; 10% fatores externos. Faixas Baixo 0–24, Moderado 25–49, Alto 50–74, Muito alto 75–100. Quatro períodos por dia (madrugada, manhã, tarde, noite) e por hora no detalhe.
- P4: demanda (equipes por N ocorrências previstas, ajustada pela gravidade) + programação linear inteira (mínimo por região, máximo de deslocamentos, órgão, nenhuma região "Muito alto" sem reforço); heurística gulosa de reserva; risco não coberto antes e depois; texto direto ("Sexta, 18 h às 23 h: reforçar o Centro com +2 equipes vindas da Zona Sul...").
- P5: equipamento (STL + escore robusto; Isolation Forest no perfil diário), região (observado fora do intervalo de P2 por N horas), operação (limites de controle nos indicadores da Parte 2); gráfico esperado × observado.
- P6: ETS 30/90 dias por tipo e região, cenários "se nada mudar" e "seguindo P1", alerta ao cruzar a meta.
- P7: probabilidade de furto por equipamento em 30 dias (densidade espaço-temporal, cobertura de câmeras, agentes).
- P8: falhas esperadas + preventivas por semana, tipo e região (4 semanas); técnicos-dia e peças.

## Telas e integrações

- "Amanhã": mapa de risco P3 com controle de horário de 72 h e animação; faixa de regiões; painel de recomendações em cartões; linha de contexto (feriados, eventos, clima, editáveis); gráfico por região previsto × real.
- Outras: Equipamentos em risco, Planejamento de equipes, Anomalias, Tendências, Cenários, Expansão, Confiança dos modelos, Copiloto.
- Alertas preventivos no motor: `PREVISAO_RISCO_REGIAO` (Alto/Muito alto nas próximas 6 h), `PREVISAO_FALHA_EQUIPAMENTO` (acima do limite e sem OS), `PREVISAO_FALTA_AGENTES`, `PREVISAO_DISPONIBILIDADE`, `ANOMALIA_*`. Visual próprio ("previsto para...", antecedência), abrem o cartão. Camada "Risco previsto (próximas 6 h)" e probabilidade de falha na ficha.
- C1 cenários (evento, clima, equipes, derrubar equipamentos, manutenções; salvar e nomear). C2 expansão. C3 copiloto com ferramentas que chamam a API, modo sem LLM com perguntas prontas. C4 briefing às 6 h, Markdown, com acertômetro. C5 decisões registradas e resultado comparado. Q1 toda previsão guardada com valor real; backtest de origem móvel de pelo menos 90 dias. Q2 padrões descobertos (SHAP agregado, dependência parcial), deixando claro que os dados são sintéticos.

## Técnica

- Treino `python -m preditivo.treinar --todos`; lote pelo APScheduler (P2, P3, P4 de hora em hora; P1, P6, P7, P8 às 5 h; P5 a cada 5 min); sob demanda para cenários e copiloto. Primeiro start gera e treina em menos de 5 min, com progresso na interface. Eventos `previsao.atualizada`, `recomendacao.nova`, `alerta.preventivo`.
- Tabelas: ocorrência, categoria, calendário, evento, clima, escala_agente, modelo_versao, previsao, recomendacao (PENDENTE, ACEITA, AJUSTADA, REJEITADA, EXPIRADA), cenario, backtest_resultado, briefing.
- Ética: nada sobre pessoas; viés de patrulhamento via `agentes_presentes_regiao`; transparência; decisão humana; incerteza à mostra.
- API: `/previsoes`, `/previsoes/{id}`, `/amanha`, `/amanha/regioes/{id}`, `/equipamentos/risco`, `/equipamentos/{id}/risco`, `/planejamento/equipes` (+ `/recalcular`), `/anomalias`, `/tendencias/disponibilidade`, `/tendencias/manutencao`, `/recomendacoes` (+ PATCH), `/cenarios/simular`, `/cenarios`, `/expansao/sugestoes`, `/copiloto/perguntar`, `/briefing/hoje`, `/modelos`, `/modelos/acertometro`, `/modelos/padroes-descobertos`, `/modelos/treinar`, `/eventos-cidade`, `/clima/previsao`, `/ocorrencias`.

## Fases

0 reconhecimento; 1 dados novos e registro na Central; 2 gerador com padrões e modo contínuo (mesma semente, mesmos dados; padrões visíveis em consultas); 3 variáveis, teste de vazamento, baselines, backtest; 4 P1 (supera baseline em AUC e Brier); 5 P2 e P3 (P2 supera sazonal em MAE); 6 P4 (reduz risco não coberto); 7 P5 (acha padrão 12); 8 contrato, cartão, "Amanhã", risco, planejamento; 9 alertas preventivos, camada, acertômetro, confiança; 10 C5, Q2, C1; 11 C4, C3; 12 P6, P7, P8, C2; 13 extras; 14 documentação e roteiro.

## Testes obrigatórios

Reprodutibilidade; sem vazamento; padrões plantados confirmados por consultas; P1 e P2 superam baselines (teste falha se não); contrato com campos não vazios; P3 casos conhecidos e soma; P4 restrições e heurística válida; P5 detecta anomalias plantadas e não acusa série normal; alertas preventivos disparam e resolvem; cenários (menos equipes aumenta risco não coberto; evento aumenta ocorrências perto); retorno registra decisão e motivo; sem internet funciona.

## Roteiro de demonstração (`roteiro-demo.md`)

1. Briefing; 2. "Amanhã" sexta 20 h, Centro "Muito alto", cartão; 3. recomendação +2 equipes da Zona Sul, aceitar; 4. "e se" show cancelado / 5 câmeras caídas; 5. ranking de risco, OS preventiva; 6. anomalia de radar (−80% infrações); 7. alerta preventivo na Central; 8. tela de confiança e padrões descobertos; 9. copiloto. Fechamento: "PROMETHEUS agora enxerga o que pode acontecer amanhã, explica por quê e diz o que fazer."

## Documentação a entregar

README; `previsoes.md`; `padroes-plantados.md` e relatório de descoberta; `decisoes.md`; `etica-e-limites.md`; `roteiro-demo.md`; `docs/uso-de-ia.md`.

Fora do escopo: previsões sobre indivíduos, reconhecimento facial, rastrear placas, bases policiais reais, decisão automática sem aprovação humana.
