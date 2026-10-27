/** Contrato de previsão da Parte 3 (o que a API devolve e o Cartão de Previsão exibe). */

export type Modulo = "P1" | "P2" | "P3" | "P4";

export interface Fator { descricao: string; efeito: number; grupo?: string }

export interface Acao { texto: string; tipo: string; parametros: Record<string, unknown> }

export interface Selo {
  texto: string; confianca: "baixa" | "moderada" | "alta"; ganho_pct: number | null; avaliado_em?: string; versao?: string;
  metrica?: string; modelo?: number | null; baseline?: number | null; precisao_50?: number | null; precisao_50_baseline?: number | null;
}

export interface Decisao {
  id: number; estado: "pendente" | "aceita" | "ajustada" | "rejeitada" | "expirada"; decidido_por: string | null;
  decidido_em: string | null; motivo: string | null; resultado: { execucao?: Record<string, unknown> } | null;
}

export interface Cartao {
  id: string; previsao_id: number; modulo: Modulo; modulo_nome: string; o_que_preve: string;
  alvo: { tipo: string; id: number; nome: string; regiao?: string | null; tipo_equipamento?: string } | null;
  horizonte: { inicio: string; fim: string }; valor: number; unidade: string;
  faixa: { inferior: number | null; superior: number | null }; nivel: string | null;
  dados_considerados: string[]; fatores: Fator[]; como_ajuda: string | null; acao_recomendada: Acao | null;
  qualidade_do_modelo: { selo: Selo } & Record<string, unknown>;
  confianca: { nivel: "baixa" | "moderada" | "alta"; aviso: string | null };
  modelo: { nome: string; versao: string } | null; gerado_em: string; valor_real: number | null; dados_sinteticos: boolean;
  extra: Record<string, unknown>; recomendacao: Decisao | null;
}

export interface RegiaoHora {
  regiao_id: number; regiao: string; indice: number; nivel: string; motivo: string; previsao_id: number;
  ocorrencias?: number; previsao_p2_id?: number | null;
}
export interface Hora { em: string; local: string; rotulo: string; regioes: RegiaoHora[] }
export interface Periodo { inicio: string; fim: string; periodo: string; rotulo: string; nome: string; regioes: RegiaoHora[] }

export interface Recomendacao {
  id: number; previsao_id: number | null; tipo: string; texto: string; parametros: Record<string, unknown>;
  impacto_estimado: Record<string, number | null>; estado: Decisao["estado"]; decidido_por: string | null;
  decidido_em: string | null; motivo: string | null; resultado: Record<string, unknown>; criado_em: string;
}

export interface ClimaDia { dia: string; chuva_mm: number; temp_max: number; temp_min: number; tempestade: boolean; editado: boolean; horas_chuva: number[] }
export interface EventoCtx { id: number; nome: string; tipo: string; local_nome: string | null; inicio_em: string; fim_em: string; publico_estimado: number; simulado: boolean }

export interface Amanha {
  origem: string; inicio: string; fim: string; horas: Hora[]; periodos: Periodo[]; selo: Selo; recomendacoes: Recomendacao[];
  contexto: { feriados: { data: string; nome: string | null; vespera: boolean }[]; eventos: EventoCtx[]; clima: ClimaDia[] };
}

export interface PontoSerie {
  em: string; local: string; previsto: number; inferior: number; superior: number; normal: number; indice: number | null;
  previsao_id: number; real: number | null;
}
export interface DetalheRegiao { regiao_id: number; regiao: string; origem: string; serie: PontoSerie[]; cartoes: Cartao[] }

export interface ItemRisco {
  previsao_id: number; equipamento_id: number; codigo: string; tipo: string; regiao: string | null; marca: string; modelo: string;
  situacao: string; probabilidade: number; faixa: [number, number]; nivel: string; fatores: Fator[]; acao: Acao | null;
  decisao: string | null; os_aberta: boolean;
}
export interface Ranking { gerado_para: string; janela_dias: 7 | 30; totais_por_nivel: Record<string, number>; selo: Selo; itens: ItemRisco[] }

export interface RegiaoPlano {
  regiao: string; demanda: number; capacidade_antes: number; capacidade_depois: number; equipes_antes: number; equipes_depois: number;
  falta_antes: number; falta_depois: number; indice: number; nivel: string; nivel_nome: string; motivo: string;
  previstas: number; razao_normal: number | null; regiao_id: number;
}
export interface Movimento { equipe: string; id: string; orgao: string; de: string; para: string; agentes: number }
export interface PeriodoPlano {
  inicio: string; fim: string; periodo: string; rotulo: string; metodo: string; status: string; avisos: string[];
  nao_coberto_antes: number; nao_coberto_depois: number; reducao_pct: number | null; regioes: RegiaoPlano[];
  movimentos: Movimento[]; recomendacoes: string[];
}
export interface Plano {
  origem: string; periodos: PeriodoPlano[]; nao_coberto_antes: number; nao_coberto_depois: number; reducao_pct: number | null;
  unidade: string; recomendacoes: Recomendacao[]; gravado?: { previsoes: number; recomendacoes: number } | null;
}

/** Confiança dos modelos (Q1) */
export interface EstadoTreino {
  situacao: "nunca" | "rodando" | "pronto" | "erro" | "interrompido"; etapa?: string; mensagem?: string | null;
  inicio?: string; atualizado_em?: string; segundos?: number; tem_modelo: boolean; rodando_aqui: boolean;
}

export interface ModeloAvaliado {
  modulo: string; nome: string; titulo: string; o_que_preve: string; metodo: string; versao: string; treinado_em: string;
  treino_inicio: string | null; treino_fim: string | null; selo: Selo;
  metricas: Record<string, number | Record<string, number>>; baseline: Record<string, number | Record<string, number>>;
  logistica: { auc: number; brier: number; precisao_50: number } | null;
  calibracao: { n: number; prevista: number; observada: number }[] | null;
  calibracao_baseline: { n: number; prevista: number; observada: number }[] | null;
  importancia: { grupo: string; nome: string; peso: number }[];
  backtest: ({ data_corte: string; modelo: number; baseline: number } & Record<string, number | string | null>)[];
}

export interface Modelos {
  modelos: ModeloAvaliado[]; derivados: { modulo: string; titulo: string; texto: string }[]; avaliacao: string;
  treino: EstadoTreino; dados_sinteticos: boolean;
}

export interface MetricasConferidas {
  n: number; mae: number; mae_baseline: number; ganho_pct: number | null; cobertura_intervalo: number; real_medio: number;
}

export interface Acertometro {
  gerado_em: string; dias: number;
  P2: { conferidas: number; geral?: MetricasConferidas; por_antecedencia?: ({ faixa: string } & MetricasConferidas)[];
        por_dia?: ({ dia: string } & MetricasConferidas)[]; por_regiao?: ({ regiao: string } & MetricasConferidas)[];
        serie_48h?: { em: string; previsto: number; real: number; baseline: number }[] };
  P1: { top: number; lotes: { inicio: string; fim: string; encerrado: boolean; decorrido_pct: number; equipamentos: number;
        apontados: number; falharam_apontados: number; esperado_apontados: number; taxa_apontados: number; taxa_geral: number;
        falharam_total: number }[] };
}

/** Cenários "e se" (C1) */
export interface CenarioParams {
  eventos?: { nome?: string; bairro_id?: number; publico: number; inicio?: string; fim?: string; raio_m?: number }[];
  cancelar_eventos?: number[];
  clima?: { inicio?: string; fim?: string; chuva_mm?: number; temperatura_c?: number; tempestade?: boolean }[];
  equipes?: { regiao: string; delta: number; inicio?: string; fim?: string }[];
  equipamentos_fora?: { codigos?: string[]; regiao?: string; prefixo?: string; quantidade?: number } | null;
  manutencoes?: { codigos?: string[]; regiao?: string; quantidade?: number } | null;
}

export interface RegiaoCenario {
  regiao: string; ocorrencias_base: number; ocorrencias_cenario: number; diferenca_pct: number | null;
  indice_medio_base: number; indice_medio_cenario: number; indice_max_base: number; indice_max_cenario: number;
  nivel_max_base: string; nivel_max_cenario: string; periodos_alto_base: number; periodos_alto_cenario: number;
}

export interface ResultadoCenario {
  origem: string; parametros: CenarioParams; frases: string[]; regioes: RegiaoCenario[]; segundos?: number;
  aplicado: Record<string, unknown>;
  periodos: { inicio: string; fim: string; rotulo: string;
              regioes: { regiao: string; indice_base: number; nivel_base: string; indice_cenario: number | null; nivel_cenario: string | null }[] }[];
  equipes: { base: { nao_coberto_escala: number; nao_coberto_otimizado: number; recomendacoes: string[] };
             cenario: { nao_coberto_escala: number; nao_coberto_otimizado: number; recomendacoes: string[] } };
}

export interface CenarioSalvo {
  id: number; nome: string; descricao: string | null; criado_por: string | null; criado_em: string; frases: string[];
  origem: string | null; parametros?: CenarioParams; resultado?: ResultadoCenario;
}

export interface OpcoesCenario {
  regioes: string[]; bairros: { id: number; nome: string; regiao: string }[];
  eventos: { id: number; nome: string; local_nome: string | null; inicio_em: string; fim_em: string; publico_estimado: number }[];
  tipos: { prefixo: string; nome: string }[];
}

/** Retorno das recomendações (C5) */
export interface Retorno {
  dias: number; total: number; decididas: number; taxa_aceitacao: number | null; por_estado: Record<string, number>;
  por_tipo: { tipo: string; rotulo: string; total: number; decididas: number; aceitas: number; rejeitadas: number; expiradas: number; pendentes: number }[];
  motivos_rejeicao: { motivo: string; vezes: number }[];
  comparacao: {
    os: { aceitas: { conferidas: number; falharam?: number; taxa_falha: number | null }; rejeitadas: { conferidas: number; falharam?: number; taxa_falha: number | null } };
    reforco: { aceitas: { conferidas: number; real_sobre_previsto: number | null }; rejeitadas: { conferidas: number; real_sobre_previsto: number | null } };
    aviso: string;
  };
  decisoes: { id: number; tipo: string; rotulo_tipo: string; texto: string; estado: string; decidido_por: string | null;
              decidido_em: string | null; motivo: string | null; previsao_id: number | null;
              execucao: Record<string, unknown> | null; retorno: { texto: string; [k: string]: unknown } | null }[];
}

/** Padrões descobertos (Q2) */
export interface PadraoDescoberto {
  padrao: number; titulo: string; modulo: string; metodo: string; descoberto: string; plantado: string;
  efeito: number | null; veredito: "encontrado" | "fraco" | "nao_encontrado" | "sem_dados"; detalhe?: string;
}
export interface PadroesDescobertos {
  gerado_em: string; padroes: PadraoDescoberto[]; resumo: Record<string, number>; aviso: string;
  curvas: Record<string, Record<string, number>[]>;
}
