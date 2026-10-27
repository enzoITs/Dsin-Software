/** Formatação e cores da Parte 3, em português do Brasil. */

export const COR_NIVEL: Record<string, string> = {
  BAIXO: "#1f9d55", MODERADO: "#d99a00", ALTO: "#ff4f00", MUITO_ALTO: "#d62828",
  ABAIXO: "#1f9d55", NORMAL: "#6b6b6b", ACIMA: "#ff4f00", MUITO_ACIMA: "#d62828",
  ATENCAO: "#d99a00", ABAIXO_META: "#d62828",
};
export const ROTULO_NIVEL: Record<string, string> = {
  BAIXO: "Baixo", MODERADO: "Moderado", ALTO: "Alto", MUITO_ALTO: "Muito alto",
  ABAIXO: "Abaixo do normal", NORMAL: "Normal", ACIMA: "Acima do normal", MUITO_ACIMA: "Muito acima do normal",
  ATENCAO: "Atenção", ABAIXO_META: "Abaixo da meta",
};

export const num = (v: number, casas = 1) => v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
export const pct = (v: number, casas = 0) => `${(v * 100).toLocaleString("pt-BR", { maximumFractionDigits: casas })}%`;

export function valorPrincipal(unidade: string, v: number): string {
  if (unidade === "probabilidade") return v < 0.01 ? pct(v, 2) : pct(v, 1);
  if (unidade === "disponibilidade") return pct(v, 1);
  if (unidade === "técnicos-dia") return `${num(v, 0)} técnicos-dia`;
  if (unidade === "índice") return `${Math.round(v)}`;
  if (unidade === "equipes") return `${Math.round(v)} ${Math.round(v) === 1 ? "equipe" : "equipes"}`;
  return num(v);
}

export function faixaTexto(unidade: string, a: number | null, b: number | null): string | null {
  if (a == null || b == null) return null;
  if (unidade === "probabilidade") return b < 0.01 ? `entre ${pct(a, 2)} e ${pct(b, 2)}` : `entre ${pct(a)} e ${pct(b)}`;
  if (unidade === "disponibilidade") return `entre ${pct(a, 1)} e ${pct(b, 1)}`;
  if (unidade === "técnicos-dia") return `entre ${num(a, 0)} e ${num(b, 0)}`;
  if (unidade === "índice") return `entre ${Math.round(a)} e ${Math.round(b)}`;
  if (unidade === "equipes") return `entre ${Math.round(a)} e ${Math.round(b)} equipes pela demanda`;
  return `entre ${num(a)} e ${num(b)}`;
}

export function efeitoTexto(unidade: string, e: number): string {
  const s = e > 0 ? "+" : e < 0 ? "−" : "";
  const a = Math.abs(e);
  if (unidade === "probabilidade") return `${s}${num(a * 100, a < 0.01 ? 2 : 1)} p.p.`;
  if (unidade === "disponibilidade") return `${s}${num(a, 1)} p.p.`;
  if (unidade === "técnicos-dia") return `${s}${num(a, 1)}`;
  if (unidade === "índice") return `${s}${num(a, 1)} pontos`;
  if (unidade === "ocorrências") return `${s}${num(a, 2)}`;
  return `${s}${num(a, 0)}`;
}

export const dataHora = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
export const dia = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" });
