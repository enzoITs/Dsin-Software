# Padrões plantados no histórico sintético

**Os dados da Parte 3 são sintéticos.** O gerador cria 18 meses de história da cidade com padrões conhecidos, descritos aqui. Os modelos de previsão **não leem este arquivo nem o módulo que define os padrões** (`backend/app/preditivo/padroes.py`): eles precisam redescobrir cada padrão olhando só os dados. A tela de confiança (Q2) mostra quais foram encontrados.

## Como o histórico é gerado

| Parte | Onde | O que gera |
|---|---|---|
| Vida dos equipamentos | `scripts/seed.py` chama `app/preditivo/gerador_equipamentos.py` | Antes do período: alguns ciclos simples de falha e conserto. Nos 18 meses do período: simulação dia a dia de falhas, furtos, esperas pelo conserto, consertos e manutenções preventivas (com atrasos) |
| Cidade | `scripts/gerar_historico.py` (roda sozinho na subida, pelo `preparar_preditivo`) | Clima por hora, calendário, cerca de 320 eventos, cerca de 18 mil turnos de equipes, cerca de 160 mil ocorrências, séries por hora de 240 equipamentos nos últimos 60 dias |
| Modo contínuo | `scripts/simulador_telemetria.py` chama `app/preditivo/historico.py` | A cada 5 minutos, as ocorrências e séries das horas que passaram. Uma vez por hora, falhas, furtos e consertos aplicados pela API, para o motor da Parte 2 reagir |

Reprodutível: **mesma semente e mesma data de referência geram os mesmos dados**. A data de referência é o fim do histórico (padrão: o dia em que o banco foi criado) e fica gravada em `estado_preditivo`. Cada dia é sorteado com uma semente que depende só da semente geral e da data, por isso gerar tudo de uma vez ou hora a hora no modo contínuo dá o mesmo resultado (desde que clima e eventos sejam os mesmos).

No modo contínuo, o clima que "acontece" é o que está no banco, inclusive o editado pelo operador. Se o gestor disser "amanhã, chuva forte à tarde", amanhã chove forte à tarde no histórico, e as ocorrências seguem o padrão 2.

Para conferir os padrões com consultas diretas ao banco:

```bash
podman compose exec api python -m scripts.verificar_padroes
```

## Os padrões

| # | Padrão | Como foi plantado | Medida no banco de demonstração* |
|---|---|---|---|
| 1 | Ocorrências no Centro aumentam sexta e sábado, das 18 h às 23 h | Todas as categorias ×2,2 nos bairros da região Centro nessas horas; perturbação ×3,5 | Sexta e sábado ÷ segunda a quinta, mesmas horas: **2,3×** |
| 2 | Chuva aumenta acidentes em cerca de 40% e alaga bairros baixos | Acidentes ×1,4 em hora com chuva (≥ 0,5 mm); semáforo apagado ×2 com chuva forte (≥ 5 mm/h); alagamentos proporcionais à chuva forte, quase só em Casa Verde, Bom Retiro, Ipiranga e Lapa | Acidentes com chuva ÷ sem chuva (12 h às 20 h): **1,5×**. **83%** dos alagamentos nos 4 bairros baixos |
| 3 | Eventos com mais de 10 mil pessoas aumentam ocorrências num raio de 2 km, de 2 h antes a 2 h depois | Ocorrências extras: 0,9 por hora a cada 10 mil pessoas (congestionamento, estacionamento irregular, perturbação, acidente), espalhadas no raio. Eventos menores não mudam nada | Raio de 2 km durante evento grande ÷ mesma janela uma semana antes: **2,7×** (eventos menores: 1,0×) |
| 4 | Câmeras de uma marca falham muito mais depois de 18 meses, sobretudo após dias de chuva | Câmeras **Hikvision** com mais de 18 meses de instalação: risco ×3; no dia seguinte a um dia com 10 mm ou mais de chuva, ×2 de novo | Hikvision com mais de 18 meses ÷ outras marcas da mesma idade: **3,0×**. Dia seguinte a chuva forte ÷ demais dias: **1,9×** |
| 5 | Radares de rodovia falham mais com temperatura acima de 32 °C | Radares de velocidade com limite de 80 km/h ou mais (vias de trânsito rápido) ×4 nos dias com máxima acima de 32 °C | Falhas em dias quentes ÷ demais dias: **3,5×** |
| 6 | Furtos de equipamentos se concentram em dois bairros, de madrugada, em pontos sem câmera próxima | Câmeras, radares, totens, balanças, cancelas e patinetes: risco ×8 em **Brás** e **Itaquera**, e ×5 de novo sem câmera a menos de 300 m; nesses bairros o furto acontece entre 0 h e 5 h. Cada furto vira ocorrência `FURTO_EQUIPAMENTO`. Vandalismo de madrugada ×5 nesses bairros | **40%** dos furtos nesses 2 de 28 bairros; **99%** deles entre 0 h e 5 h |
| 7 | Manutenção atrasada há mais de 15 dias dobra a chance de falhar | Risco ×2 enquanto a preventiva está atrasada mais de 15 dias. 78% das preventivas saem até 7 dias depois da data, 14% entre 8 e 15 dias, 8% entre 16 e 45 dias. Conserto corretivo não substitui a preventiva | Falhas por dia com atraso > 15 dias ÷ em dia: **2,0×** |
| 8 | Congestionamentos nos dias úteis das 7 h às 9 h e das 17 h às 19 h, mais fortes em véspera de feriado | Congestionamento ×4 nessas horas dos dias úteis; ×1,6 de novo em véspera de feriado. Feriado se comporta como domingo | Pico ÷ demais horas dos dias úteis: **8,6×**. Véspera ÷ dia útil comum, no pico: **1,5×** |
| 9 | Estacionamento rotativo | **Não plantado** (fora do plano enxuto) | — |
| 10 | Patinetes | **Não plantado** (fora do plano enxuto) | — |
| 11 | Queda lenta de disponibilidade numa região sem manutenção preventiva | A partir de um terço do período, a região **Leste** deixa de fazer 92% das preventivas (os atrasos crescem e o padrão 7 entra em ação), e a espera pelo conserto sobe de 4 para 14 dias até o fim do período | Disponibilidade dos fixos da Leste: **97,5% → 89,6%**; nas outras regiões a queda mediana é de 0,4 ponto |
| 12 | Anomalias isoladas | Séries por hora (`serie_equipamento_hora`) de 120 radares (infrações) e 120 câmeras (minutos online) nos últimos 60 dias. Três radares passam a registrar 80% menos (há 2, 9 e 25 dias da data de referência) e três câmeras caem toda noite entre 0 h e 5 h (há 5, 12 e 30 dias) | Todas as 6 visíveis nas séries |

\* Medidas do banco gerado com semente 42 e data de referência 25/10/2026 (20 mil equipamentos). O teste automatizado `tests/test_gerador.py` repete as mesmas consultas num banco à parte, com 6 mil equipamentos, e falha se algum padrão não aparecer.

## Ruído e realismo

- Cada equipamento tem uma fragilidade própria (lognormal) e o risco cresce 10% por ano de uso.
- Cada bairro tem um tamanho relativo fixo e, a cada dia, uma variação aleatória (gama com média 1).
- Ocorrências seguem perfis por hora e dia da semana diferentes por categoria (estacionamento irregular em horário comercial, perturbação à noite, vandalismo de madrugada).
- **Viés de registro:** o número de ocorrências registradas sobe um pouco onde há mais agentes em turno (até 25% de efeito). Por isso cada ocorrência guarda `agentes_presentes_regiao`, que os modelos usam como exposição (ver `etica-e-limites.md`).
- A escala de agentes segue o efetivo de cada região, não a demanda. É isso que a recomendação de reforço (P4) corrige.
- Eventos: jogos (quarta, quinta e fim de semana nos estádios), shows (sexta e sábado), feiras (abaixo de 10 mil pessoas) e manifestações. Há sempre um grande show no Pacaembu, Centro, na primeira sexta depois da data de referência, para o roteiro da demonstração.
- Clima: normais de São Paulo por mês, ondas de calor no verão e na primavera, pancadas de fim de tarde no verão e chuva espalhada no inverno.
