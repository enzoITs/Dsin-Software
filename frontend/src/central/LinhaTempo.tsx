import { Area, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { X } from "lucide-react";
import { useSerieHora } from "./api";
import { useTela } from "./store";
import type { LinhaDoTempo } from "./tipos";
import { COR_NIVEL } from "./visual";
import { COR } from "../lib/cores";

const hora = (iso: string) => new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

/** Controle deslizante que volta o mapa, os indicadores e as regiões até uma hora atrás. */
export default function LinhaTempo({ dados, carregando }: { dados?: LinhaDoTempo; carregando: boolean }) {
  const minutos = useTela((s) => s.minutos);
  const setMinutos = useTela((s) => s.setMinutos);
  const fechar = () => useTela.getState().setLinhaAberta(false);
  const serie = useSerieHora().data ?? [];
  const alvo = new Date(Date.now() - minutos * 60_000).toISOString();
  const pontos = serie.map((s) => ({ ...s, t: new Date(s.em).getTime() }));
  return (
    <div className="absolute inset-x-2 bottom-2 z-20 border border-tinta bg-papel/95 px-3 py-2 shadow-[0_6px_24px_rgba(0,0,0,0.15)]">
      <div className="flex items-center gap-3">
        <span className="text-[11px] font-bold uppercase tracking-[0.06em]">Linha do tempo</span>
        <span className="num text-[13px] font-semibold">
          {minutos === 0 ? "Agora (ao vivo)" : `${hora(alvo)} · há ${minutos} min`}
          {carregando && minutos > 0 ? " · carregando…" : ""}
        </span>
        {minutos > 0 && dados && (
          <span className="text-[12px] text-cinza">
            {dados.alertas.length} alerta(s) abertos naquele momento · {dados.equipamentos.length} equipamento(s) mudaram de situação desde então
          </span>
        )}
        <button className="ml-auto p-1 hover:bg-neutro" onClick={fechar} aria-label="Fechar linha do tempo"><X size={16} /></button>
      </div>
      <div className="h-[64px]">
        {pontos.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={pontos} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
              <XAxis dataKey="t" type="number" domain={[Date.now() - 3_600_000, Date.now()]} hide />
              <YAxis yAxisId="a" hide domain={[0, "dataMax + 2"]} />
              <YAxis yAxisId="d" hide domain={["dataMin - 1", "dataMax + 1"]} />
              <Tooltip
                labelFormatter={(t) => hora(new Date(Number(t)).toISOString())}
                formatter={(v: number, n: string) => [n === "disponibilidade" ? `${v?.toFixed(1)}%` : v, n === "critica" ? "críticos" : n === "alta" ? "altos" : "disponibilidade"]}
              />
              <Area yAxisId="a" dataKey="alta" stroke={COR_NIVEL.alta} fill={COR_NIVEL.alta} fillOpacity={0.15} isAnimationActive={false} />
              <Area yAxisId="a" dataKey="critica" stroke={COR_NIVEL.critica} fill={COR_NIVEL.critica} fillOpacity={0.25} isAnimationActive={false} />
              <Line yAxisId="d" dataKey="disponibilidade" stroke={COR.texto} dot={false} strokeWidth={1.5} isAnimationActive={false} />
              <ReferenceLine yAxisId="a" x={Date.now() - minutos * 60_000} stroke={COR.acento} strokeWidth={2} />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <p className="pt-4 text-[12px] text-cinza">O gráfico aparece depois de alguns minutos de central no ar (um instantâneo por minuto).</p>
        )}
      </div>
      <input
        type="range" min={0} max={60} step={1} value={60 - minutos} onChange={(e) => setMinutos(60 - Number(e.target.value))}
        className="w-full accent-[var(--color-acento)]" aria-label="Minutos atrás"
      />
      <div className="flex justify-between text-[11px] text-cinza"><span>1 hora atrás</span><span>30 min</span><span>agora</span></div>
      {minutos > 0 && <p className="text-[11px] text-cinza">No passado, o mapa mostra a situação e os alertas daquele momento; os agentes aparecem só ao vivo.</p>}
    </div>
  );
}
