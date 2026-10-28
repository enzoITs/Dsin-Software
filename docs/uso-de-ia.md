# Uso de IA no Atalaia

Dois usos diferentes: a IA que **ajudou a construir** o sistema e a IA que **faz parte** do sistema.

## 1. IA no desenvolvimento

O código foi escrito com o Claude Code (Claude Opus 5.5) a partir do documento de especificação da Parte 1, seguindo a ordem de construção do próprio documento: banco e seed, API e regras com testes, telas, inteligência (simulador, score, qualidade), IA e modo campo.

### Onde a IA ajudou

- Modelagem inicial (entidades, enums, índices, trigger de histórico somente inserção).
- Código do backend (FastAPI, SQLAlchemy, PostGIS) e do frontend (React, TanStack Query, MapLibre, react-jsonschema-form).
- Testes automáticos das regras que os jurados vão tentar quebrar (73 no backend, 6 no frontend).
- Dados de demonstração: 20 mil equipamentos com histórico coerente com a máquina de estados.

### Sugestões que foram corrigidas

Problemas encontrados ao rodar, testar e olhar as telas, com a correção aplicada:

| Problema | Como apareceu | Correção |
|---|---|---|
| Seed plantava duplicidade copiando a marca de outro tipo ("CHEVROLET" num radar) | Captura de tela da listagem | Duplicidade só entre equipamentos do mesmo tipo |
| Atributos do formulário fora da ordem definida | Captura de tela do cadastro | O JSONB do Postgres reordena chaves; a ordem passou a ser guardada em `x-ordem` no schema |
| Editor de tipos convertia opções para minúsculas ("4MP" virava "4mp"), o que invalidaria cadastros existentes | Revisão do editor com um tipo real | Opções guardadas como digitadas |
| Erro de número de série duplicado escapava como erro 500 | Teste `test_serie_unica_por_marca` | O autoflush do SQLAlchemy disparava antes do `try`; unicidade passou a ser checada antes de inserir |
| 23% dos equipamentos com manutenção vencida no seed | Consulta de distribuição após o seed | Distribuição ajustada para cerca de 8% |
| Completude penalizava campo que não se aplica (velocidade máxima em radar de semáforo) | Painel de qualidade | Completude conta só atributos obrigatórios do tipo |
| Ranking de qualidade com todos os órgãos iguais | Painel de qualidade | Seed passou a variar o cuidado de cadastro por órgão |
| Build do frontend falhando com Tailwind 4.0.0 | `vite build` | Atualizado para Tailwind 4.1 |


### Decisões de arquitetura e o porquê

- **Modelo híbrido (colunas fixas + JSONB validado por JSON Schema):** o mesmo schema valida na API e gera o formulário na tela, então um tipo novo é só uma linha no banco.
- **Regras no domínio (`backend/app/domain`), não nas telas:** disponibilidade, transições e score têm um único lugar, usado pelo painel, pelo modo campo e pelo PROMETHEUS.
- **Score com motivos persistidos:** a listagem ordena por score sem recalcular, e a ficha mostra exatamente o que pesou.
- **Recálculo em lote com consultas agregadas:** 20 mil equipamentos em cerca de 2 segundos, o que permite rodar o job a cada minuto.
- **Sem login nesta parte:** perfil por cabeçalho mantém a separação por órgão sem gastar o prazo em autenticação.

## 2. IA dentro do sistema

Código em `backend/app/services/ia.py` e `backend/app/routers/ia.py`. Modelo: `claude-opus-5-5` (troca por `ANTHROPIC_MODEL` no `.env`).

### Cadastro por foto ou texto (`POST /ia/extrair-cadastro`)

Entrada: foto da etiqueta e/ou frase livre. O prompt recebe a lista de tipos com seus schemas e a lista de bairros oficiais. Instruções principais do prompt de sistema:

- preencher só o que estiver na foto ou no texto; sem evidência, `null`; nunca inventar número de série, MAC ou IMEI;
- escolher o tipo pelo id da lista;
- atributos só com chaves do schema do tipo e valores de enum exatos;
- separar rua e referência ("oposto ao 181", "KM 203").

A resposta é forçada a um JSON Schema (saída estruturada). **Antes de ir para a tela**, a API:

1. confere se o tipo existe;
2. descarta atributos que não estão no schema e valida cada valor (um valor inválido é descartado com aviso);
3. casa o bairro com a lista oficial, ignorando acento e caixa, e coloca um ponto aproximado no bairro para a pessoa ajustar;
4. normaliza o CEP.

Nada é salvo: os campos voltam para revisão e só são gravados quando a pessoa clica em Cadastrar.

### Busca em linguagem natural (`POST /busca`)

Ex.: "câmeras sem visão noturna no Centro com manutenção vencendo". O modelo devolve filtros num JSON Schema fechado (tipos, situações, órgãos, regiões, bairros, status de manutenção, sem sinal, score máximo, atributos). A API mantém só valores que existem nas listas reais e chaves de atributo que existem em algum tipo, e devolve os mesmos parâmetros da listagem. A tela mostra os filtros entendidos, que a pessoa pode remover.

### Falhas

- Sem `ANTHROPIC_API_KEY`, sem rede, limite de uso ou erro da API: resposta 503 com mensagem clara; a tela desliga os botões de IA e o fluxo manual continua.
- Recusa por política: o servidor tenta um modelo de fallback (`fallbacks: "default"`); se ainda assim recusar, a tela pede preenchimento manual.
- Os testes em `backend/tests/test_ia.py` simulam respostas do modelo, inclusive valores inválidos, para provar que a validação segura o que não confere.

---

# Parte 2: Central de Operações

## IA no desenvolvimento

A Parte 2 foi construída com o Claude Code (Claude Opus 5.5) a partir do documento "Atalaia — Parte 2: Solução da Central de Operações", seguindo a ordem de construção do próprio documento: motor de interpretação com as regras principais; mapa com camadas, agrupamento e ficha; tempo real, alertas e indicadores; filtros, índice de saúde e regiões; fila de manutenção, agentes mais próximos e ações; simulação e incidente correlacionado; resumo do turno, linha do tempo, pontos cegos e sala de situação.

Cada etapa foi verificada rodando a API contra o banco com os 20 mil equipamentos, ouvindo o WebSocket e tirando capturas de tela do navegador.

### Problemas encontrados e corrigidos

| Problema | Como apareceu | Correção |
|---|---|---|
| Quase todo grupo do mapa ficava vermelho | Captura de tela: os 600 furtados do histórico estão espalhados pela cidade | Miolo do grupo com a pior cor (regra do documento) e anel com a proporção de cada cor |
| Anel do grupo lia as proporções na ordem invertida | Captura de tela: grupos quase todos laranja | Ordem corrigida |
| Mapa em branco | Captura de tela | O CSS do MapLibre força `position: relative` no contêiner; o mapa ganhou um contêiner interno |
| Simulação de queda de energia "desfeita" em 2 segundos | Alertas resolvidos com "Sinal voltou" logo depois de criados | O simulador tinha um lote de sinais em trânsito; sinais de equipamentos parados pela simulação passaram a ser descartados na entrada |
| Deadlock entre o recálculo geral e os lotes de telemetria | Log da API | Gravações em lote em ordem fixa de id e nova tentativa em caso de deadlock |
| Equipamento recém-cadastrado virava "falha silenciosa" na hora | Teste `test_erro_com_outro_radar_perto_fica_alta` | Sem nenhum sinal ainda, o silêncio conta a partir do cadastro |
| Toda região ficaria crítica com a pendência acumulada (3.479 manutenções vencidas) | Conta do índice com os dados reais | Linha de base na primeira subida, índice só com alertas "abertos" e teto de −15 para os médios |
| Alertas criados antes da linha de base, porque o container da API recarregou o código novo enquanto o simulador antigo ainda rodava | Contagem de alertas por estado | Linha de base refeita com `--forcar` depois de atualizar o simulador |
| Viaturas viravam "falha silenciosa" meia hora depois de subir o simulador novo | Regiões Sul e Oeste caíram para Crítica sem simulação | Móveis sem ponto no cadastro (0,4% do seed, de propósito) ficavam fora do simulador; agora mandam presença como os fixos |
| Membros de incidente republicados a cada novo membro (eventos em quantidade quadrática) | Escuta do WebSocket | Só os membros que mudaram são publicados |
| Volume antigo de `node_modules` reaproveitado pelo container web | Erro do Vite ao importar `@turf/circle` | Volume recriado (instrução no README de desenvolvimento) |

## IA dentro da central

Dois recursos usam o Claude, sempre com fatos calculados pela API e com alternativa sem IA:

- **Resumo do turno** (`GET /resumo-turno`): a API monta os fatos da última hora (alertas novos agrupados por regra, tipo e região; resolvidos; abertos por nível; disponibilidade e variação; regiões fora do normal e mudanças de estado) e um texto-base por modelo de texto. Com IA disponível, o Claude reescreve os fatos em até 3 frases, com a instrução de usar só números e nomes presentes nos fatos. Sem IA, ou se ela falhar, a tela mostra o texto-base. A resposta informa a fonte (`ia` ou `modelo`).
- **Perguntar ao painel** (`GET /central/perguntar?q=`): a região (ou o bairro) citada é achada na pergunta sem IA, ignorando acento e caixa. A API reúne índice, alertas, indicadores e agentes da região e monta uma resposta; com IA, o Claude responde à pergunta só com esses fatos.

Os dois usam a mesma chamada da Parte 1 (`services/ia.py`: saída estruturada em JSON Schema e fallback do servidor em caso de recusa).

---

# Parte 3: Cidade Preditiva

## IA no desenvolvimento

A Parte 3 foi construída com o Claude Code (Claude Opus 5.5) a partir do prompt da Parte 3, condensado em [parte3/especificacao.md](parte3/especificacao.md). O trabalho começou por um reconhecimento do código das Partes 1 e 2 e um plano enxuto ([parte3/00-reconhecimento.md](parte3/00-reconhecimento.md)), aprovado pela equipe antes de qualquer código, com as decisões que só a equipe podia tomar: recriar o banco com o histórico novo, prever por bairro e somar por região, deixar de fora os padrões 9 e 10.

Depois, 14 fases com um commit cada, na ordem do documento: dados novos; gerador com padrões plantados; variáveis sem vazamento, baselines e backtest; P1; P2 e P3; P4; P5; contrato, cartão e telas; alertas preventivos e acertômetro; cenários, retorno e padrões descobertos; briefing e copiloto; P6, P7, P8 e expansão; extras; documentação. Toda divergência da especificação foi registrada em [parte3/decisoes.md](parte3/decisoes.md), com o motivo.

Cada fase foi conferida de três jeitos: testes automáticos (que falham se um modelo não superar a referência), métricas do backtest no banco gerado e capturas de tela do navegador sem interface gráfica.

### Onde a IA ajudou

- Gerador determinístico da história da cidade com os padrões plantados, e as consultas que conferem cada padrão.
- Variáveis por equipamento × dia e bairro × hora com teste de vazamento, baselines e backtest de origem móvel.
- Modelos (LightGBM, regressão logística, ETS, STL, Isolation Forest), calibração, intervalos conformais e a tradução das contribuições SHAP em fatores para o gestor.
- Otimização de equipes (`scipy.optimize.milp`) com heurística de reserva.
- Contrato de previsão, Cartão de Previsão e as telas.
- Contrafactuais para conferir se os modelos redescobriram os padrões, sem que eles lessem a descrição.

### Problemas encontrados e corrigidos

| Problema | Como apareceu | Correção |
|---|---|---|
| Escala sintética deixava as regiões Leste e Norte sem nenhuma equipe | Conferência da escala por região na fase de P3 | Equipes distribuídas na proporção do número de bairros |
| Otimizador trocava equipes entre duas regiões no mesmo período | Primeira tela do planejamento | Restrição nova: uma região não cede e recebe no mesmo período (a redução do risco caiu de 52% para 46%, mas o plano ficou legível) |
| P7 dizia que câmera mais longe reduzia o risco de furto | Contrafactual da tela de Expansão com o sinal trocado | Restrição monótona no LightGBM (AUC 0,733 em vez de 0,746, mas com sentido) |
| ETS na série diária de disponibilidade perdia para a média móvel | Backtest de P6 | ETS sobre as médias semanais |
| Isolation Forest sozinho acusava qualquer queda de uma hora | Alarmes falsos nas séries normais | Virou segunda opinião; a regra é STL com escore robusto |
| Treino de P1 quebrava num corte do backtest sem nenhuma falha (AUC indefinida) | Erro no log do treino | AUC mostrada como "—" nesse corte (commit `36596b3`) |
| Cenário com menos equipes "reduzia" ocorrências | P2 aprendeu que mais agentes registram mais ocorrências (viés de registro) | Nos cenários, mudar equipes muda só o índice e o risco não coberto, nunca as ocorrências previstas |
| Treino do primeiro start morria quando o `--reload` recarregava a API | Desenvolvimento com o contêiner recarregando o código | O estado guarda o processo; treino órfão é refeito no próximo start |
| Modelos treinados na máquina não abriam no contêiner | Caminho gravado inexistente | Busca pelo nome na pasta dos modelos |
| Testes falhavam quando a suíte cruzava a virada da hora | Dois lotes de previsão no banco | Os testes olham só o lote mais recente |
| Rótulos no mapa exigiam fontes baixadas da internet | Mapa sem texto offline | Nome e índice aparecem ao passar o mouse e na faixa de regiões |
| PuLP 4 não traz mais o CBC | Escolha do solver na fase 1 | `scipy.optimize.milp` (HiGHS), offline |

### O que a equipe decidiu

A IA propôs; a equipe aprovou o plano, o escopo enxuto, a recriação do banco, a unidade espacial e o que ficou de fora (X1, X2, detector de operação de P5, P1 no score de saúde da Parte 1). As cinco regras do enunciado (ação, explicação, prova, decisão humana, nunca pessoas) foram usadas como critério de revisão de cada tela.

## IA dentro do sistema

**As previsões não usam IA generativa.** P1 a P8, o briefing, o relatório semanal, os cenários e os alertas são modelos estatísticos e regras sobre os dados do sistema: saem iguais todo dia e funcionam sem internet.

O único recurso com o Claude é o **copiloto** (`backend/app/preditivo/copiloto.py`, `POST /copiloto/perguntar`):

- **Com `ANTHROPIC_API_KEY`:** loop de ferramentas com o `claude-opus-5-5` (esforço médio, fallback do servidor ligado). São 9 ferramentas estritas que chamam as mesmas funções dos endpoints: risco por região, ocorrências previstas, equipamentos em risco, reforços, anomalias, alertas preventivos, qualidade dos modelos, contexto do dia e simulação de cenário. No máximo 8 passos por pergunta.
- **Instruções principais do prompt de sistema:** usar as ferramentas para todo número, região, horário ou equipamento citado, sem inventar dados; começar pela resposta, depois o porquê e a ação; citar o id da previsão (`[prev_123]`), que a tela abre como cartão; dizer quando a confiança é moderada ou baixa; recomendar, não decidir; falar de lugares, períodos e equipamentos, nunca de pessoas.
- **Limites:** só lê e simula; não decide nem grava nada.
- **Sem chave, sem rede ou com erro:** 8 perguntas prontas respondidas por regras sobre as mesmas consultas (incluindo dois cenários: chuva forte amanhã de manhã e 2 equipes a menos no Centro). Texto livre é associado a uma pronta por palavras-chave. A tela diz qual modo respondeu e por quê.
- Os testes em `backend/tests/test_copiloto.py` cobrem os dois modos, com respostas do modelo simuladas.
