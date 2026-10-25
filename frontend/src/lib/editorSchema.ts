import { camposOrdenados, type JSONSchema } from "../api/tipos";

export type TipoCampo = "texto" | "numero" | "inteiro" | "simnao" | "opcoes" | "multipla" | "data";

export interface CampoEditor {
  chave: string;
  titulo: string;
  tipo: TipoCampo;
  obrigatorio: boolean;
  opcoes: string;
  minimo: string;
  maximo: string;
}

export const ROTULO_TIPO_CAMPO: Record<TipoCampo, string> = {
  texto: "Texto", numero: "Número decimal", inteiro: "Número inteiro", simnao: "Sim ou não",
  opcoes: "Uma opção da lista", multipla: "Várias opções da lista", data: "Data",
};

/** "Velocidade máxima (km/h)" -> "velocidade_maxima_km_h" */
export function chaveDe(titulo: string): string {
  return titulo
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "")
    .slice(0, 40) || "campo";
}

function listaOpcoes(s: string): string[] {
  return [...new Set(s.split(",").map((x) => x.trim()).filter(Boolean))];
}

export function camposParaSchema(campos: CampoEditor[]): JSONSchema {
  const properties: Record<string, JSONSchema> = {};
  const required: string[] = [];
  for (const c of campos) {
    if (!c.chave) continue;
    let p: JSONSchema;
    switch (c.tipo) {
      case "numero": case "inteiro":
        p = { type: c.tipo === "numero" ? "number" : "integer", title: c.titulo };
        if (c.minimo !== "") p.minimum = Number(c.minimo);
        if (c.maximo !== "") p.maximum = Number(c.maximo);
        break;
      case "simnao": p = { type: "boolean", title: c.titulo }; break;
      case "opcoes": p = { type: "string", title: c.titulo, enum: listaOpcoes(c.opcoes) }; break;
      case "multipla":
        p = { type: "array", title: c.titulo, items: { type: "string", enum: listaOpcoes(c.opcoes) }, uniqueItems: true };
        break;
      case "data": p = { type: "string", title: c.titulo, format: "date" }; break;
      default: p = { type: "string", title: c.titulo };
    }
    properties[c.chave] = p;
    if (c.obrigatorio) required.push(c.chave);
  }
  return { type: "object", required, properties, "x-ordem": Object.keys(properties) };
}

export function schemaParaCampos(schema: JSONSchema): CampoEditor[] {
  const req = new Set(schema.required ?? []);
  return camposOrdenados(schema).map(([chave, p]) => {
    let tipo: TipoCampo = "texto";
    if (p.type === "number") tipo = "numero";
    else if (p.type === "integer") tipo = "inteiro";
    else if (p.type === "boolean") tipo = "simnao";
    else if (p.type === "array") tipo = "multipla";
    else if (p.enum) tipo = "opcoes";
    else if (p.format === "date") tipo = "data";
    const opcoes = (p.enum ?? p.items?.enum ?? []).join(", ");
    return {
      chave, titulo: p.title ?? chave, tipo, obrigatorio: req.has(chave), opcoes,
      minimo: p.minimum != null ? String(p.minimum) : "", maximo: p.maximum != null ? String(p.maximum) : "",
    };
  });
}

/** Problemas que impedem salvar, em linguagem simples. */
export function problemas(campos: CampoEditor[]): string[] {
  const out: string[] = [];
  const vistos = new Set<string>();
  campos.forEach((c, i) => {
    const n = c.titulo || `Campo ${i + 1}`;
    if (!c.titulo.trim()) out.push(`Campo ${i + 1}: dê um nome.`);
    if (vistos.has(c.chave)) out.push(`${n}: nome repetido.`);
    vistos.add(c.chave);
    if ((c.tipo === "opcoes" || c.tipo === "multipla") && listaOpcoes(c.opcoes).length < 2) out.push(`${n}: informe pelo menos duas opções separadas por vírgula.`);
    if (c.minimo !== "" && c.maximo !== "" && Number(c.minimo) > Number(c.maximo)) out.push(`${n}: mínimo maior que o máximo.`);
  });
  return out;
}
