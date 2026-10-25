import type { Situacao } from "../api/tipos";
import type { EstadoRegiao, Nivel } from "./tipos";

/** Cor = situação (ou o pior alerta). Mesma escala do mapa, dos grupos e das listas. */
export const COR_GRAVIDADE = ["#9a9aa0", "#1f9d55", "#e0a800", "#ea6c13", "#d62828"] as const;
export const ROTULO_GRAVIDADE = ["Desativado ou não instalado", "Operacional", "Manutenção próxima ou em manutenção", "Mau funcionamento ou alerta alto", "Furtado ou alerta crítico"];
/** Símbolo da situação para quem não distingue cores. */
export const SIMBOLO_GRAVIDADE = ["–", "✓", "!", "!", "×"] as const;

export const COR_NIVEL: Record<Nivel, string> = { critica: "#d62828", alta: "#ea6c13", media: "#e0a800", baixa: "#7d8fa3" };
export const ROTULO_NIVEL: Record<Nivel, string> = { critica: "Crítica", alta: "Alta", media: "Média", baixa: "Baixa" };
export const RANK_NIVEL: Record<Nivel, number> = { baixa: 1, media: 2, alta: 3, critica: 4 };

export const COR_REGIAO: Record<EstadoRegiao, string> = { normal: "#1f9d55", atencao: "#e0a800", critica: "#d62828" };
export const ROTULO_REGIAO: Record<EstadoRegiao, string> = { normal: "Normal", atencao: "Atenção", critica: "Crítica" };

export const COR_ORGAO: Record<string, string> = { CET: "#2563eb", GCM: "#7c3aed", PM: "#0f766e", SMT: "#b45309" };
export const corOrgao = (sigla: string) => COR_ORGAO[sigla] ?? "#334155";

export const ROTULO_ESTADO_ALERTA = { aberto: "Aberto", reconhecido: "Reconhecido", em_atendimento: "Em atendimento", resolvido: "Resolvido" } as const;

export const FORMA_ROTULO = { c: "Fiscalização e controle", q: "Monitoramento", t: "Veículos", d: "Agentes" } as const;

/** Mesma regra da API (services/central.gravidade), para a linha do tempo recolorir no navegador. */
export function gravidade(s: Situacao, nivel: number): number {
  if (s === "furtado" || nivel >= 4) return 4;
  if (s === "mau_funcionamento" || nivel === 3) return 3;
  if (s === "desativado" || s === "nao_instalado") return 0;
  if (s === "em_manutencao" || nivel === 2) return 2;
  return 1;
}

export function emRegiao(nome: string | null | undefined) {
  if (!nome) return "";
  return nome === "Centro" ? "no Centro" : `na região ${nome}`;
}

export function idade(iso: string | null | undefined, agora = Date.now()) {
  if (!iso) return "sem dado";
  const s = Math.max(0, Math.round((agora - new Date(iso).getTime()) / 1000));
  if (s < 60) return `há ${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `há ${m} min`;
  const h = Math.round(m / 60);
  if (h < 48) return `há ${h} h`;
  return `há ${Math.round(h / 24)} dias`;
}

export const fmt = (n: number | null | undefined, casas = 0) =>
  n == null ? "—" : n.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
