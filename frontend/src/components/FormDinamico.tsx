import Form from "@rjsf/core";
import type { ErrorSchema, RJSFSchema, UiSchema } from "@rjsf/utils";
import validator from "@rjsf/validator-ajv8";
import { camposOrdenados, type JSONSchema } from "../api/tipos";

/** Rótulo legível para valores de enum: "retorno_proibido" -> "Retorno proibido". */
export function rotuloEnum(v: unknown): string {
  const s = String(v).replace(/_/g, " ").replace(/-/g, " – ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function uiSchemaPara(schema: JSONSchema): UiSchema {
  const campos = camposOrdenados(schema);
  const ui: UiSchema = { "ui:submitButtonOptions": { norender: true }, "ui:order": [...campos.map(([k]) => k), "*"] };
  for (const [nome, p] of campos) {
    if (p.enum) ui[nome] = { "ui:enumNames": p.enum.map(rotuloEnum) };
    if (p.type === "array" && p.items?.enum) {
      ui[nome] = { "ui:widget": "checkboxes", "ui:options": { enumOptions: p.items.enum.map((v) => ({ value: v, label: rotuloEnum(v) })) } };
    }
    if (p.type === "boolean") ui[nome] = { "ui:widget": "checkbox" };
  }
  return ui;
}

/** Valida no navegador com o mesmo JSON Schema que a API usa. Devolve erros por campo. */
export function validarAtributos(schema: JSONSchema, dados: Record<string, unknown>): Record<string, string> {
  const r = validator.validateFormData(dados, schema as RJSFSchema);
  const erros: Record<string, string> = {};
  for (const e of r.errors) {
    const campo = e.name === "required" ? String(e.params?.missingProperty ?? "") : (e.property ?? "").replace(/^\./, "");
    if (campo && !erros[campo]) erros[campo] = traduzir(e.name ?? "", e.message ?? "");
  }
  return erros;
}

function traduzir(regra: string, msg: string) {
  const mapa: Record<string, string> = {
    required: "Campo obrigatório", enum: "Escolha uma das opções", type: "Valor inválido",
    minimum: "Abaixo do mínimo permitido", maximum: "Acima do máximo permitido", pattern: "Formato inválido",
    minItems: "Escolha pelo menos uma opção", format: "Formato inválido",
  };
  return mapa[regra] ?? msg;
}

export function errosParaRjsf(erros: Record<string, string>): ErrorSchema {
  const es: Record<string, { __errors: string[] }> = {};
  for (const [campo, msg] of Object.entries(erros)) es[campo] = { __errors: [msg] };
  return es as ErrorSchema;
}

interface Props {
  schema: JSONSchema;
  dados: Record<string, unknown>;
  onChange: (d: Record<string, unknown>) => void;
  erros?: Record<string, string>;
}

export default function FormDinamico({ schema, dados, onChange, erros = {} }: Props) {
  const temCampos = Object.keys(schema.properties ?? {}).length > 0;
  if (!temCampos) return <p className="text-cinza">Este tipo não tem atributos específicos.</p>;
  return (
    <div className="form-dinamico">
      <Form
        schema={schema as RJSFSchema}
        uiSchema={uiSchemaPara(schema)}
        formData={dados}
        validator={validator}
        onChange={(e) => onChange((e.formData ?? {}) as Record<string, unknown>)}
        extraErrors={errosParaRjsf(erros)}
        showErrorList={false}
        noHtml5Validate
        liveOmit
        omitExtraData
      >
        <></>
      </Form>
    </div>
  );
}
