import type { ButtonHTMLAttributes, ReactNode } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import type { Situacao } from "../api/tipos";
import { ApiError } from "../api/client";
import { SITUACAO, corScore } from "../lib/rotulos";

type Variante = "primario" | "secundario" | "fantasma" | "perigo";

export function Botao({ variante = "secundario", carregando, children, className = "", ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variante?: Variante; carregando?: boolean }) {
  const estilos: Record<Variante, string> = {
    primario: "bg-acento text-papel border-acento hover:bg-acento-forte hover:border-acento-forte",
    secundario: "bg-neutro text-tinta border-linha hover:border-acento",
    fantasma: "bg-transparent text-tinta border-transparent hover:bg-neutro",
    perigo: "bg-papel text-critico border-critico hover:bg-critico-fundo",
  };
  return (
    <button
      {...p}
      disabled={p.disabled || carregando}
      className={`inline-flex items-center gap-2 border px-3 py-[7px] text-[13px] font-semibold disabled:opacity-40 disabled:cursor-not-allowed ${estilos[variante]} ${className}`}
    >
      {carregando && <Loader2 size={14} className="animate-spin" />}
      {children}
    </button>
  );
}

export function SeloSituacao({ situacao }: { situacao: Situacao }) {
  const s = SITUACAO[situacao];
  return (
    <span className="inline-flex items-center gap-[6px] whitespace-nowrap">
      <span className="inline-block h-[9px] w-[9px] shrink-0" style={{ background: s.cor }} />
      {s.rotulo}
    </span>
  );
}

export function Score({ valor, grande }: { valor: number; grande?: boolean }) {
  if (grande) {
    return (
      <div>
        <div className="cond num text-[88px] font-bold leading-[0.85]" style={{ color: corScore(valor) }}>{valor}</div>
        <div className="mt-2 h-[3px] w-full bg-linha">
          <div className="h-full" style={{ width: `${valor}%`, background: corScore(valor) }} />
        </div>
      </div>
    );
  }
  return (
    <span className="num inline-flex items-center gap-2">
      <span className="w-7 text-right font-semibold" style={{ color: corScore(valor) }}>{valor}</span>
      <span className="h-[3px] w-10 bg-linha">
        <span className="block h-full" style={{ width: `${valor}%`, background: corScore(valor) }} />
      </span>
    </span>
  );
}

export function Carregando({ texto = "Carregando…" }: { texto?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-cinza">
      <Loader2 size={16} className="animate-spin" /> {texto}
    </div>
  );
}

export function Erro({ erro, tentar }: { erro: unknown; tentar?: () => void }) {
  const msg = erro instanceof ApiError ? erro.erro.mensagem : erro instanceof Error ? erro.message : "Erro inesperado.";
  return (
    <div className="flex items-start gap-3 border border-critico p-4">
      <AlertTriangle size={18} className="mt-[1px] text-critico" />
      <div className="flex-1">
        <div className="font-semibold">Não foi possível carregar</div>
        <div className="text-cinza">{msg}</div>
      </div>
      {tentar && <Botao onClick={tentar}>Tentar de novo</Botao>}
    </div>
  );
}

export function Vazio({ titulo, children }: { titulo: string; children?: ReactNode }) {
  return (
    <div className="border border-dashed border-linha px-6 py-12">
      <div className="text-[18px] font-semibold">{titulo}</div>
      {children && <div className="mt-2 text-cinza">{children}</div>}
    </div>
  );
}

export function Secao({ titulo, acao, children, className = "" }: { titulo: string; acao?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`border-t border-tinta pt-3 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <h2 className="text-[13px] font-bold uppercase tracking-[0.06em]">{titulo}</h2>
        {acao}
      </div>
      {children}
    </section>
  );
}

export function Paginacao({ pagina, total, porPagina, onPagina }: { pagina: number; total: number; porPagina: number; onPagina: (p: number) => void }) {
  const ultima = Math.max(1, Math.ceil(total / porPagina));
  const de = total ? (pagina - 1) * porPagina + 1 : 0;
  const ate = Math.min(total, pagina * porPagina);
  return (
    <div className="flex items-center justify-between gap-4 border-t border-linha pt-3 text-[13px]">
      <span className="num text-cinza">{de.toLocaleString("pt-BR")}–{ate.toLocaleString("pt-BR")} de {total.toLocaleString("pt-BR")}</span>
      <div className="flex items-center gap-2">
        <Botao variante="fantasma" disabled={pagina <= 1} onClick={() => onPagina(pagina - 1)}>Anterior</Botao>
        <span className="num">{pagina} / {ultima}</span>
        <Botao variante="fantasma" disabled={pagina >= ultima} onClick={() => onPagina(pagina + 1)}>Próxima</Botao>
      </div>
    </div>
  );
}

export function Campo({ rotulo, erro, children, obrigatorio, dica }: { rotulo: string; erro?: string; children: ReactNode; obrigatorio?: boolean; dica?: string }) {
  return (
    <label className="block">
      <span className="rotulo">{rotulo}{obrigatorio && <span className="text-acento"> *</span>}</span>
      {children}
      {dica && !erro && <span className="mt-1 block text-[12px] text-cinza">{dica}</span>}
      {erro && <span className="mt-1 block text-[12px] text-critico">{erro}</span>}
    </label>
  );
}

export function Avisos({ avisos }: { avisos: { codigo: string; mensagem: string }[] }) {
  if (!avisos.length) return null;
  return (
    <ul className="space-y-1">
      {avisos.map((a, i) => (
        <li key={i} className="flex items-start gap-2 border-l-[3px] border-atencao bg-neutro px-3 py-2 text-[13px]">
          {a.mensagem}
        </li>
      ))}
    </ul>
  );
}
