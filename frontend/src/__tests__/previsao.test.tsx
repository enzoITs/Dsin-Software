import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import CartaoPrevisao from "../preditivo/CartaoPrevisao";
import { efeitoTexto, faixaTexto, valorPrincipal } from "../preditivo/formato";
import type { Cartao } from "../preditivo/tipos";

const cartao: Cartao = {
  id: "prev_1", previsao_id: 1, modulo: "P1", modulo_nome: "Risco de falha de equipamento",
  o_que_preve: "Probabilidade de falha de RAD-0042 nos próximos 7 dias",
  alvo: { tipo: "equipamento", id: 42, nome: "RAD-0042", regiao: "Centro" },
  horizonte: { inicio: "2026-10-26T03:00:00Z", fim: "2026-11-02T03:00:00Z" }, valor: 0.68, unidade: "probabilidade",
  faixa: { inferior: 0.55, superior: 0.79 }, nivel: "MUITO_ALTO",
  dados_considerados: ["Histórico de falhas dos últimos 180 dias", "Previsão de temperatura"],
  fatores: [{ descricao: "Temperatura prevista de até 34 °C nos próximos 7 dias", efeito: 0.18 },
            { descricao: "Nenhuma falha nos últimos 180 dias", efeito: -0.06 }],
  como_ajuda: "Antecipar a manutenção evita perder a fiscalização de velocidade neste trecho",
  acao_recomendada: { texto: "Abrir ordem de serviço preventiva para RAD-0042 até 29/10", tipo: "ABRIR_ORDEM_SERVICO", parametros: {} },
  qualidade_do_modelo: { selo: { texto: "De cada 50 equipamentos que o modelo aponta, 8 falham", confianca: "moderada", ganho_pct: 8 } },
  confianca: { nivel: "moderada", aviso: "Confiança moderada: a faixa mostra a incerteza." },
  modelo: { nome: "falha_equipamento_7d", versao: "2026-10-25.1" }, gerado_em: "2026-10-26T06:00:00Z", valor_real: null,
  dados_sinteticos: true, extra: {}, recomendacao: null,
};

function montar(c: Cartao) {
  return render(
    <QueryClientProvider client={new QueryClient()}><MemoryRouter><CartaoPrevisao c={c} /></MemoryRouter></QueryClientProvider>,
  );
}

describe("Cartão de Previsão", () => {
  it("responde às três perguntas do enunciado, com títulos fixos", () => {
    montar(cartao);
    expect(screen.getByText("O que estamos prevendo")).toBeTruthy();
    expect(screen.getByText("Com base em quê")).toBeTruthy();
    expect(screen.getByText("Como isso ajuda")).toBeTruthy();
    expect(screen.getByText(cartao.o_que_preve)).toBeTruthy();
    expect(screen.getByText("68%")).toBeTruthy();
    expect(screen.getByText(/Temperatura prevista de até 34 °C/)).toBeTruthy();
    expect(screen.getByText(cartao.como_ajuda!)).toBeTruthy();
  });
  it("tem os botões de decisão e mostra a qualidade e a confiança", () => {
    montar(cartao);
    for (const b of ["Aceitar", "Ajustar", "Rejeitar"]) expect(screen.getByRole("button", { name: new RegExp(b) })).toBeTruthy();
    expect(screen.getByText(/8 falham/)).toBeTruthy();
    expect(screen.getByText(/Confiança moderada/)).toBeTruthy();
    expect(screen.getByText(/Dados sintéticos/i)).toBeTruthy();
  });
  it("mostra a decisão já tomada no lugar dos botões", () => {
    montar({ ...cartao, recomendacao: { id: 1, estado: "rejeitada", decidido_por: "Ana", decidido_em: "2026-10-26T10:00:00Z",
                                        motivo: "Será substituído", resultado: null } });
    expect(screen.queryByRole("button", { name: /Aceitar/ })).toBeNull();
    expect(screen.getByText(/Rejeitada/)).toBeTruthy();
    expect(screen.getByText(/Será substituído/)).toBeTruthy();
  });
});

describe("formatação", () => {
  it("valores e faixas em português", () => {
    expect(valorPrincipal("probabilidade", 0.68)).toBe("68%");
    expect(valorPrincipal("índice", 74.6)).toBe("75");
    expect(valorPrincipal("equipes", 1)).toBe("1 equipe");
    expect(faixaTexto("ocorrências", 2.1, 6.8)).toBe("entre 2,1 e 6,8");
    expect(efeitoTexto("probabilidade", 0.18)).toBe("+18,0 p.p.");
    expect(efeitoTexto("índice", -3)).toBe("−3,0 pontos");
  });
});

describe("Alerta preventivo na central", () => {
  const base = {
    id: 9, tipo: "previsao_risco_regiao", regra: "previsao_risco_regiao", rotulo_regra: "Previsão: risco alto na região",
    nivel: "alta" as const, nivel_inicial: "media" as const, motivos_nivel: [], estado: "aberto" as const,
    mensagem: "Previsto para hoje, 20 h: risco muito alto na região Centro (índice 81 às 20 h)", contador: 1,
    criado_em: new Date().toISOString(), ultima_ocorrencia_em: null, regiao: "Centro", lon: -46.63, lat: -23.55,
    equipamento_id: null, codigo_interno: null, tipo_equipamento: null, orgao: null, dispositivo_iot_id: null, agente_alvo_id: null,
    agente: null, ordem_servico_id: null, incidente_id: null, membros: 0, equipamentos: [], silenciado_ate: null, silenciado_motivo: null,
    reconhecido_em: null, reconhecido_por: null, resolvido_em: null, resolvido_por: null, resolucao: null, severidade: "atencao",
    simulado: false,
  };

  it("mostra que é previsão, para quando e o botão que abre o cartão", async () => {
    const { CardAlerta } = await import("../central/PainelAlertas");
    const daqui3h = new Date(Date.now() + 3 * 3_600_000 + 60_000).toISOString();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CardAlerta a={{ ...base, preditivo: { previsao_id: 77, modulo: "P3", previsto_para: daqui3h, ate: daqui3h, antecedencia_min: 180 } }} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Previsão")).toBeTruthy();
    expect(screen.getByText(/em 3 h/)).toBeTruthy();
    expect(screen.getByText(/Ver previsão/)).toBeTruthy();
    expect(screen.queryByText(/Atribuir/)).toBeNull();
  });

  it("calcula a antecedência na hora", async () => {
    const { antecedencia } = await import("../central/PainelAlertas");
    const agora = Date.parse("2026-10-30T18:00:00Z");
    expect(antecedencia("2026-10-30T20:30:00Z", undefined, agora)).toBe("em 2 h 30 min");
    expect(antecedencia("2026-10-30T18:45:00Z", undefined, agora)).toBe("em 45 min");
    expect(antecedencia("2026-10-30T17:00:00Z", "2026-10-30T19:00:00Z", agora)).toBe("em andamento");
  });
});

describe("Cenário e se", () => {
  it("mostra o que muda, por região, e o risco não coberto", async () => {
    const { Resultado } = await import("../pages/Cenarios");
    const r = {
      origem: "2026-10-30T21:00:00Z", parametros: {}, aplicado: {}, segundos: 4.2,
      frases: ["Ocorrências previstas nas próximas 72 h: 1.229 → 1.248 (+1,5%)"],
      regioes: [{ regiao: "Centro", ocorrencias_base: 380, ocorrencias_cenario: 396, diferenca_pct: 4.2, indice_medio_base: 28,
                  indice_medio_cenario: 35, indice_max_base: 57, indice_max_cenario: 57, nivel_max_base: "ALTO", nivel_max_cenario: "ALTO",
                  periodos_alto_base: 1, periodos_alto_cenario: 2 }],
      periodos: [{ inicio: "2026-10-30T21:00:00Z", fim: "2026-10-31T03:00:00Z", rotulo: "Sexta (30/10), 18 h às 24 h",
                   regioes: [{ regiao: "Centro", indice_base: 57, nivel_base: "ALTO", indice_cenario: 77, nivel_cenario: "MUITO_ALTO" }] }],
      equipes: { base: { nao_coberto_escala: 5366, nao_coberto_otimizado: 3745, recomendacoes: [] },
                 cenario: { nao_coberto_escala: 10507, nao_coberto_otimizado: 7911, recomendacoes: ["reforçar a região Centro"] } },
    };
    render(<Resultado r={r} />);
    expect(screen.getByText(r.frases[0])).toBeTruthy();
    expect(screen.getByText("Centro", { selector: "td" })).toBeTruthy();
    expect(screen.getByText("10.507")).toBeTruthy();
    expect(screen.getByText(/Nada foi alterado no sistema/)).toBeTruthy();
  });
});

describe("Copiloto", () => {
  it("renderiza listas, negrito e o link do cartão", async () => {
    const { default: TextoRico } = await import("../preditivo/TextoRico");
    const abertos: number[] = [];
    render(<TextoRico texto={"**Centro, sexta à noite** [prev_42]\n\n- Oeste: alto\n- Sul: moderado"} abrir={(id) => abertos.push(id)} />);
    expect(screen.getByText("Centro, sexta à noite").tagName).toBe("B");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    screen.getByRole("button", { name: "cartão" }).click();
    expect(abertos).toEqual([42]);
  });
});
