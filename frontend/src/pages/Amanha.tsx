import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarDays, CloudRain, Pause, Play, RefreshCw, Thermometer, Users } from "lucide-react";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { ApiError } from "../api/client";
import { SeletorPerfil } from "../components/Layout";
import { Botao, Carregando } from "../components/ui";
import { useRegioesGeo } from "../central/api";
import CartaoPrevisao, { SeloNivel } from "../preditivo/CartaoPrevisao";
import MapaRisco from "../preditivo/MapaRisco";
import AvisoTreino from "../preditivo/AvisoTreino";
import { useAmanha, useCartoes, useDetalheRegiao, useEditarClima, useRecalcularPrevisoes } from "../preditivo/api";
import { COR_NIVEL, dia, num } from "../preditivo/formato";
import type { Amanha as TAmanha } from "../preditivo/tipos";

const hora = (iso: string) => new Date(iso).toLocaleString("pt-BR", { weekday: "short", day: "2-digit", hour: "2-digit" }).replace(",", "");

function EditarClima({ fechar }: { fechar: () => void }) {
  const editar = useEditarClima();
  const amanha = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  const [f, setF] = useState({ dia: amanha, de: 14, ate: 19, chuva: 15, tempestade: true });
  const enviar = () => {
    const ini = new Date(`${f.dia}T${String(f.de).padStart(2, "0")}:00:00-03:00`);
    const fim = new Date(`${f.dia}T${String(f.ate).padStart(2, "0")}:00:00-03:00`);
    editar.mutate({ inicio: ini.toISOString(), fim: fim.toISOString(), chuva_mm: f.chuva, alerta_tempestade: f.tempestade }, { onSuccess: fechar });
  };
  return (
    <div className="absolute left-3 top-[calc(100%+4px)] z-30 w-[300px] border border-tinta bg-papel p-3 text-[13px] shadow-lg">
      <div className="mb-2 font-semibold">Mudar a previsão do tempo</div>
      <label className="rotulo">Dia</label>
      <input type="date" className="campo" value={f.dia} onChange={(e) => setF({ ...f, dia: e.target.value })} />
      <div className="mt-2 grid grid-cols-2 gap-2">
        <label>De (h)<input type="number" min={0} max={23} className="campo" value={f.de} onChange={(e) => setF({ ...f, de: +e.target.value })} /></label>
        <label>Até (h)<input type="number" min={1} max={24} className="campo" value={f.ate} onChange={(e) => setF({ ...f, ate: +e.target.value })} /></label>
      </div>
      <label className="mt-2 block">Chuva (mm por hora)<input type="number" min={0} max={100} className="campo" value={f.chuva} onChange={(e) => setF({ ...f, chuva: +e.target.value })} /></label>
      <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={f.tempestade} onChange={(e) => setF({ ...f, tempestade: e.target.checked })} /> Alerta de tempestade</label>
      <p className="mt-2 text-[12px] text-cinza">As previsões são refeitas com o novo clima ao clicar em "Recalcular previsões".</p>
      <div className="mt-3 flex gap-2">
        <Botao variante="primario" carregando={editar.isPending} onClick={enviar}>Salvar</Botao>
        <Botao variante="fantasma" onClick={fechar}>Cancelar</Botao>
      </div>
    </div>
  );
}

function Contexto({ d }: { d: TAmanha }) {
  const [editando, setEditando] = useState(false);
  const recalcular = useRecalcularPrevisoes();
  const { feriados, eventos, clima } = d.contexto;
  const grandes = eventos.filter((e) => e.publico_estimado >= 1000);
  return (
    <div className="relative flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-linha px-3 py-2 text-[12px]">
      <span className="flex items-center gap-1 font-semibold"><CalendarDays size={14} />
        {feriados.length ? feriados.map((f) => `${f.vespera ? "Véspera de feriado" : f.nome} (${dia(f.data)})`).join(" · ") : "Sem feriados no período"}
      </span>
      <span className="flex items-center gap-1"><Users size={14} />
        {grandes.length ? grandes.slice(0, 4).map((e) => (
          <span key={e.id} className="mr-2"><b>{e.nome}</b> · {e.local_nome} · {hora(e.inicio_em)} · {num(e.publico_estimado / 1000, 0)} mil</span>
        )) : "Sem eventos grandes"}
        {grandes.length > 4 && <span className="text-cinza">+{grandes.length - 4}</span>}
      </span>
      <span className="flex items-center gap-2">
        {clima.map((c) => (
          <span key={c.dia} className={`flex items-center gap-1 ${c.tempestade ? "font-semibold text-critico" : ""}`} title={c.editado ? "Previsão editada pelo operador" : "Previsão sintética"}>
            {c.chuva_mm >= 1 ? <CloudRain size={13} /> : <Thermometer size={13} />}
            {dia(c.dia)}: {num(c.temp_max, 0)} °C{c.chuva_mm >= 1 ? `, ${num(c.chuva_mm, 0)} mm` : ""}{c.tempestade ? " (tempestade)" : ""}{c.editado ? "*" : ""}
          </span>
        ))}
      </span>
      <span className="ml-auto flex gap-2">
        <Botao variante="fantasma" onClick={() => setEditando(!editando)}>Editar clima</Botao>
        <Botao carregando={recalcular.isPending} onClick={() => recalcular.mutate()}><RefreshCw size={13} /> Recalcular previsões</Botao>
      </span>
      {recalcular.error instanceof ApiError && <span className="w-full text-critico">{recalcular.error.erro.mensagem}</span>}
      {editando && <EditarClima fechar={() => setEditando(false)} />}
    </div>
  );
}

function GraficoRegiao({ id, emSel }: { id: number; emSel: string | null }) {
  const det = useDetalheRegiao(id);
  if (det.isLoading) return <Carregando />;
  if (!det.data) return null;
  const dados = det.data.serie.map((p) => ({ ...p, x: hora(p.em), faixa: [p.inferior, p.superior] }));
  const sel = emSel ? hora(emSel) : null;
  return (
    <div>
      <h3 className="text-[15px] font-bold">{det.data.regiao}: ocorrências por hora</h3>
      <p className="text-[12px] text-cinza">Previsto com a faixa provável (90%), o normal da hora e, nas horas que já passaram, o que aconteceu.</p>
      <div className="mt-2 h-[220px]">
        <ResponsiveContainer>
          <ComposedChart data={dados} margin={{ left: -18, right: 8, top: 6 }}>
            <CartesianGrid stroke="#eee" vertical={false} />
            <XAxis dataKey="x" tick={{ fontSize: 10 }} interval={11} />
            <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
            <Tooltip formatter={(v: number | number[]) => (Array.isArray(v) ? `${num(v[0])} a ${num(v[1])}` : num(Number(v)))} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Area dataKey="faixa" name="Faixa provável" stroke="none" fill="#ff4f00" fillOpacity={0.15} isAnimationActive={false} />
            <Line dataKey="previsto" name="Previsto" stroke="#ff4f00" dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line dataKey="normal" name="Normal da hora" stroke="#6b6b6b" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            <Scatter dataKey="real" name="Aconteceu" fill="#111" isAnimationActive={false} />
            {sel && <ReferenceLine x={sel} stroke="#111" />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <h4 className="mt-4 text-[11px] font-bold uppercase tracking-[0.08em] text-cinza">Períodos (índice de risco e equipes)</h4>
      <div className="mt-2 space-y-3">
        {det.data.cartoes.filter((c) => c.modulo === "P3" || c.acao_recomendada?.tipo === "REFORCAR_EQUIPES").map((c) => (
          <CartaoPrevisao key={c.previsao_id} c={c} compacto />
        ))}
      </div>
    </div>
  );
}

function Recomendacoes() {
  const cartoes = useCartoes({ modulo: "P4", atuais: true, limite: 200 });
  const lista = (cartoes.data ?? []).filter((c) => c.acao_recomendada?.tipo === "REFORCAR_EQUIPES");
  if (cartoes.isLoading) return <Carregando />;
  return (
    <div className="space-y-3">
      <p className="text-[12px] text-cinza">Reforços sugeridos para as próximas 72 h, só redistribuindo quem já está escalado. Aceitar move as equipes na escala.</p>
      {lista.length === 0 && <p className="text-[13px]">Nenhum reforço necessário: a escala cobre a demanda prevista.</p>}
      {lista.map((c) => <CartaoPrevisao key={c.previsao_id} c={c} compacto />)}
      <Link to="/previsao/equipes" className="block text-[13px] font-semibold underline">Ver o planejamento completo de equipes</Link>
    </div>
  );
}

export default function Amanha() {
  const d = useAmanha();
  const geo = useRegioesGeo();
  const [i, setI] = useState(0);
  const [tocando, setTocando] = useState(false);
  const [regiao, setRegiao] = useState<number | null>(null);
  const [aba, setAba] = useState<"regiao" | "recomendacoes">("recomendacoes");
  const horas = d.data?.horas ?? [];
  const atual = horas[Math.min(i, Math.max(horas.length - 1, 0))];

  useEffect(() => {
    if (!tocando || !horas.length) return;
    const t = setInterval(() => setI((x) => (x + 1) % horas.length), 400);
    return () => clearInterval(t);
  }, [tocando, horas.length]);

  const escolher = (id: number) => { setRegiao(id); setAba("regiao"); };
  const pior = useMemo(() => atual?.regioes[0], [atual]);

  if (d.isLoading) return <Carregando texto="Carregando as previsões…" />;
  if (d.error) {
    return (
      <div className="p-8">
        <h1 className="text-[22px] font-bold">Amanhã</h1>
        <div className="mt-3 max-w-[720px]"><AvisoTreino /></div>
        <p className="mt-2">{d.error instanceof ApiError ? d.error.erro.mensagem : "Não foi possível carregar as previsões."}</p>
        <Link to="/central" className="mt-4 inline-block underline">Voltar à central</Link>
      </div>
    );
  }
  const dados = d.data!;
  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-tinta px-3 py-2">
        <div className="flex items-baseline gap-2">
          <Link to="/" className="text-[20px] font-bold tracking-[-0.02em]">Atalaia</Link>
          <span className="h-[9px] w-[9px] bg-acento" aria-hidden />
          <span className="text-[12px] font-semibold uppercase tracking-[0.06em]">Amanhã · próximas 72 horas</span>
        </div>
        <span className="text-[12px] text-cinza">{dados.selo.texto}</span>
        <nav className="ml-auto flex gap-3 text-[13px] font-semibold">
          <Link to="/central" className="underline">Central</Link>
          <Link to="/previsao/equipamentos" className="underline">Equipamentos em risco</Link>
          <Link to="/previsao/equipes" className="underline">Planejamento de equipes</Link>
          <Link to="/previsao/cenarios" className="underline">Cenários</Link>
          <Link to="/previsao/confianca" className="underline">Confiança dos modelos</Link>
        </nav>
        <SeletorPerfil />
      </header>
      <AvisoTreino />
      <Contexto d={dados} />

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <main className="relative min-h-[320px] flex-1">
          <MapaRisco geo={geo.data} regioes={atual?.regioes ?? []} selecionada={regiao} onSelecionar={escolher} />
          <div className="absolute left-2 right-2 top-2 z-10 border border-tinta bg-papel p-2 md:right-auto md:w-[520px]">
            <div className="flex items-center gap-2">
              <button className="border border-tinta p-1" onClick={() => setTocando(!tocando)} aria-label={tocando ? "Pausar" : "Reproduzir"}>
                {tocando ? <Pause size={14} /> : <Play size={14} />}
              </button>
              <input type="range" min={0} max={Math.max(horas.length - 1, 0)} value={i} onChange={(e) => { setTocando(false); setI(+e.target.value); }}
                className="flex-1 accent-[#ff4f00]" aria-label="Hora prevista" />
              <span className="num w-[120px] text-right text-[13px] font-bold">{atual ? hora(atual.em) : ""}</span>
            </div>
            {pior && (
              <p className="mt-1 text-[12px]">
                Região mais crítica: <b>{pior.regiao}</b> ({Math.round(pior.indice)}, <SeloNivel nivel={pior.nivel} />) · {pior.motivo}
              </p>
            )}
          </div>
          <div className="absolute bottom-2 left-2 z-10 flex gap-3 border border-linha bg-papel px-2 py-1 text-[11px]">
            {["BAIXO", "MODERADO", "ALTO", "MUITO_ALTO"].map((n) => <SeloNivel key={n} nivel={n} />)}
          </div>
        </main>
        <aside className="flex min-h-0 shrink-0 flex-col border-l border-linha md:w-[430px]">
          <div className="flex border-b border-tinta text-[13px] font-semibold">
            {(["recomendacoes", "regiao"] as const).map((a) => (
              <button key={a} onClick={() => setAba(a)} className={`flex-1 px-3 py-2 ${aba === a ? "border-b-[3px] border-acento" : "text-cinza"}`}>
                {a === "recomendacoes" ? `Recomendações (${dados.recomendacoes.length})` : "Região"}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {aba === "recomendacoes" ? <Recomendacoes /> : regiao != null ? <GraficoRegiao id={regiao} emSel={atual?.em ?? null} /> :
              <p className="text-[13px]">Clique numa região no mapa ou na faixa abaixo.</p>}
          </div>
        </aside>
      </div>

      <footer className="flex shrink-0 overflow-x-auto border-t border-tinta">
        {(atual?.regioes ?? []).map((r) => (
          <button key={r.regiao_id} onClick={() => escolher(r.regiao_id)}
            className={`min-w-[200px] flex-1 border-r border-linha px-3 py-2 text-left ${regiao === r.regiao_id ? "bg-neutro" : ""}`}>
            <div className="flex items-baseline justify-between">
              <span className="font-bold">{r.regiao}</span>
              <span className="cond num text-[26px] font-bold leading-none" style={{ color: COR_NIVEL[r.nivel] }}>{Math.round(r.indice)}</span>
            </div>
            <div className="text-[11px]"><SeloNivel nivel={r.nivel} /> · {num(r.ocorrencias ?? 0)} ocorrências previstas na hora</div>
            <div className="line-clamp-2 text-[11px] text-cinza">{r.motivo}</div>
          </button>
        ))}
      </footer>
    </div>
  );
}
