import { useEffect, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { FileText, History, Loader2, MessageSquare, Monitor, RotateCcw, Siren, Volume2, VolumeX } from "lucide-react";
import { ApiError } from "../api/client";
import { usePerguntar, useRestaurar, useResumoTurno, useSimular } from "./api";
import { liberarSom } from "./som";
import { focarAlerta } from "./PainelAlertas";
import { useTela } from "./store";

const TIPOS_INCIDENTE = [
  ["furto", "Furto de radar", "O radar manda posição longe do ponto de instalação"],
  ["queda_energia", "Queda de energia", "Vários equipamentos próximos ficam em silêncio ao mesmo tempo"],
  ["falha", "Falha de equipamento", "O equipamento manda sinal de erro"],
  ["silencio", "Silêncio", "Uma câmera para de mandar sinal"],
  ["degradado", "Sinal degradado", "Câmera com queda de qualidade de imagem"],
  ["sem_agentes", "Região sem agentes", "Os agentes da região entram em pausa"],
] as const;
const REGIOES = ["Centro", "Norte", "Sul", "Leste", "Oeste"];

function erro(e: unknown) {
  return e instanceof ApiError ? e.erro.mensagem : "Não foi possível falar com a API.";
}

function Pop({ rotulo, icone, children, largura = 340, ativo }: { rotulo: string; icone: ReactNode; children: (fechar: () => void) => ReactNode; largura?: number; ativo?: boolean }) {
  const [aberto, setAberto] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setAberto(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setAberto(false); };
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", fora); document.removeEventListener("keydown", esc); };
  }, [aberto]);
  return (
    <div className="relative" ref={ref}>
      <Botao onClick={() => setAberto(!aberto)} ativo={aberto || ativo} aria-expanded={aberto}>{icone}{rotulo}</Botao>
      {aberto && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-40 border border-tinta bg-papel p-3 shadow-[0_8px_28px_rgba(0,0,0,0.2)]" style={{ width: largura }}>
          {children(() => setAberto(false))}
        </div>
      )}
    </div>
  );
}

function Botao({ children, ativo, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { ativo?: boolean }) {
  return (
    <button
      {...p}
      className={`inline-flex items-center gap-[6px] whitespace-nowrap border px-[9px] py-[5px] text-[12px] font-semibold ${ativo ? "border-tinta bg-tinta text-papel" : "border-linha bg-papel hover:border-tinta"}`}
    >
      {children}
    </button>
  );
}

function Simular() {
  const [tipo, setTipo] = useState<string>("furto");
  const [regiao, setRegiao] = useState("Norte");
  const [qtd, setQtd] = useState(5);
  const sim = useSimular();
  const rest = useRestaurar();
  return (
    <Pop rotulo="Simular incidente" icone={<Siren size={14} />} largura={360}>
      {() => (
        <div className="space-y-2">
          <p className="text-[12px] text-cinza">Provoca o problema com sinais iguais aos de um equipamento real; o motor faz o resto. Funciona sem internet.</p>
          <div className="space-y-1">
            {TIPOS_INCIDENTE.map(([v, r, d]) => (
              <label key={v} className={`flex cursor-pointer gap-2 border px-2 py-1 ${tipo === v ? "border-tinta" : "border-linha"}`}>
                <input type="radio" name="tipo" checked={tipo === v} onChange={() => setTipo(v)} className="mt-[3px]" />
                <span><span className="block text-[13px] font-semibold">{r}</span><span className="block text-[11px] text-cinza">{d}</span></span>
              </label>
            ))}
          </div>
          <div className="flex gap-2">
            <select className="campo" value={regiao} onChange={(e) => setRegiao(e.target.value)} aria-label="Região">
              {REGIOES.map((r) => <option key={r}>{r}</option>)}
            </select>
            {tipo === "queda_energia" && (
              <select className="campo !w-[110px]" value={qtd} onChange={(e) => setQtd(Number(e.target.value))} aria-label="Quantidade">
                {[3, 5, 8, 12].map((n) => <option key={n} value={n}>{n} equip.</option>)}
              </select>
            )}
          </div>
          <button
            className="flex w-full items-center justify-center gap-2 border border-acento bg-acento px-3 py-2 text-[13px] font-semibold text-white disabled:opacity-50"
            disabled={sim.isPending}
            onClick={() => sim.mutate({ tipo, regiao, quantidade: qtd }, {
              onSuccess: (r) => {
                const pior = [...r.alertas].sort((a, b) => (b.nivel === "critica" ? 1 : 0) - (a.nivel === "critica" ? 1 : 0))[0];
                if (pior) focarAlerta(pior);
              },
            })}
          >
            {sim.isPending && <Loader2 size={14} className="animate-spin" />} Provocar agora
          </button>
          {sim.isSuccess && <p className="text-[12px]">Feito: {sim.data.afetados.join(", ")}. {sim.data.alertas.length} alerta(s) gerado(s) pelo motor.</p>}
          {sim.isError && <p className="text-[12px] text-critico">{erro(sim.error)}</p>}
          <button className="inline-flex items-center gap-1 text-[12px] text-cinza underline hover:text-tinta" onClick={() => rest.mutate()} disabled={rest.isPending}>
            <RotateCcw size={12} /> Restaurar tudo o que foi simulado
          </button>
          {rest.isSuccess && <p className="text-[12px]">{rest.data.alertas_resolvidos} alerta(s) resolvido(s).</p>}
        </div>
      )}
    </Pop>
  );
}

function Resumo() {
  const [ativo, setAtivo] = useState(false);
  const q = useResumoTurno(ativo);
  return (
    <div onClickCapture={() => setAtivo(true)}>
      <Pop rotulo="Resumo do turno" icone={<FileText size={14} />} largura={420}>
        {() => (
          <div>
            <div className="mb-1 flex items-baseline justify-between">
              <span className="text-[11px] font-bold uppercase tracking-[0.06em]">O que mudou na última hora</span>
              <button className="text-[12px] text-cinza underline" onClick={() => q.refetch()}>Atualizar</button>
            </div>
            {q.isLoading || q.isFetching ? <p className="text-cinza">Montando…</p> : q.data ? (
              <>
                <p className="text-[14px] leading-relaxed">{q.data.texto}</p>
                <p className="mt-2 text-[11px] text-cinza">{q.data.fonte === "ia" ? "Texto escrito pela IA a partir dos alertas e indicadores." : "Modelo de texto (IA indisponível ou desligada)."}</p>
              </>
            ) : q.isError ? <p className="text-critico">{erro(q.error)}</p> : null}
          </div>
        )}
      </Pop>
    </div>
  );
}

function Perguntar() {
  const [q, setQ] = useState("");
  const m = usePerguntar();
  return (
    <Pop rotulo="Perguntar" icone={<MessageSquare size={14} />} largura={420}>
      {() => (
        <div className="space-y-2">
          <form onSubmit={(e) => { e.preventDefault(); if (q.trim().length > 1) m.mutate(q.trim()); }} className="flex gap-2">
            <input className="campo" autoFocus placeholder="O que está acontecendo no Centro?" value={q} onChange={(e) => setQ(e.target.value)} />
            <button className="shrink-0 border border-tinta px-3 text-[13px] font-semibold" disabled={m.isPending}>Perguntar</button>
          </form>
          <div className="flex flex-wrap gap-1">
            {["O que está acontecendo no Centro?", "Como está a zona Norte?", "Como está a cidade?"].map((s) => (
              <button key={s} className="border border-linha px-2 py-[2px] text-[11px] text-cinza hover:border-tinta" onClick={() => { setQ(s); m.mutate(s); }}>{s}</button>
            ))}
          </div>
          {m.isPending && <p className="text-cinza">Consultando…</p>}
          {m.isError && <p className="text-critico">{erro(m.error)}</p>}
          {m.data && (
            <div>
              <p className="text-[14px] leading-relaxed">{m.data.texto}</p>
              {m.data.alertas.slice(0, 3).map((a) => (
                <button key={a.id} className="mt-1 block w-full text-left text-[12px] underline" onClick={() => focarAlerta(a)}>{a.mensagem}</button>
              ))}
              <p className="mt-2 text-[11px] text-cinza">{m.data.fonte === "ia" ? "Resposta da IA com os dados da central." : "Resposta montada com os dados da central (sem IA)."}</p>
            </div>
          )}
        </div>
      )}
    </Pop>
  );
}

export default function Ferramentas() {
  const [, setSp] = useSearchParams();
  const som = useTela((s) => s.som);
  const linhaAberta = useTela((s) => s.linhaAberta);
  return (
    <div className="flex flex-wrap items-center gap-[6px]">
      <Simular />
      <Resumo />
      <Perguntar />
      <Botao ativo={linhaAberta} onClick={() => useTela.getState().setLinhaAberta(!linhaAberta)}><History size={14} />Linha do tempo</Botao>
      <Botao
        onClick={() => {
          setSp((a) => { const n = new URLSearchParams(a); n.set("sala", "1"); return n; });
          document.documentElement.requestFullscreen?.().catch(() => {});
        }}
      >
        <Monitor size={14} />Sala de situação
      </Botao>
      <Botao
        onClick={() => { if (!som) liberarSom(); useTela.getState().setSom(!som); }}
        aria-label={som ? "Desligar som dos alertas críticos" : "Ligar som dos alertas críticos"} title="Som e aviso para alertas críticos"
      >
        {som ? <Volume2 size={14} /> : <VolumeX size={14} />}
      </Botao>
    </div>
  );
}
