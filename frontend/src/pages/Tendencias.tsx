import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ShieldCheck } from "lucide-react";
import { Carregando, Erro } from "../components/ui";
import AvisoTreino from "../preditivo/AvisoTreino";
import CartaoPrevisao, { SeloNivel } from "../preditivo/CartaoPrevisao";
import GavetaCartao from "../preditivo/GavetaCartao";
import { useDisponibilidade, useManutencao } from "../preditivo/api";
import { COR_NIVEL, dia, num, pct } from "../preditivo/formato";
import type { ItemDisponibilidade, Manutencao } from "../preditivo/tipos";
import { COR } from "../lib/cores";

const curto = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

function Grafico({ x, meta }: { x: ItemDisponibilidade; meta: number }) {
  type Linha = { x: string; observado?: number; previsto?: number; faixa?: (number | undefined)[]; seguindo?: number };
  const dados: Linha[] = [
    ...x.historico.map((p) => ({ x: curto(p.dia), observado: p.valor })),
    ...x.previsto.map((p) => ({ x: curto(p.dia), previsto: p.valor, faixa: [p.inferior, p.superior], seguindo: p.seguindo_p1 })),
  ];
  const valores = dados.flatMap((d) => [d.observado, d.previsto, d.seguindo].filter((v): v is number => v != null));
  const min = Math.min(meta, ...valores) - 0.01;
  const max = Math.max(meta, ...valores) + 0.005;
  return (
    <div className="h-[240px]">
      <ResponsiveContainer>
        <ComposedChart data={dados} margin={{ left: -6, right: 8, top: 6 }}>
          <CartesianGrid stroke={COR.grade} vertical={false} />
          <XAxis dataKey="x" tick={{ fontSize: 10 }} interval={29} />
          <YAxis tick={{ fontSize: 10 }} domain={[min, max]} tickFormatter={(v: number) => pct(v, 1)} width={52} />
          <Tooltip formatter={(v: number | number[]) => (Array.isArray(v) ? `${pct(v[0], 1)} a ${pct(v[1], 1)}` : pct(Number(v), 1))} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Area dataKey="faixa" name="Faixa provável (90%)" stroke="none" fill={COR.acento} fillOpacity={0.12} isAnimationActive={false} />
          <Line dataKey="observado" name="Observado" stroke={COR.texto} dot={false} strokeWidth={1.5} isAnimationActive={false} />
          <Line dataKey="previsto" name="Se nada mudar" stroke={COR.acento} dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line dataKey="seguindo" name="Seguindo o P1" stroke={COR.ok} strokeDasharray="5 3" dot={false} strokeWidth={2} isAnimationActive={false} />
          <ReferenceLine y={meta} stroke={COR.critico} strokeDasharray="3 3" label={{ value: `Meta ${pct(meta)}`, fontSize: 10, position: "insideTopLeft" }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function Disponibilidade() {
  const [grupo, setGrupo] = useState<"regiao" | "tipo">("regiao");
  const [sel, setSel] = useState<string | null>(null);
  const d = useDisponibilidade(grupo);
  if (d.isLoading) return <Carregando />;
  if (d.error) return <Erro erro={d.error} />;
  if (!d.data) return null;
  const itens = d.data.itens;
  const atual = itens.find((x) => x.nome === sel) ?? itens[0];
  return (
    <div>
      <div className="mt-3 flex items-start gap-2 border border-linha bg-neutro p-2 text-[13px]">
        <ShieldCheck size={15} className="mt-[2px] shrink-0" /><span>{d.data.selo.texto}.</span>
      </div>
      <div className="mt-3 flex border border-tinta text-[13px] font-semibold w-fit">
        {(["regiao", "tipo"] as const).map((g) => (
          <button key={g} onClick={() => { setGrupo(g); setSel(null); }} className={`px-3 py-1 ${grupo === g ? "bg-acento text-papel font-semibold" : ""}`}>
            {g === "regiao" ? "Por região" : "Por tipo"}
          </button>
        ))}
      </div>
      <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <div className="space-y-1">
          {itens.map((x) => (
            <button key={x.nome} onClick={() => setSel(x.nome)}
              className={`flex w-full items-center justify-between gap-2 border px-2 py-2 text-left text-[13px] ${x.nome === atual?.nome ? "border-tinta bg-neutro" : "border-linha"}`}>
              <span>
                <b>{x.nome}</b>
                <span className="block text-[12px] text-cinza">hoje {pct(x.atual, 1)} · 30 dias {pct(x.previsto_30, 1)} · 90 dias {pct(x.previsto_90, 1)}</span>
              </span>
              <SeloNivel nivel={x.nivel_30} />
            </button>
          ))}
          <p className="pt-2 text-[12px] text-cinza">
            "Seguindo o P1": as preventivas recomendadas para os equipamentos de risco alto são feitas e evitam
            {" "}{pct(d.data.eficacia_preventiva)} das falhas esperadas deles.
          </p>
        </div>
        {atual && (
          <div>
            <h3 className="text-[15px] font-bold">{atual.nome}: disponibilidade dos equipamentos fixos</h3>
            <p className="text-[12px] text-cinza">
              {atual.em_servico.toLocaleString("pt-BR")} equipamentos em serviço. Conserto médio de {num(atual.dias_conserto, 0)} dias.
              {atual.atual < d.data.meta
                ? " Já está abaixo da meta."
                : atual.cruza_meta_em ? ` Se nada mudar, fica abaixo da meta a partir de ${dia(atual.cruza_meta_em)}.` : ""}
              {` Se nada mudar: ${pct(atual.previsto_30, 1)} em 30 dias e ${pct(atual.previsto_90, 1)} em 90.`}
              {` Seguindo o P1: ${pct(atual.seguindo_p1_30, 1)} e ${pct(atual.seguindo_p1_90, 1)}.`}
            </p>
            <Grafico x={atual} meta={d.data.meta} />
            <div className="mt-3 grid gap-3 xl:grid-cols-2">
              <CartaoPrevisao c={atual.cartao_30} compacto />
              <CartaoPrevisao c={atual.cartao_90} compacto />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function CargaManutencao() {
  const m = useManutencao();
  const [regiao, setRegiao] = useState<string | null>(null);
  const [aberto, setAberto] = useState<number | null>(null);
  if (m.isLoading) return <Carregando />;
  if (m.error) return <Erro erro={m.error} />;
  if (!m.data) return null;
  const itens: Manutencao["itens"] = m.data.itens;
  const atual = itens.find((x) => x.nome === regiao) ?? itens[0];
  return (
    <div>
      <div className="mt-3 flex items-start gap-2 border border-linha bg-neutro p-2 text-[13px]">
        <ShieldCheck size={15} className="mt-[2px] shrink-0" /><span>{m.data.selo.texto}.</span>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-tinta text-left text-[11px] uppercase tracking-[0.06em] text-cinza">
              <th className="py-2 pr-3">Região</th>
              {itens[0]?.semanas.map((s) => <th key={s.semana} className="pr-3">{s.rotulo.replace("semana de ", "")}</th>)}
            </tr>
          </thead>
          <tbody>
            {itens.map((x) => (
              <tr key={x.nome} className={`cursor-pointer border-b border-linha hover:bg-neutro ${x.nome === atual?.nome ? "bg-neutro" : ""}`}
                  onClick={() => setRegiao(x.nome)}>
                <td className="py-2 pr-3 font-semibold">{x.nome}</td>
                {x.semanas.map((s) => (
                  <td key={s.semana} className="num pr-3">
                    <b style={{ color: COR_NIVEL[s.nivel] }}>{num(s.tecnicos_dia, 0)}</b>
                    <span className="text-[11px] text-cinza"> / normal {num(s.normal_tecnicos_dia, 0)}</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-[12px] text-cinza">Técnicos-dia por semana (jornada de {m.data.jornada_h} h). O normal é a média executada nas últimas 8 semanas.</p>
      </div>
      {atual && (
        <div className="mt-4">
          <h3 className="text-[15px] font-bold">{atual.nome}: o que entra em cada semana</h3>
          <div className="mt-2 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {atual.semanas.map((s) => (
              <button key={s.semana} onClick={() => setAberto(s.cartao.previsao_id)} className="border border-linha p-2 text-left text-[12px] hover:border-tinta">
                <div className="flex items-center justify-between">
                  <b className="text-[13px]">{s.rotulo}</b><SeloNivel nivel={s.nivel} />
                </div>
                <div className="num mt-1 text-[20px] font-bold">{num(s.tecnicos_dia, 0)} <span className="text-[12px] font-normal">técnicos-dia</span></div>
                <div className="text-cinza">entre {num(s.faixa[0], 0)} e {num(s.faixa[1], 0)} · normal {num(s.normal_tecnicos_dia, 0)}</div>
                <ul className="mt-2 space-y-[2px]">
                  <li>{num(s.corretivas, 0)} falhas esperadas (P1)</li>
                  {s.pendentes > 0 && <li>{s.pendentes} parados à espera de conserto</li>}
                  <li>{s.preventivas} preventivas{s.preventivas_atrasadas ? `, incluindo ¼ das ${s.preventivas_atrasadas} atrasadas` : ""}</li>
                  <li>cerca de {s.pecas} kits de reparo</li>
                </ul>
                <div className="mt-2 border-t border-linha pt-1 text-cinza">
                  {s.por_tipo.slice(0, 3).map((t) => `${t.nome}: ${num(t.tecnicos_dia, 0)}`).join(" · ")}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
      {aberto != null && <GavetaCartao id={aberto} fechar={() => setAberto(null)} />}
    </div>
  );
}

export default function Tendencias() {
  const [aba, setAba] = useState<"disp" | "manut">("disp");
  return (
    <div>
      <h1 className="text-[26px] font-bold tracking-[-0.02em]">Tendências</h1>
      <p className="text-cinza">
        Para onde a disponibilidade dos equipamentos está indo (30 e 90 dias) e quanta manutenção vem pela frente (4 semanas). Dados sintéticos.
      </p>
      <div className="mt-3 flex gap-4 border-b border-linha text-[14px] font-semibold">
        <button onClick={() => setAba("disp")} className={`pb-2 ${aba === "disp" ? "border-b-2 border-tinta" : "text-cinza"}`}>Disponibilidade</button>
        <button onClick={() => setAba("manut")} className={`pb-2 ${aba === "manut" ? "border-b-2 border-tinta" : "text-cinza"}`}>Carga de manutenção</button>
      </div>
      <div className="mt-3"><AvisoTreino /></div>
      {aba === "disp" ? <Disponibilidade /> : <CargaManutencao />}
    </div>
  );
}
