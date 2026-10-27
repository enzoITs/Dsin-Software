import { describe, expect, it } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import ModoApresentacao, { ROTEIRO, iniciarApresentacao } from "../components/ModoApresentacao";

function Onde() {
  return <div data-testid="rota">{useLocation().pathname}</div>;
}

describe("Modo apresentação", () => {
  it("segue o roteiro com PageDown e PageUp e navega para cada tela", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <ModoApresentacao />
        <Routes><Route path="*" element={<Onde />} /></Routes>
      </MemoryRouter>,
    );
    expect(screen.queryByLabelText("Modo apresentação")).toBeNull();
    act(() => iniciarApresentacao());
    expect(screen.getByText(`Passo 1 de ${ROTEIRO.length}`)).toBeTruthy();
    expect(screen.getByTestId("rota").textContent).toBe(ROTEIRO[0].rota);
    fireEvent.keyDown(window, { key: "PageDown" });
    expect(screen.getByText(`Passo 2 de ${ROTEIRO.length}`)).toBeTruthy();
    expect(screen.getByTestId("rota").textContent).toBe(ROTEIRO[1].rota);
    fireEvent.keyDown(window, { key: "PageUp" });
    expect(screen.getByTestId("rota").textContent).toBe(ROTEIRO[0].rota);
    fireEvent.click(screen.getByLabelText("Sair da apresentação"));
    expect(screen.queryByLabelText("Modo apresentação")).toBeNull();
  });

  it("todo passo diz o que mostrar e o que dizer", () => {
    for (const p of ROTEIRO) {
      expect(p.rota.startsWith("/")).toBe(true);
      expect(p.mostrar.length).toBeGreaterThan(0);
      expect(p.dizer.length).toBeGreaterThan(10);
    }
    expect(ROTEIRO.at(-1)!.dizer).toContain("PROMETHEUS");
  });
});
