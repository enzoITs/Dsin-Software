import { describe, expect, it } from "vitest";
import { contarFiltros, lerFiltros, paramsApi } from "../central/filtros";
import { emRegiao, gravidade, idade } from "../central/visual";

describe("cor do ponto no mapa (mesma regra da API)", () => {
  it("furto ou alerta crítico é vermelho, mesmo com situação operacional", () => {
    expect(gravidade("furtado", 0)).toBe(4);
    expect(gravidade("operacional", 4)).toBe(4);
  });
  it("mau funcionamento ou alerta alto é laranja", () => {
    expect(gravidade("mau_funcionamento", 0)).toBe(3);
    expect(gravidade("operacional", 3)).toBe(3);
  });
  it("em manutenção ou alerta médio é amarelo; desativado é cinza", () => {
    expect(gravidade("em_manutencao", 0)).toBe(2);
    expect(gravidade("operacional", 2)).toBe(2);
    expect(gravidade("desativado", 0)).toBe(0);
    expect(gravidade("operacional", 0)).toBe(1);
  });
});

describe("filtros no endereço da página", () => {
  it("lê e converte para a API", () => {
    const f = lerFiltros(new URLSearchParams("regiao=Norte&tipo_id=2&sem_sinal=1&nivel=critica&area=-46.6 -23.5,-46.5 -23.5,-46.5 -23.4"));
    expect(f.regiao).toEqual(["Norte"]);
    expect(f.tipo_id).toEqual([2]);
    expect(f.sem_sinal).toBe(true);
    expect(f.area).toHaveLength(3);
    const p = paramsApi(f);
    expect(p.sem_sinal).toBe(true);
    expect(p.area).toBe("-46.600000 -23.500000,-46.500000 -23.500000,-46.500000 -23.400000");
    expect(contarFiltros(f)).toBe(5);
  });
  it("sem filtros não manda nada", () => {
    const p = paramsApi(lerFiltros(new URLSearchParams("")));
    expect(p.sem_sinal).toBeUndefined();
    expect(p.area).toBeUndefined();
    expect(p.score_max).toBeUndefined();
  });
});

describe("textos", () => {
  it("região com preposição certa", () => {
    expect(emRegiao("Centro")).toBe("no Centro");
    expect(emRegiao("Norte")).toBe("na região Norte");
  });
  it("idade do dado", () => {
    const agora = Date.parse("2026-10-24T12:00:00Z");
    expect(idade("2026-10-24T11:59:30Z", agora)).toBe("há 30 s");
    expect(idade("2026-10-24T11:50:00Z", agora)).toBe("há 10 min");
    expect(idade(null, agora)).toBe("sem dado");
  });
});
