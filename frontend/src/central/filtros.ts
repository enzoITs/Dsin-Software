import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/** Filtros da central. Ficam no endereço da página para salvar ou compartilhar uma visão
 * ("câmeras sem sinal na região Norte"). Os mesmos parâmetros vão para todos os endpoints. */
export interface FiltrosCentral {
  tipo_id: number[];
  situacao: string[];
  regiao: string[];
  bairro_id: number[];
  orgao_id: number[];
  nivel: string[];
  sem_sinal: boolean;
  manutencao: string[];
  score_max: number | null;
  area: [number, number][];
}

const LISTAS = ["tipo_id", "situacao", "regiao", "bairro_id", "orgao_id", "nivel", "manutencao"] as const;
const NUMERICAS = new Set(["tipo_id", "bairro_id", "orgao_id"]);

export function lerFiltros(sp: URLSearchParams): FiltrosCentral {
  const f: Record<string, unknown> = {};
  for (const k of LISTAS) f[k] = sp.getAll(k).map((v) => (NUMERICAS.has(k) ? Number(v) : v));
  f.sem_sinal = sp.get("sem_sinal") === "1";
  f.score_max = sp.get("score_max") ? Number(sp.get("score_max")) : null;
  const area = sp.get("area");
  f.area = area
    ? area.split(",").map((p) => p.trim().split(" ").map(Number) as [number, number]).filter((p) => p.length === 2 && p.every(Number.isFinite))
    : [];
  return f as unknown as FiltrosCentral;
}

/** Parâmetros para a API (mesmos nomes da Parte 1, mais nivel, manutencao e area). */
export function paramsApi(f: FiltrosCentral): Record<string, string | number | boolean | (string | number)[] | undefined> {
  return {
    tipo_id: f.tipo_id, situacao: f.situacao, regiao: f.regiao, bairro_id: f.bairro_id, orgao_id: f.orgao_id,
    nivel: f.nivel, manutencao: f.manutencao, sem_sinal: f.sem_sinal || undefined,
    score_max: f.score_max ?? undefined,
    area: f.area.length >= 3 ? f.area.map(([x, y]) => `${x.toFixed(6)} ${y.toFixed(6)}`).join(",") : undefined,
  };
}

export function contarFiltros(f: FiltrosCentral) {
  return LISTAS.reduce((n, k) => n + (f[k].length ? 1 : 0), 0) + (f.sem_sinal ? 1 : 0) + (f.score_max != null ? 1 : 0) + (f.area.length ? 1 : 0);
}

export function useFiltrosCentral() {
  const [sp, setSp] = useSearchParams();
  const filtros = useMemo(() => lerFiltros(sp), [sp]);
  const chave = useMemo(() => {
    const c = new URLSearchParams(sp);
    c.delete("sala");
    c.sort();
    return c.toString();
  }, [sp]);

  const definir = useCallback((mud: Partial<Record<keyof FiltrosCentral, unknown>>) => {
    setSp((atual) => {
      const novo = new URLSearchParams(atual);
      for (const [k, v] of Object.entries(mud)) {
        novo.delete(k);
        if (v == null || v === false || (Array.isArray(v) && !v.length)) continue;
        if (k === "area") {
          novo.set("area", (v as [number, number][]).map(([x, y]) => `${x.toFixed(5)} ${y.toFixed(5)}`).join(","));
        } else if (Array.isArray(v)) v.forEach((x) => novo.append(k, String(x)));
        else if (v === true) novo.set(k, "1");
        else novo.set(k, String(v));
      }
      return novo;
    }, { replace: true });
  }, [setSp]);

  const alternar = useCallback((k: (typeof LISTAS)[number], valor: string | number) => {
    const atual = filtros[k] as (string | number)[];
    definir({ [k]: atual.includes(valor) ? atual.filter((x) => x !== valor) : [...atual, valor] });
  }, [filtros, definir]);

  const limpar = useCallback(() => {
    setSp((atual) => {
      const novo = new URLSearchParams();
      if (atual.get("sala")) novo.set("sala", atual.get("sala")!);
      return novo;
    }, { replace: true });
  }, [setSp]);

  return { filtros, chave, params: useMemo(() => paramsApi(filtros), [filtros]), definir, alternar, limpar, total: contarFiltros(filtros) };
}
