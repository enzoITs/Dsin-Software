import { describe, expect, it } from "vitest";
import { codigoDoQr } from "../pages/Campo";
import { camposParaSchema, chaveDe, problemas, schemaParaCampos, type CampoEditor } from "../lib/editorSchema";
import { validarAtributos } from "../components/FormDinamico";

describe("QR Code do modo campo", () => {
  it("lê URL do Atalaia e código digitado", () => {
    expect(codigoDoQr("http://192.168.0.10:5173/campo/RAD-0042")).toBe("RAD-0042");
    expect(codigoDoQr(" cam-0315 ")).toBe("CAM-0315");
  });
  it("recusa QR de outra coisa", () => {
    expect(codigoDoQr("https://exemplo.com/promo")).toBeNull();
  });
});

const fases: CampoEditor = { chave: "fases", titulo: "Fases", tipo: "inteiro", obrigatorio: true, opcoes: "", minimo: "2", maximo: "8" };
const acesso: CampoEditor = { chave: "acesso", titulo: "Acesso", tipo: "opcoes", obrigatorio: false, opcoes: "Veicular, Pedestre", minimo: "", maximo: "" };

describe("editor de tipos", () => {
  it("gera chave sem acento", () => {
    expect(chaveDe("Velocidade máxima (km/h)")).toBe("velocidade_maxima_km_h");
  });
  it("gera JSON Schema e volta para os mesmos campos", () => {
    const schema = camposParaSchema([fases, acesso]);
    expect(schema.required).toEqual(["fases"]);
    expect(schema.properties!.fases).toMatchObject({ type: "integer", minimum: 2, maximum: 8 });
    expect(schema.properties!.acesso.enum).toEqual(["Veicular", "Pedestre"]);
    const volta = schemaParaCampos(schema);
    expect(volta.map((c) => [c.chave, c.tipo, c.obrigatorio])).toEqual([["fases", "inteiro", true], ["acesso", "opcoes", false]]);
  });
  it("aponta problemas antes de salvar", () => {
    expect(problemas([{ ...acesso, opcoes: "só uma" }])).toHaveLength(1);
    expect(problemas([fases, { ...fases }])).toContain("Fases: nome repetido.");
    expect(problemas([{ ...fases, minimo: "9" }])[0]).toMatch(/mínimo maior/);
  });
});

describe("validação do formulário dinâmico", () => {
  const schema = camposParaSchema([fases, acesso]);
  it("acusa obrigatório e limites por campo", () => {
    expect(validarAtributos(schema, {})).toEqual({ fases: "Campo obrigatório" });
    expect(validarAtributos(schema, { fases: 12 })).toEqual({ fases: "Acima do máximo permitido" });
    expect(validarAtributos(schema, { fases: 3, acesso: "Veicular" })).toEqual({});
  });
});
