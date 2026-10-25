import { createContext, useContext, type ReactNode } from "react";
import type { Indicadores as Ind, ValoresIndicadores } from "./tipos";
import { COR_NIVEL, fmt } from "./visual";

/** Variação na última hora, com a cor dizendo se piorou ou melhorou. */
const NoPassado = createContext(false);

function Var({ v, unidade = "", melhorSobe = true, casas = 0 }: { v: unknown; unidade?: string; melhorSobe?: boolean; casas?: number }) {
  if (useContext(NoPassado)) return <span className="text-cinza">naquele momento</span>;
  if (typeof v !== "number") return <span className="text-cinza">sem histórico</span>;
  if (Math.abs(v) < 10 ** -casas / 2) return <span className="text-cinza">estável na hora</span>;
  const bom = (v > 0) === melhorSobe;
  return (
    <span style={{ color: bom ? "var(--color-ok)" : "var(--color-critico)" }}>
      {v > 0 ? "+" : "−"}{fmt(Math.abs(v), casas)}{unidade} na hora
    </span>
  );
}

function Bloco({ rotulo, valor, sub, destaque, titulo }: { rotulo: string; valor: ReactNode; sub?: ReactNode; destaque?: string; titulo?: string }) {
  return (
    <div className="min-w-0 border-l border-linha px-3 py-2 first:border-l-0" title={titulo}>
      <div className="truncate text-[11px] font-semibold uppercase tracking-[0.05em] text-cinza">{rotulo}</div>
      <div className="cond num truncate text-[30px] font-bold leading-[1.05]" style={destaque ? { color: destaque } : undefined}>{valor}</div>
      <div className="num truncate text-[11px]">{sub}</div>
    </div>
  );
}

function tempo(s: number | null) {
  if (s == null) return "—";
  if (s < 90) return `${Math.round(s)} s`;
  return `${fmt(s / 60, 1)} min`;
}

export default function Indicadores({ dados, passado, grande }: { dados?: Ind; passado?: Partial<ValoresIndicadores> | null; grande?: boolean }) {
  const v: Partial<ValoresIndicadores> = passado ?? dados?.valores ?? {};
  const va = passado ? {} : dados?.variacao ?? {};
  const al = v.alertas;
  const vAl = va.alertas as Record<string, number> | undefined;
  const disp = v.disponibilidade;
  return (
    <NoPassado.Provider value={!!passado}>
    <div className={`grid grid-cols-3 border-b border-linha bg-papel sm:grid-cols-5 lg:grid-cols-9 ${grande ? "[&_.cond]:text-[44px]" : ""}`}>
      <Bloco rotulo="Equipamentos" valor={fmt(v.total)} sub={<Var v={va.total} />} titulo="Todos os cadastrados, em qualquer situação" />
      <Bloco rotulo="Operacionais" valor={fmt(v.operacionais)} sub={<Var v={va.operacionais} />} />
      <Bloco rotulo="Indisponíveis" valor={fmt(v.indisponiveis)} sub={<Var v={va.indisponiveis} melhorSobe={false} />}
        titulo="Mau funcionamento + em manutenção + furtado" />
      <Bloco rotulo="Disponibilidade" valor={disp == null ? "—" : `${fmt(disp, 1)}%`}
        destaque={disp != null && disp < 90 ? "var(--color-atencao)" : undefined}
        sub={<Var v={va.disponibilidade} unidade=" p.p." casas={1} />}
        titulo="Regra única da Parte 1: operacionais / (operacionais + mau funcionamento + em manutenção + furtados)" />
      <Bloco rotulo="Agentes ativos" valor={fmt(v.agentes_ativos)} sub={<Var v={va.agentes_ativos} />}
        titulo="Em atividade, com posição atualizada nos últimos 10 min" />
      <Bloco
        rotulo="Alertas abertos"
        valor={
          <span className="flex items-baseline gap-2">
            <span style={{ color: al?.critica ? COR_NIVEL.critica : undefined }} title="Críticos">{fmt(al?.critica)}</span>
            <span className="text-[18px]" style={{ color: COR_NIVEL.alta }} title="Altos">{fmt(al?.alta)}</span>
            <span className="text-[18px] text-cinza" title="Médios">{fmt(al?.media)}</span>
          </span>
        }
        sub={vAl ? <Var v={vAl.critica} melhorSobe={false} /> : <span className="text-cinza">crítica · alta · média</span>}
        titulo="Contagem por nível (crítica, alta, média)"
      />
      <Bloco rotulo="Sem sinal" valor={fmt(v.sem_sinal)} sub={<Var v={va.sem_sinal} melhorSobe={false} />}
        destaque={v.sem_sinal ? COR_NIVEL.alta : undefined} titulo="Equipamentos em falha silenciosa" />
      <Bloco rotulo="Manut. vencidas" valor={fmt(v.manutencoes_vencidas)} sub={<Var v={va.manutencoes_vencidas} melhorSobe={false} />}
        titulo="Planos com data passada e sem execução" />
      <Bloco rotulo="Até reconhecer" valor={tempo(v.tempo_reconhecer_s ?? null)}
        sub={typeof va.tempo_reconhecer_s === "number"
          ? <Var v={va.tempo_reconhecer_s} unidade=" s" melhorSobe={false} />
          : <span className="text-cinza">média na última hora</span>}
        titulo="Média, na última hora, do tempo entre abrir e reconhecer um alerta" />
    </div>
    </NoPassado.Provider>
  );
}
