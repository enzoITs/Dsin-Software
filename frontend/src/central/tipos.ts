import type { Situacao } from "../api/tipos";

export type Nivel = "critica" | "alta" | "media" | "baixa";
export type EstadoAlerta = "aberto" | "reconhecido" | "em_atendimento" | "resolvido";
export type EstadoRegiao = "normal" | "atencao" | "critica";

export interface AlertaC {
  id: number; tipo: string; regra: string; rotulo_regra: string; nivel: Nivel; nivel_inicial: Nivel; motivos_nivel: string[];
  estado: EstadoAlerta; mensagem: string; contador: number; criado_em: string; ultima_ocorrencia_em: string | null;
  regiao: string | null; lon: number | null; lat: number | null; equipamento_id: number | null; codigo_interno: string | null;
  tipo_equipamento: string | null; orgao: string | null; dispositivo_iot_id: string | null; agente_alvo_id: number | null;
  agente: { id: number; nome: string; orgao: string } | null; ordem_servico_id: number | null; incidente_id: number | null;
  membros: number; equipamentos: string[]; silenciado_ate: string | null; silenciado_motivo: string | null;
  reconhecido_em: string | null; reconhecido_por: string | null; resolvido_em: string | null; resolvido_por: string | null;
  resolucao: string | null; severidade: string; simulado: boolean;
  preditivo?: AlertaPreditivo | null;
  lista_membros?: AlertaC[];
}

/** Alerta preventivo (Parte 3): a previsão por trás, para quando está previsto e a antecedência. */
export interface AlertaPreditivo {
  previsao_id: number; modulo: string; previsto_para: string; ate: string; antecedencia_min: number;
  nivel?: string; indice?: number; probabilidade?: number; falta?: number; demanda?: number; horas?: number;
}

export interface RiscoPrevisto {
  origem: string | null; horas: number;
  regioes: { previsao_id: number; regiao_id: number; regiao: string; indice: number; nivel: string; nivel_nome: string;
             pico_em: string; motivo: string | null; geometria: GeoJSON.Geometry }[];
}

export interface ListaAlertas { itens: AlertaC[]; total: number; pagina: number; por_pagina: number; por_nivel: Record<string, number> }

export interface ValoresIndicadores {
  total: number; operacionais: number; indisponiveis: number; disponibilidade: number | null; agentes_ativos: number;
  alertas: Record<"critica" | "alta" | "media", number>; sem_sinal: number; manutencoes_vencidas: number;
  tempo_reconhecer_s: number | null;
}
export interface Indicadores {
  em: string; valores: ValoresIndicadores;
  variacao: Partial<Record<keyof ValoresIndicadores, number | null | Record<string, number>>>;
}

export interface RegiaoSaude {
  regiao: string; nota: number; estado: EstadoRegiao; motivo: string; fatores: { fator: string; texto: string; pontos: number }[];
  alertas: Record<"critica" | "alta" | "media", number>; disponibilidade: number | null; equipamentos: number;
  agentes_ativos: number; agentes_por_orgao: Record<string, number>; pico: boolean;
}

export interface ItemFila {
  categoria: "imediata" | "vencida" | "proxima"; equipamento_id: number; codigo_interno: string; tipo: string;
  regiao: string | null; situacao: Situacao; data: string | null; dias: number | null; motivo: string;
  ordem_servico: { id: number; prioridade: string | null } | null; lon: number | null; lat: number | null;
}
export interface Fila { totais: Record<string, number>; total: number; itens: ItemFila[] }

export interface AgenteProximo {
  id: number; nome: string; equipe: string | null; orgao: string; regiao: string | null; posicao_em: string | null;
  distancia_m: number; em_atendimento: boolean;
}

/** Propriedades compactas de cada ponto do mapa (ver services/central.py). */
export interface PropsEquip {
  i: number; c: string; p: string; f: "c" | "q" | "t"; s: Situacao; n: number; g: number; v: 0 | 1; m: 0 | 1; o: string; r: string | null;
}
export interface PropsAgente { i: number; nome: string; eq: string | null; o: string; r: string | null; pe: string | null; at: number | null }

export type Feicao<P> = { type: "Feature"; geometry: { type: "Point"; coordinates: [number, number] }; properties: P };
export interface EstadoCentral {
  em: string;
  equipamentos: { type: "FeatureCollection"; features: Feicao<PropsEquip>[] };
  agentes: { type: "FeatureCollection"; features: Feicao<PropsAgente>[] };
}

export interface LinhaDoTempo {
  em: string;
  indicadores: Partial<ValoresIndicadores>;
  regioes: { regiao: string; nota: number; estado: EstadoRegiao; motivo: string }[];
  alertas: { id: number; regra: string; nivel: Nivel; mensagem: string; regiao: string | null; equipamento_id: number | null; criado_em: string; lon: number | null; lat: number | null }[];
  equipamentos: { i: number; s: Situacao }[];
  criados_depois: number[];
  serie: { em: string; disponibilidade: number | null; critica: number; alta: number }[];
}

export type Evento =
  | { tipo: "ola"; canal: string }
  | { tipo: "pulso" }
  | { tipo: "alerta"; acao: "novo" | "atualizado" | "resolvido" | "tocar"; alerta: AlertaC }
  | { tipo: "equipamentos"; feicoes: Feicao<PropsEquip>[]; removidos: number[] }
  | { tipo: "posicoes"; equipamentos?: [number, number, number][]; agentes?: [number, number, number][] }
  | { tipo: "agentes"; ids: number[] }
  | { tipo: "recarregar"; motivo: string }
  | { tipo: "ocorrencia"; acao: "nova"; ocorrencia: Ocorrencia };

/** Ocorrência da cidade (Parte 3): registrada na central, derivada de alerta ou simulada. */
export interface Ocorrencia {
  id: number; categoria: string; categoria_nome: string; gravidade: number; inicio_em: string; fim_em: string | null;
  lon: number | null; lat: number | null; regiao: string | null; bairro: string | null;
  origem: "simulada" | "central" | "equipamento" | "externa"; equipamento_id: number | null; alerta_id: number | null;
  agentes_presentes_regiao: number | null; descricao: string | null; registrado_por: string | null;
}
export interface CategoriaOcorrencia { codigo: string; nome: string; descricao: string | null; gravidade_padrao: number }
