import { useState } from "react";
import { BellOff, Check, ChevronDown, ChevronRight, ClipboardList, Crosshair, Loader2, Telescope, UserPlus, X } from "lucide-react";
import { ApiError } from "../api/client";
import { useAbrirOS, useAcaoAlerta, useAlerta, useAlertasCentral, useFila } from "./api";
import { useFiltrosCentral } from "./filtros";
import { useTela } from "./store";
import type { AlertaC, ItemFila } from "./tipos";
import { COR_NIVEL, ROTULO_ESTADO_ALERTA, ROTULO_NIVEL, emRegiao, idade } from "./visual";

function erroTexto(e: unknown) {
  return e instanceof ApiError ? e.erro.mensagem : e instanceof Error ? e.message : "Erro";
}

export function focarAlerta(a: AlertaC) {
  const t = useTela.getState();
  if (a.equipamento_id) t.selecionar({ tipo: "equipamento", id: a.equipamento_id, alertaId: a.id });
  else t.selecionar({ tipo: "alerta", id: a.id });
  if (a.lon != null && a.lat != null) t.voar({ lon: a.lon, lat: a.lat, zoom: a.regra === "regiao_descoberta" ? 12.5 : 16 });
}

/** "em 2 h 30 min", "agora" ou "começou há 40 min": antecedência do alerta preventivo, calculada na hora. */
export function antecedencia(previstoPara: string, ate?: string, agora = Date.now()) {
  const ini = new Date(previstoPara).getTime();
  const min = Math.round((ini - agora) / 60_000);
  if (min > 0) {
    const h = Math.floor(min / 60), m = min % 60;
    return `em ${h ? `${h} h` : ""}${h && m ? " " : ""}${m || !h ? `${m} min` : ""}`;
  }
  if (ate && new Date(ate).getTime() > agora) return "em andamento";
  return "agora";
}

function horaLocal(iso: string) {
  return new Date(iso).toLocaleString("pt-BR", { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

function Silenciar({ a, fechar }: { a: AlertaC; fechar: () => void }) {
  const [motivo, setMotivo] = useState("");
  const [min, setMin] = useState(30);
  const acao = useAcaoAlerta();
  return (
    <form
      className="mt-2 space-y-2 border border-linha bg-neutro p-2"
      onSubmit={(e) => { e.preventDefault(); acao.mutate({ id: a.id, acao: "silenciar", motivo, minutos: min }, { onSuccess: fechar }); }}
    >
      <input className="campo !py-1 text-[13px]" placeholder="Motivo (obrigatório)" value={motivo} onChange={(e) => setMotivo(e.target.value)} autoFocus />
      <div className="flex items-center gap-2 text-[12px]">
        <select className="campo !w-auto !py-1 text-[13px]" value={min} onChange={(e) => setMin(Number(e.target.value))}>
          {[5, 10, 15, 30].map((m) => <option key={m} value={m}>{m} min</option>)}
        </select>
        <button type="submit" disabled={!motivo.trim() || acao.isPending} className="border border-tinta bg-papel px-2 py-1 font-semibold disabled:opacity-40">Silenciar</button>
        <button type="button" className="text-cinza" onClick={fechar}>Cancelar</button>
      </div>
      {acao.isError && <p className="text-[12px] text-critico">{erroTexto(acao.error)}</p>}
    </form>
  );
}

function Resolver({ a, fechar }: { a: AlertaC; fechar: () => void }) {
  const [motivo, setMotivo] = useState("");
  const acao = useAcaoAlerta();
  return (
    <form
      className="mt-2 flex gap-2 border border-linha bg-neutro p-2"
      onSubmit={(e) => { e.preventDefault(); acao.mutate({ id: a.id, acao: "resolver", motivo: motivo || undefined }, { onSuccess: fechar }); }}
    >
      <input className="campo !py-1 text-[13px]" placeholder="Como foi resolvido (opcional)" value={motivo} onChange={(e) => setMotivo(e.target.value)} autoFocus />
      <button type="submit" disabled={acao.isPending} className="shrink-0 border border-tinta bg-papel px-2 py-1 text-[12px] font-semibold">Encerrar</button>
      <button type="button" className="text-cinza" onClick={fechar} aria-label="Cancelar"><X size={14} /></button>
    </form>
  );
}

function Membros({ id }: { id: number }) {
  const q = useAlerta(id);
  if (q.isLoading) return <div className="py-1 text-[12px] text-cinza">Carregando…</div>;
  return (
    <ul className="mt-1 space-y-1 border-l-2 border-linha pl-2">
      {(q.data?.lista_membros ?? []).map((m) => (
        <li key={m.id}>
          <button className="w-full text-left text-[12px] hover:underline" onClick={() => focarAlerta(m)}>
            <span className="mr-1 inline-block h-[7px] w-[7px]" style={{ background: COR_NIVEL[m.nivel] }} />
            <b className="num">{m.codigo_interno}</b> {m.rotulo_regra.toLowerCase()}{m.resolvido_em ? " · resolvido" : ""}
          </button>
        </li>
      ))}
    </ul>
  );
}

export function CardAlerta({ a, compacto }: { a: AlertaC; compacto?: boolean }) {
  const sel = useTela((s) => s.selecao);
  const [modo, setModo] = useState<"" | "silenciar" | "resolver">("");
  const [aberto, setAberto] = useState(false);
  const acao = useAcaoAlerta();
  const os = useAbrirOS();
  const selecionado = (sel?.tipo === "alerta" && sel.id === a.id) || (sel?.tipo === "equipamento" && sel.alertaId === a.id);
  const silenciado = a.silenciado_ate && new Date(a.silenciado_ate).getTime() > Date.now();
  const incidente = a.regra === "incidente_correlacionado";
  const prev = a.preditivo;
  return (
    <article
      className={`border-l-[5px] px-3 py-2 ${prev ? "border-dashed bg-[#f6f4fb]" : "bg-papel"} ${selecionado ? "outline outline-2 outline-acento" : ""} ${silenciado ? "opacity-60" : ""}`}
      style={{ borderLeftColor: COR_NIVEL[a.nivel] }}
    >
      {prev && (
        <div className="mb-1 flex items-center justify-between gap-2 text-[11px] font-semibold text-[#5b3fa6]">
          <span className="inline-flex items-center gap-1 uppercase tracking-[0.05em]"><Telescope size={12} /> Previsão</span>
          {prev.modulo !== "P1" && (
            <span className="num">previsto para {horaLocal(prev.previsto_para)} · {antecedencia(prev.previsto_para, prev.ate)}</span>
          )}
        </div>
      )}
      <button className="block w-full text-left" onClick={() => focarAlerta(a)}>
        <div className="flex items-baseline justify-between gap-2 text-[11px]">
          <span className="font-bold uppercase tracking-[0.05em]" style={{ color: COR_NIVEL[a.nivel] }}>
            {ROTULO_NIVEL[a.nivel]} · {a.rotulo_regra}
          </span>
          <span className="num shrink-0 text-cinza">{idade(a.criado_em)}</span>
        </div>
        <div className="mt-[2px] text-[13px] font-semibold leading-snug">{a.mensagem}</div>
        <div className="mt-[3px] flex flex-wrap gap-x-2 text-[11px] text-cinza">
          {a.regiao && <span>{emRegiao(a.regiao)}</span>}
          <span className={a.estado === "aberto" ? "font-semibold text-tinta" : ""}>{ROTULO_ESTADO_ALERTA[a.estado]}</span>
          {a.contador > 1 && !incidente && <span>repetiu {a.contador}×</span>}
          {a.agente && <span>agente: {a.agente.nome} ({a.agente.orgao})</span>}
          {a.ordem_servico_id && <span>OS #{a.ordem_servico_id}</span>}
          {silenciado && <span>silenciado até {new Date(a.silenciado_ate!).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>}
          {a.simulado && <span className="text-acento">simulado</span>}
        </div>
        {!compacto && a.motivos_nivel.length > 0 && (
          <ul className="mt-1 space-y-[1px] text-[11px]">
            {a.motivos_nivel.map((m) => <li key={m} className="text-tinta">↑ {m}</li>)}
          </ul>
        )}
      </button>
      {incidente && (
        <button className="mt-1 inline-flex items-center gap-1 text-[12px] font-semibold" onClick={() => setAberto(!aberto)}>
          {aberto ? <ChevronDown size={13} /> : <ChevronRight size={13} />} {a.membros} equipamentos dentro
        </button>
      )}
      {incidente && aberto && <Membros id={a.id} />}
      {!compacto && !a.resolvido_em && (
        <div className="mt-2 flex flex-wrap gap-1">
          {prev && <Acao onClick={() => useTela.getState().abrirCartao(prev.previsao_id)}><Telescope size={13} /> Ver previsão</Acao>}
          {a.estado === "aberto" && (
            <Acao onClick={() => acao.mutate({ id: a.id, acao: "reconhecer" })} carregando={acao.isPending}><Check size={13} /> Estou vendo</Acao>
          )}
          {a.lon != null && !prev && <Acao onClick={() => focarAlerta(a)}><UserPlus size={13} /> Atribuir</Acao>}
          {a.equipamento_id && !a.ordem_servico_id && (
            <Acao onClick={() => os.mutate(a.id)} carregando={os.isPending}><ClipboardList size={13} /> Abrir OS</Acao>
          )}
          {silenciado
            ? <Acao onClick={() => acao.mutate({ id: a.id, acao: "reabrir_som" })}><BellOff size={13} /> Reativar</Acao>
            : <Acao onClick={() => setModo(modo === "silenciar" ? "" : "silenciar")}><BellOff size={13} /> Silenciar</Acao>}
          <Acao onClick={() => setModo(modo === "resolver" ? "" : "resolver")}><X size={13} /> Resolver</Acao>
        </div>
      )}
      {(acao.isError || os.isError) && <p className="mt-1 text-[12px] text-critico">{erroTexto(acao.error ?? os.error)}</p>}
      {modo === "silenciar" && <Silenciar a={a} fechar={() => setModo("")} />}
      {modo === "resolver" && <Resolver a={a} fechar={() => setModo("")} />}
    </article>
  );
}

function Acao({ onClick, children, carregando }: { onClick: () => void; children: React.ReactNode; carregando?: boolean }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(); }} disabled={carregando}
      className="inline-flex items-center gap-1 border border-linha bg-papel px-[7px] py-[3px] text-[12px] font-semibold hover:border-tinta disabled:opacity-40"
    >
      {carregando ? <Loader2 size={13} className="animate-spin" /> : null}{children}
    </button>
  );
}

function ListaAlertas() {
  const { params, chave } = useFiltrosCentral();
  const [soNovos, setSoNovos] = useState(false);
  const [limite, setLimite] = useState(60);
  const q = useAlertasCentral(params, chave, soNovos ? { estado: "aberto" } : {}, limite);
  const itens = q.data?.itens ?? [];
  const criticos = itens.filter((a) => a.nivel === "critica" && !(a.silenciado_ate && new Date(a.silenciado_ate).getTime() > Date.now()));
  const resto = itens.filter((a) => !criticos.includes(a));
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-linha px-3 py-2 text-[12px]">
        <label className="flex items-center gap-1"><input type="checkbox" checked={soNovos} onChange={(e) => setSoNovos(e.target.checked)} /> Só não reconhecidos</label>
        <span className="num ml-auto text-cinza">{q.data ? `${q.data.total.toLocaleString("pt-BR")} na lista` : ""}</span>
      </div>
      {q.isLoading && <div className="p-3 text-cinza">Carregando…</div>}
      {q.isError && <div className="p-3 text-critico">{erroTexto(q.error)}</div>}
      {criticos.length > 0 && (
        <div className="max-h-[46%] shrink-0 space-y-[6px] overflow-y-auto border-b-2 border-critico bg-[#fdf1f1] p-2">
          {criticos.map((a) => <CardAlerta key={a.id} a={a} />)}
        </div>
      )}
      <div className="min-h-0 flex-1 space-y-[6px] overflow-y-auto bg-neutro p-2">
        {!q.isLoading && itens.length === 0 && <p className="p-2 text-cinza">Nenhum alerta com estes filtros.</p>}
        {resto.map((a) => <CardAlerta key={a.id} a={a} />)}
        {q.data && q.data.total > itens.length && (
          <button className="w-full border border-linha bg-papel py-2 text-[12px] font-semibold" onClick={() => setLimite(limite + 60)}>
            Mostrar mais ({(q.data.total - itens.length).toLocaleString("pt-BR")})
          </button>
        )}
      </div>
    </div>
  );
}

const CAT_FILA = { imediata: { r: "Imediata", cor: COR_NIVEL.critica }, vencida: { r: "Vencida", cor: COR_NIVEL.alta }, proxima: { r: "Próxima", cor: COR_NIVEL.media } };

function LinhaFila({ i }: { i: ItemFila }) {
  const quando = i.dias == null ? "" : i.dias < 0 ? `atrasada ${-i.dias} dia${i.dias === -1 ? "" : "s"}` : i.dias === 0 ? "hoje" : `em ${i.dias} dia${i.dias === 1 ? "" : "s"}`;
  return (
    <li className="border-l-[4px] bg-papel px-3 py-2" style={{ borderLeftColor: CAT_FILA[i.categoria].cor }}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-bold uppercase tracking-[0.05em]" style={{ color: CAT_FILA[i.categoria].cor }}>{CAT_FILA[i.categoria].r} · {quando}</span>
        {i.lon != null && (
          <button
            className="inline-flex items-center gap-1 text-[12px] font-semibold hover:underline"
            onClick={() => { useTela.getState().selecionar({ tipo: "equipamento", id: i.equipamento_id }); useTela.getState().voar({ lon: i.lon!, lat: i.lat!, zoom: 16 }); }}
          >
            <Crosshair size={12} /> Localizar
          </button>
        )}
      </div>
      <div className="text-[13px]"><b className="num">{i.codigo_interno}</b> · {i.tipo}</div>
      <div className="text-[12px] text-cinza">{i.motivo}</div>
      <div className="text-[11px] text-cinza">
        {i.regiao ?? "sem região"}{i.ordem_servico ? ` · OS #${i.ordem_servico.id} (${i.ordem_servico.prioridade})` : " · sem OS"}
      </div>
    </li>
  );
}

function FilaManutencao() {
  const { params, chave } = useFiltrosCentral();
  const q = useFila(params, chave, true);
  const [cat, setCat] = useState<"" | ItemFila["categoria"]>("");
  const itens = (q.data?.itens ?? []).filter((i) => !cat || i.categoria === cat);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap gap-1 border-b border-linha px-3 py-2 text-[12px]">
        {(["", "imediata", "vencida", "proxima"] as const).map((c) => (
          <button key={c} onClick={() => setCat(c)} className={`border px-2 py-[2px] ${cat === c ? "border-tinta font-semibold" : "border-linha text-cinza"}`}>
            {c ? CAT_FILA[c].r : "Todas"} <span className="num">{c ? q.data?.totais[c] ?? 0 : q.data?.total ?? 0}</span>
          </button>
        ))}
      </div>
      {q.isLoading && <div className="p-3 text-cinza">Carregando…</div>}
      <ul className="min-h-0 flex-1 space-y-[6px] overflow-y-auto bg-neutro p-2">
        {itens.map((i) => <LinhaFila key={i.equipamento_id} i={i} />)}
        {q.data && q.data.total > (q.data.itens.length ?? 0) && (
          <li className="p-2 text-center text-[12px] text-cinza">Mostrando os {q.data.itens.length} mais urgentes de {q.data.total.toLocaleString("pt-BR")}. Use os filtros para focar.</li>
        )}
      </ul>
    </div>
  );
}

export default function PainelAlertas() {
  const aba = useTela((s) => s.aba);
  const setAba = useTela((s) => s.setAba);
  const { params, chave } = useFiltrosCentral();
  const n = useAlertasCentral(params, chave, {}, 60).data?.por_nivel;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex border-b border-tinta" role="tablist">
        {([["alertas", "Alertas"], ["manutencao", "Manutenção"]] as const).map(([k, r]) => (
          <button
            key={k} role="tab" aria-selected={aba === k} onClick={() => setAba(k)}
            className={`-mb-px flex-1 border-b-[3px] px-3 py-2 text-[13px] font-semibold ${aba === k ? "border-acento" : "border-transparent text-cinza"}`}
          >
            {r}
            {k === "alertas" && n && (
              <span className="num ml-2 text-[12px]">
                <span style={{ color: COR_NIVEL.critica }}>{n.critica}</span> · <span style={{ color: COR_NIVEL.alta }}>{n.alta}</span> · <span className="text-cinza">{n.media}</span>
              </span>
            )}
          </button>
        ))}
      </div>
      {aba === "alertas" ? <ListaAlertas /> : <FilaManutencao />}
    </div>
  );
}
