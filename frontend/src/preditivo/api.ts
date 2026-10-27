import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  Acertometro, Amanha, CenarioParams, CenarioSalvo, Cartao, DetalheRegiao, EstadoTreino, Modelos, OpcoesCenario, PadroesDescobertos, Plano,
  Briefing, Ranking, Recomendacao, RespostaCopiloto, ResultadoCenario, Retorno, Disponibilidade, Manutencao, RiscoFurto, Expansao,
} from "./tipos";

export const useAmanha = () =>
  useQuery({ queryKey: ["prev", "amanha"], queryFn: () => api<Amanha>("/amanha"), refetchInterval: 5 * 60_000, retry: false });

export const useDetalheRegiao = (id: number | null) =>
  useQuery({ queryKey: ["prev", "regiao", id], enabled: id != null, queryFn: () => api<DetalheRegiao>(`/amanha/regioes/${id}`) });

export const useCartao = (id: number | null) =>
  useQuery({ queryKey: ["prev", "cartao", id], enabled: id != null, queryFn: () => api<Cartao>(`/previsoes/${id}`) });

export const useCartoes = (params: Record<string, string | number | boolean | undefined>, ativo = true) =>
  useQuery({ queryKey: ["prev", "cartoes", params], enabled: ativo, queryFn: () => api<Cartao[]>("/previsoes", { params }) });

export const useRanking = (params: Record<string, string | number | string[] | undefined>) =>
  useQuery({ queryKey: ["prev", "ranking", params], queryFn: () => api<Ranking>("/equipamentos/risco", { params }),
             placeholderData: keepPreviousData, retry: false });

export const useRiscoEquipamento = (id: number) =>
  useQuery({ queryKey: ["prev", "risco-eq", id], queryFn: () => api<{ cartoes: Cartao[]; furto: Cartao | null; mensagem: string | null }>(`/equipamentos/${id}/risco`),
             retry: false });

export const usePlano = () => useQuery({ queryKey: ["prev", "plano"], queryFn: () => api<Plano>("/planejamento/equipes"), retry: false });

export const useRecomendacoes = (params: Record<string, string | undefined>) =>
  useQuery({ queryKey: ["prev", "recs", params], queryFn: () => api<Recomendacao[]>("/recomendacoes", { params }) });

export interface DecisaoIn { acao: "aceitar" | "ajustar" | "rejeitar"; motivo?: string; parametros?: Record<string, unknown> }

export function useDecidir() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ previsaoId, ...body }: DecisaoIn & { previsaoId: number }) =>
      api<Cartao>(`/previsoes/${previsaoId}/decisao`, { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prev"] }),
  });
}

export function useDecidirRecomendacao() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: DecisaoIn & { id: number }) => api<Recomendacao>(`/recomendacoes/${id}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prev"] }),
  });
}

export function useOrdensLote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (previsao_ids: number[]) =>
      api<{ abertas: { previsao_id: number; ordem_servico_id?: number }[]; puladas: { previsao_id: number; motivo: string }[] }>(
        "/equipamentos/risco/ordens", { method: "POST", body: { previsao_ids } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prev"] }),
  });
}

export function useRecalcularPlano() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { max_deslocamentos?: number; min_por_regiao?: number; regioes_fixas?: string[]; salvar?: boolean }) =>
      api<Plano>("/planejamento/equipes/recalcular", { method: "POST", body }),
    onSuccess: (_d, v) => { if (v.salvar) qc.invalidateQueries({ queryKey: ["prev"] }); },
  });
}

export function useRecalcularPrevisoes() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<Record<string, number>>("/previsoes/recalcular", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prev"] }),
  });
}

export function useEditarClima() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { inicio: string; fim: string; chuva_mm?: number; temperatura_c?: number; alerta_tempestade?: boolean }) =>
      api<{ horas_alteradas: number }>("/clima/previsao", { method: "PUT", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prev", "amanha"] }),
  });
}

export const useTreino = () =>
  useQuery({
    queryKey: ["prev", "treino"], queryFn: () => api<EstadoTreino>("/modelos/treino"), retry: false,
    refetchInterval: (q) => (q.state.data?.situacao === "rodando" ? 3_000 : 60_000),
  });

export const useModelos = () => useQuery({ queryKey: ["prev", "modelos"], queryFn: () => api<Modelos>("/modelos") });

export const useAcertometro = (dias: number) =>
  useQuery({ queryKey: ["prev", "acertometro", dias], queryFn: () => api<Acertometro>("/modelos/acertometro", { params: { dias } }),
             refetchInterval: 10 * 60_000 });

export function useTreinar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<EstadoTreino>("/modelos/treinar", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prev", "treino"] }),
  });
}

export const useOpcoesCenario = () =>
  useQuery({ queryKey: ["prev", "cenarios", "opcoes"], queryFn: () => api<OpcoesCenario>("/cenarios/opcoes"), staleTime: 5 * 60_000 });

export const useCenarios = () => useQuery({ queryKey: ["prev", "cenarios", "lista"], queryFn: () => api<CenarioSalvo[]>("/cenarios") });

export const useCenario = (id: number | null) =>
  useQuery({ queryKey: ["prev", "cenarios", id], enabled: id != null, queryFn: () => api<CenarioSalvo>(`/cenarios/${id}`) });

export const useSimular = () =>
  useMutation({ mutationFn: (p: CenarioParams) => api<ResultadoCenario>("/cenarios/simular", { method: "POST", body: p }) });

export function useSalvarCenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { nome: string; descricao?: string; parametros: CenarioParams }) => api<CenarioSalvo>("/cenarios", { method: "POST", body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prev", "cenarios", "lista"] }),
  });
}

export function useRemoverCenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/cenarios/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prev", "cenarios", "lista"] }),
  });
}

export const useRetorno = (dias: number) =>
  useQuery({ queryKey: ["prev", "retorno", dias], queryFn: () => api<Retorno>("/recomendacoes/retorno", { params: { dias } }) });

export const usePadroes = () =>
  useQuery({ queryKey: ["prev", "padroes"], queryFn: () => api<PadroesDescobertos>("/modelos/padroes-descobertos"), retry: false,
             staleTime: 10 * 60_000 });

export const usePerguntasProntas = () =>
  useQuery({ queryKey: ["prev", "copiloto", "prontas"], queryFn: () => api<{ ia_disponivel: boolean; perguntas: { id: string; texto: string }[] }>("/copiloto/perguntas-prontas"),
             staleTime: 5 * 60_000 });

export const usePerguntar = () =>
  useMutation({ mutationFn: (b: { pergunta?: string; pronta?: string; historico?: { papel: "user" | "assistant"; texto: string }[] }) =>
    api<RespostaCopiloto>("/copiloto/perguntar", { method: "POST", body: b }) });

export const useBriefing = () => useQuery({ queryKey: ["prev", "briefing"], queryFn: () => api<Briefing>("/briefing/hoje"), retry: false });

export function useGerarBriefing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<Briefing>("/briefing/gerar", { method: "POST" }),
    onSuccess: (b) => qc.setQueryData(["prev", "briefing"], b),
  });
}

// Fase 12
export const useDisponibilidade = (grupo: "regiao" | "tipo") =>
  useQuery({ queryKey: ["prev", "disp", grupo], queryFn: () => api<Disponibilidade>("/tendencias/disponibilidade", { params: { grupo } }),
             retry: false, placeholderData: keepPreviousData });

export const useManutencao = () =>
  useQuery({ queryKey: ["prev", "manutencao"], queryFn: () => api<Manutencao>("/tendencias/manutencao"), retry: false });

export const useRiscoFurto = (params: Record<string, string | number | string[] | undefined>) =>
  useQuery({ queryKey: ["prev", "furto", params], queryFn: () => api<RiscoFurto>("/furtos/risco", { params }),
             placeholderData: keepPreviousData, retry: false });

export const useExpansao = (criterio: string, n: number) =>
  useQuery({ queryKey: ["prev", "expansao", criterio, n], queryFn: () => api<Expansao>("/expansao/sugestoes", { params: { criterio, n } }),
             placeholderData: keepPreviousData, retry: false, staleTime: 5 * 60_000 });
