export type Situacao =
  | "nao_instalado" | "operacional" | "mau_funcionamento" | "em_manutencao" | "desativado" | "furtado";
export type StatusManutencao = "em_dia" | "proxima" | "vencida";
export type Mobilidade = "fixo" | "movel";

export interface Pagina<T> { itens: T[]; total: number; pagina: number; por_pagina: number }

export interface Orgao { id: number; nome: string; sigla: string }
export interface Cidade { id: number; nome: string; uf: string; tem_lista_bairros: boolean; lon: number | null; lat: number | null }
export interface Bairro { id: number; cidade_id: number; nome: string; regiao: string | null }
export interface Base { id: number; nome: string; orgao_id: number; cidade_id: number; endereco: string | null }

export interface JSONSchema {
  type?: string; title?: string; description?: string; enum?: unknown[]; items?: JSONSchema;
  properties?: Record<string, JSONSchema>; required?: string[]; minimum?: number; maximum?: number;
  pattern?: string; format?: string; uniqueItems?: boolean; minItems?: number;
  "x-ordem"?: string[];
}

export interface Tipo {
  id: number; nome: string; prefixo: string; categoria: string; mobilidade: Mobilidade; icone: string;
  schema_atributos: JSONSchema; intervalo_sinal_esperado_min: number; periodicidade_padrao_dias: number | null;
  total_equipamentos: number;
}

export interface Motivo { chave: string; texto: string; pontos: number }

export interface EquipamentoResumo {
  id: number; codigo_interno: string;
  tipo: { id: number; nome: string; prefixo: string; icone: string; mobilidade: Mobilidade };
  marca: string; modelo: string; numero_serie: string; orgao: string; situacao: Situacao;
  score_saude: number; status_manutencao: StatusManutencao; bairro: string | null; regiao: string | null;
  cidade: string | null; ultimo_sinal_em: string | null; sem_sinal: boolean; lon: number | null; lat: number | null;
}

export interface Aviso { codigo: string; mensagem: string; bairro_id?: number }

export interface Equipamento extends EquipamentoResumo {
  orgao_id: number; dispositivo_iot_id: string | null; data_instalacao: string | null;
  atributos: Record<string, unknown>; score_motivos: Motivo[];
  localizacao: {
    cidade_id: number; cidade: string; uf: string; rua: string; cep: string | null; bairro_id: number | null;
    bairro: string | null; referencia: string | null; regiao: string | null; lon: number | null; lat: number | null;
  } | null;
  transicoes_permitidas: Situacao[]; criado_em: string; atualizado_em: string; avisos: Aviso[];
}

export interface Historico {
  id: number; situacao_anterior: Situacao | null; situacao_nova: Situacao; motivo: string; usuario: string; em: string;
}
export interface Plano {
  id: number; tipo: "imediata" | "agendada" | "periodica"; proxima_data: string | null;
  periodicidade_dias: number | null; descricao: string | null; ativo: boolean;
}
export interface Registro {
  id: number; plano_id: number | null; executada_em: string; tecnico: string; descricao: string | null; resultado: string;
}
export interface Ordem {
  id: number; motivo: string; prioridade: string; status: "aberta" | "fechada"; aberta_em: string; fechada_em: string | null;
}
export interface Alerta {
  id: number; equipamento_id: number; codigo_interno: string; tipo: "furto" | "falha_silenciosa" | "manutencao_vencida";
  severidade: "critico" | "atencao"; mensagem: string; criado_em: string; resolvido_em: string | null;
}
export interface Agente {
  id: number; nome: string; matricula: string; categoria: "agente_transito" | "guarda_municipal" | "policial_militar";
  orgao_id: number; orgao: string; equipe: string | null; situacao: "em_atividade" | "em_pausa" | "fora_de_escala";
  contato: string | null; veiculo: { id: number; codigo_interno: string; tipo: string; placa: string | null } | null;
  base_id: number | null; base: string | null;
}

export interface ErroApi { codigo: string; mensagem: string; detalhes?: { campo?: string | null; mensagem: string }[] }

/** Campos do schema na ordem em que foram definidos. */
export function camposOrdenados(schema: JSONSchema): [string, JSONSchema][] {
  const props = schema.properties ?? {};
  const ordem = (schema["x-ordem"] ?? []).filter((k) => k in props);
  const resto = Object.keys(props).filter((k) => !ordem.includes(k));
  return [...ordem, ...resto].map((k) => [k, props[k]]);
}
