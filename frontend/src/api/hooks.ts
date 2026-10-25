import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  Agente, Alerta, Bairro, Base, Cidade, Equipamento, EquipamentoResumo, Historico, Ordem, Orgao, Pagina, Plano,
  Registro, Situacao, Tipo,
} from "./tipos";

const LONGO = 5 * 60_000;

export const useTipos = () => useQuery({ queryKey: ["tipos"], queryFn: () => api<Tipo[]>("/tipos-equipamento") });
export const useOrgaos = () => useQuery({ queryKey: ["orgaos"], queryFn: () => api<Orgao[]>("/orgaos"), staleTime: LONGO });
export const useCidades = () => useQuery({ queryKey: ["cidades"], queryFn: () => api<Cidade[]>("/cidades"), staleTime: LONGO });
export const useBairros = (cidadeId: number | null | undefined) =>
  useQuery({
    queryKey: ["bairros", cidadeId], enabled: !!cidadeId, staleTime: LONGO,
    queryFn: () => api<Bairro[]>(`/cidades/${cidadeId}/bairros`),
  });
export const useBases = (orgaoId?: number | null) =>
  useQuery({ queryKey: ["bases", orgaoId], queryFn: () => api<Base[]>("/bases", { params: { orgao_id: orgaoId ?? undefined } }) });

export type FiltrosEquip = {
  q?: string; tipo_id?: number[]; situacao?: Situacao[]; orgao_id?: number[]; bairro_id?: number[]; regiao?: string[];
  status_manutencao?: string[]; sem_sinal?: boolean; score_max?: number; score_min?: number; atributos?: string;
  ordenar?: string; pagina?: number; por_pagina?: number; cidade_id?: number;
};

export const useEquipamentos = (f: FiltrosEquip) =>
  useQuery({
    queryKey: ["equipamentos", f],
    queryFn: () => api<Pagina<EquipamentoResumo>>("/equipamentos", { params: f }),
    placeholderData: keepPreviousData,
  });

export const useEquipamento = (id: number) =>
  useQuery({ queryKey: ["equipamento", id], queryFn: () => api<Equipamento>(`/equipamentos/${id}`) });
export const useHistorico = (id: number) =>
  useQuery({ queryKey: ["equipamento", id, "historico"], queryFn: () => api<Historico[]>(`/equipamentos/${id}/historico`) });
export const usePlanos = (id: number) =>
  useQuery({ queryKey: ["equipamento", id, "planos"], queryFn: () => api<Plano[]>(`/equipamentos/${id}/planos-manutencao`) });
export const useRegistros = (id: number) =>
  useQuery({ queryKey: ["equipamento", id, "registros"], queryFn: () => api<Registro[]>(`/equipamentos/${id}/registros-manutencao`) });
export const useOrdens = (id: number) =>
  useQuery({ queryKey: ["equipamento", id, "ordens"], queryFn: () => api<Ordem[]>(`/equipamentos/${id}/ordens-servico`) });

export interface Resumo {
  total_equipamentos: number;
  disponibilidade: { disponibilidade: number | null; disponiveis: number; indisponiveis: number; fora_da_conta: number; por_situacao: Record<Situacao, number> };
  manutencao: Record<string, number>; sem_sinal: number; score_medio: number; alertas_abertos: Record<string, number>;
}
export const useResumo = () =>
  useQuery({ queryKey: ["resumo"], queryFn: () => api<Resumo>("/indicadores/resumo"), refetchInterval: 30_000 });

export const useAlertas = (params: Record<string, string | number | boolean | string[] | undefined>) =>
  useQuery({
    queryKey: ["alertas", params], refetchInterval: 20_000, placeholderData: keepPreviousData,
    queryFn: () => api<Pagina<Alerta>>("/alertas", { params }),
  });

export const useAgentes = (params: Record<string, string | number | string[] | undefined>) =>
  useQuery({
    queryKey: ["agentes", params], placeholderData: keepPreviousData,
    queryFn: () => api<Pagina<Agente>>("/agentes", { params }),
  });

/** Invalida tudo que depende de um equipamento depois de uma mudança. */
export function useInvalidarEquipamento() {
  const qc = useQueryClient();
  return (id?: number) => {
    if (id) qc.invalidateQueries({ queryKey: ["equipamento", id] });
    qc.invalidateQueries({ queryKey: ["equipamentos"] });
    qc.invalidateQueries({ queryKey: ["resumo"] });
    qc.invalidateQueries({ queryKey: ["alertas"] });
    qc.invalidateQueries({ queryKey: ["qualidade"] });
  };
}

export function useMudarSituacao(id: number) {
  const invalidar = useInvalidarEquipamento();
  return useMutation({
    mutationFn: (b: { situacao: Situacao; motivo: string }) =>
      api<{ equipamento: Equipamento; acoes: string[] }>(`/equipamentos/${id}/situacao`, { method: "PATCH", body: b }),
    onSuccess: () => invalidar(id),
  });
}

export const useStatusApi = () =>
  useQuery({ queryKey: ["status-api"], queryFn: () => api<{ ok: boolean; ia_disponivel: boolean }>("/saude-api"), staleTime: 60_000 });
