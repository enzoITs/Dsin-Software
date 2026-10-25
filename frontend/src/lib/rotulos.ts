import type { Situacao, StatusManutencao } from "../api/tipos";

export const SITUACAO: Record<Situacao, { rotulo: string; cor: string }> = {
  operacional: { rotulo: "Operacional", cor: "var(--color-ok)" },
  mau_funcionamento: { rotulo: "Mau funcionamento", cor: "var(--color-atencao)" },
  em_manutencao: { rotulo: "Em manutenção", cor: "var(--color-atencao)" },
  furtado: { rotulo: "Furtado", cor: "var(--color-critico)" },
  nao_instalado: { rotulo: "Ainda não instalado", cor: "var(--color-inativo)" },
  desativado: { rotulo: "Desativado", cor: "var(--color-inativo)" },
};
export const ORDEM_SITUACAO: Situacao[] = ["operacional", "mau_funcionamento", "em_manutencao", "furtado", "nao_instalado", "desativado"];

export const MANUTENCAO: Record<StatusManutencao, string> = {
  em_dia: "Em dia", proxima: "Manutenção próxima", vencida: "Manutenção vencida",
};

export const CATEGORIA_AGENTE = {
  agente_transito: "Agente de trânsito", guarda_municipal: "Guarda municipal", policial_militar: "Policial militar",
} as const;
export const SITUACAO_AGENTE = { em_atividade: "Em atividade", em_pausa: "Em pausa", fora_de_escala: "Fora de escala" } as const;

export function corScore(s: number) {
  return s >= 80 ? "var(--color-ok)" : s >= 50 ? "var(--color-atencao)" : "var(--color-critico)";
}

export function dataHora(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}
export function data(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(iso + "T12:00:00") : new Date(iso);
  return d.toLocaleDateString("pt-BR");
}
export function haQuanto(iso: string | null) {
  if (!iso) return "nunca";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "agora";
  if (min < 60) return `há ${min} min`;
  const h = Math.round(min / 60);
  if (h < 48) return `há ${h} h`;
  return `há ${Math.round(h / 24)} dias`;
}
