import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  AgenteProximo, AlertaC, EstadoCentral, Fila, Indicadores, LinhaDoTempo, ListaAlertas, RegiaoSaude,
} from "./tipos";

type P = Record<string, string | number | boolean | (string | number)[] | undefined>;

/** Indicadores e regiões são recalculados na API a cada 5 s (doc: "frequência do painel"). */
const A_CADA_5S = 5_000;

export const useEstadoCentral = (params: P, chave: string) =>
  useQuery({
    queryKey: ["central", "estado", chave],
    queryFn: () => api<EstadoCentral>("/central/estado", { params }),
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });

export const useRegioesGeo = () =>
  useQuery({ queryKey: ["central", "regioes-geo"], queryFn: () => api<GeoJSON.FeatureCollection>("/central/regioes.geojson"), staleTime: Infinity });

export const useIndicadores = (params: P, chave: string, ativo = true) =>
  useQuery({
    queryKey: ["central", "indicadores", chave], queryFn: () => api<Indicadores>("/indicadores", { params }),
    refetchInterval: ativo ? A_CADA_5S : false, placeholderData: keepPreviousData,
  });

export const useRegioesSaude = (params: P, chave: string) =>
  useQuery({
    queryKey: ["central", "regioes", chave], queryFn: () => api<RegiaoSaude[]>("/regioes/saude", { params }),
    refetchInterval: A_CADA_5S, placeholderData: keepPreviousData,
  });

export const useAlertasCentral = (params: P, chave: string, extra: P, limite: number) =>
  useQuery({
    queryKey: ["central", "alertas", chave, extra, limite],
    queryFn: () => api<ListaAlertas>("/alertas", { params: { ...params, ...extra, agrupar: true, por_pagina: limite } }),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });

export const useAlerta = (id: number | null) =>
  useQuery({ queryKey: ["central", "alerta", id], enabled: id != null, queryFn: () => api<AlertaC>(`/alertas/${id}`) });

export const useAlertasEquipamento = (id: number | null) =>
  useQuery({
    queryKey: ["central", "alertas-equip", id], enabled: id != null,
    queryFn: () => api<ListaAlertas>("/alertas", { params: { equipamento_id: id ?? undefined, por_pagina: 20 } }),
  });

export const useFila = (params: P, chave: string, ativo: boolean) =>
  useQuery({
    queryKey: ["central", "fila", chave], enabled: ativo, queryFn: () => api<Fila>("/manutencao/fila", { params: { ...params, limite: 300 } }),
    placeholderData: keepPreviousData, refetchInterval: 60_000,
  });

export const useAgentesProximos = (alertaId: number | null) =>
  useQuery({
    queryKey: ["central", "proximos", alertaId], enabled: alertaId != null,
    queryFn: () => api<AgenteProximo[]>(`/alertas/${alertaId}/agentes-proximos`), refetchInterval: 15_000,
  });

export const useLinhaDoTempo = (params: P, chave: string, minutos: number) =>
  useQuery({
    queryKey: ["central", "linha", chave, minutos], enabled: minutos > 0,
    queryFn: () => api<LinhaDoTempo>("/linha-do-tempo", { params: { ...params, minutos_atras: minutos } }),
    placeholderData: keepPreviousData, staleTime: 20_000,
  });

export const useSerieHora = () =>
  useQuery({
    queryKey: ["central", "serie"], queryFn: () => api<LinhaDoTempo>("/linha-do-tempo", { params: { minutos_atras: 0 } }),
    refetchInterval: 60_000, select: (d) => d.serie,
  });

export const useCalor = (params: P, chave: string, ativo: boolean) =>
  useQuery({
    queryKey: ["central", "calor", chave], enabled: ativo,
    queryFn: () => api<GeoJSON.FeatureCollection>("/central/calor", { params }), refetchInterval: 60_000,
  });

export interface Resumo { texto: string; fonte: "ia" | "modelo"; texto_modelo: string }
export const useResumoTurno = (ativo: boolean) =>
  useQuery({ queryKey: ["central", "resumo"], enabled: ativo, queryFn: () => api<Resumo>("/resumo-turno"), staleTime: 30_000 });

/** Depois de qualquer ação, a lista e os números são recarregados (o WebSocket também avisa). */
function useInvalidarCentral() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["alertas", "alerta", "alertas-equip", "indicadores", "regioes", "proximos", "fila"]) {
      qc.invalidateQueries({ queryKey: ["central", k] });
    }
  };
}

export function useAcaoAlerta() {
  const inv = useInvalidarCentral();
  return useMutation({
    mutationFn: (b: { id: number; acao: "reconhecer" | "silenciar" | "resolver" | "reabrir_som"; motivo?: string; minutos?: number }) =>
      api<AlertaC>(`/alertas/${b.id}`, { method: "PATCH", body: { acao: b.acao, motivo: b.motivo, minutos: b.minutos } }),
    onSuccess: inv,
  });
}

export function useAtribuir() {
  const inv = useInvalidarCentral();
  return useMutation({
    mutationFn: (b: { id: number; agente_id: number }) =>
      api<AlertaC>(`/alertas/${b.id}/atribuir`, { method: "POST", body: { agente_id: b.agente_id } }),
    onSuccess: inv,
  });
}

export function useAbrirOS() {
  const inv = useInvalidarCentral();
  return useMutation({
    mutationFn: (id: number) => api<AlertaC & { ordem_servico: { id: number } }>(`/alertas/${id}/ordem-servico`, { method: "POST", body: {} }),
    onSuccess: inv,
  });
}

export function useSimular() {
  const inv = useInvalidarCentral();
  return useMutation({
    mutationFn: (b: { tipo: string; regiao: string; quantidade?: number }) =>
      api<{ afetados: string[]; alertas: AlertaC[] }>("/simulacao/incidente", { method: "POST", body: b }),
    onSuccess: inv,
  });
}

export function useRestaurar() {
  const inv = useInvalidarCentral();
  return useMutation({
    mutationFn: () => api<{ alertas_resolvidos: number }>("/simulacao/restaurar", { method: "POST" }),
    onSuccess: inv,
  });
}

export function usePerguntar() {
  return useMutation({
    mutationFn: (q: string) =>
      api<{ texto: string; fonte: string; regiao: string | null; alertas: AlertaC[] }>("/central/perguntar", { params: { q } }),
  });
}
