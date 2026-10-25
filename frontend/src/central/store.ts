import { create } from "zustand";

/** Estado da tela da central (o que não vai para o endereço): seleção, camadas, linha do tempo. */

export type Selecao =
  | { tipo: "equipamento"; id: number; alertaId?: number }
  | { tipo: "agente"; id: number }
  | { tipo: "alerta"; id: number };

export type Camada = "fixos" | "moveis" | "agentes" | "regioes" | "calor" | "cobertura" | "ocorrencias";

export interface Voo { lon?: number; lat?: number; zoom?: number; bbox?: [number, number, number, number]; t: number }

interface EstadoTela {
  selecao: Selecao | null;
  selecionar: (s: Selecao | null) => void;
  camadas: Record<Camada, boolean>;
  alternarCamada: (c: Camada) => void;
  aba: "alertas" | "manutencao";
  setAba: (a: "alertas" | "manutencao") => void;
  minutos: number; // linha do tempo: 0 = agora
  setMinutos: (m: number) => void;
  linhaAberta: boolean;
  setLinhaAberta: (v: boolean) => void;
  desenhando: boolean;
  setDesenhando: (v: boolean) => void;
  /** Registro de ocorrência: true espera o clique no mapa; o ponto escolhido fica em `pontoOcorrencia`. */
  registrando: boolean;
  setRegistrando: (v: boolean) => void;
  pontoOcorrencia: [number, number] | null;
  setPontoOcorrencia: (p: [number, number] | null) => void;
  som: boolean;
  setSom: (v: boolean) => void;
  voo: Voo | null;
  voar: (v: Omit<Voo, "t">) => void;
  conexao: "conectando" | "ao_vivo" | "caiu";
  setConexao: (c: "conectando" | "ao_vivo" | "caiu") => void;
  ultimoEvento: number;
  marcarEvento: () => void;
}

function lerSom() {
  try { return localStorage.getItem("atalaia.som") !== "0"; } catch { return true; }
}

export const useTela = create<EstadoTela>((set) => ({
  selecao: null,
  selecionar: (selecao) => set({ selecao }),
  camadas: { fixos: true, moveis: true, agentes: true, regioes: true, calor: false, cobertura: false, ocorrencias: true },
  alternarCamada: (c) => set((s) => ({ camadas: { ...s.camadas, [c]: !s.camadas[c] } })),
  aba: "alertas",
  setAba: (aba) => set({ aba }),
  minutos: 0,
  setMinutos: (minutos) => set({ minutos }),
  linhaAberta: false,
  setLinhaAberta: (linhaAberta) => set(linhaAberta ? { linhaAberta } : { linhaAberta, minutos: 0 }),
  desenhando: false,
  setDesenhando: (desenhando) => set({ desenhando }),
  registrando: false,
  setRegistrando: (registrando) => set(registrando ? { registrando, desenhando: false, pontoOcorrencia: null } : { registrando, pontoOcorrencia: null }),
  pontoOcorrencia: null,
  setPontoOcorrencia: (pontoOcorrencia) => set({ pontoOcorrencia }),
  som: lerSom(),
  setSom: (som) => {
    try { localStorage.setItem("atalaia.som", som ? "1" : "0"); } catch { /* sem storage */ }
    set({ som });
  },
  voo: null,
  voar: (v) => set({ voo: { ...v, t: Date.now() } }),
  conexao: "conectando",
  setConexao: (conexao) => set({ conexao }),
  ultimoEvento: 0,
  marcarEvento: () => set({ ultimoEvento: Date.now() }),
}));
