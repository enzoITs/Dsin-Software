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
