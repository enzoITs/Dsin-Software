import { useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { Botao, Carregando, Erro } from "../components/ui";
import { usePerfil } from "../lib/perfil";
import AvisoTreino from "../preditivo/AvisoTreino";
import GavetaCartao from "../preditivo/GavetaCartao";
import { useBriefing, useGerarBriefing, useRelatorioSemanal } from "../preditivo/api";

/** Briefing diário (C4), gerado às 6 h, e relatório semanal (X5), no mesmo formato. */
export default function BriefingDia() {
  const [aba, setAba] = useState<"dia" | "semana">("dia");
  const diario = useBriefing();
  const semanal = useRelatorioSemanal(aba === "semana");
  const b = aba === "dia" ? diario : semanal;
  const gerar = useGerarBriefing();
  const { perfil } = usePerfil();
  const [cartao, setCartao] = useState<number | null>(null);
  const baixar = () => {
    if (!b.data) return;
    const url = URL.createObjectURL(new Blob([b.data.markdown], { type: "text/markdown;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `${aba === "dia" ? "briefing" : "relatorio-semanal"}-${b.data.data}.md` });
    a.click();
    URL.revokeObjectURL(url);
  };
  const abas = (
    <div className="flex gap-4 border-b border-linha text-[14px] font-semibold">
      <button onClick={() => setAba("dia")} className={`pb-2 ${aba === "dia" ? "border-b-2 border-tinta" : "text-cinza"}`}>Briefing do dia</button>
      <button onClick={() => setAba("semana")} className={`pb-2 ${aba === "semana" ? "border-b-2 border-tinta" : "text-cinza"}`}>Relatório semanal</button>
    </div>
  );
  if (b.isLoading) return <div className="mx-auto max-w-[860px]">{abas}<Carregando texto={aba === "dia" ? "Montando o briefing…" : "Montando o relatório da semana…"} /></div>;
  if (!b.data) return <div className="mx-auto max-w-[860px]">{abas}<Erro erro={b.error} /></div>;
  const d = b.data;
  return (
    <div className="mx-auto max-w-[860px] space-y-4">
      {abas}
      <AvisoTreino />
      <div className="flex flex-wrap items-end justify-between gap-3 border-b-2 border-tinta pb-3">
        <div>
          <div className="text-[12px] font-semibold uppercase tracking-[0.06em] text-cinza">{aba === "dia" ? "Briefing diário · 6 h" : "Relatório semanal"}</div>
          <h1 className="text-[26px] font-bold tracking-[-0.02em]">{d.titulo}</h1>
          <p className="text-[12px] text-cinza">Gerado em {new Date(d.gerado_em).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} ({d.gerado_por})</p>
        </div>
        <div className="flex gap-2">
          <Botao onClick={baixar}><Download size={14} /> Markdown</Botao>
          {aba === "dia" && perfil.perfil === "gestor" && <Botao carregando={gerar.isPending} onClick={() => gerar.mutate()}><RefreshCw size={14} /> Atualizar agora</Botao>}
        </div>
      </div>
      {d.secoes.map((s) => (
        <section key={s.id} className={s.id === "resumo" ? "border-l-[4px] border-acento bg-neutro px-4 py-3" : ""}>
          <h2 className="mb-2 text-[12px] font-bold uppercase tracking-[0.07em]">{s.titulo}</h2>
          <ul className={`space-y-1 text-[14px] ${s.id === "resumo" ? "font-semibold" : "list-disc pl-5"}`}>
            {s.itens.map((i, k) => (
              <li key={k}>
                {i.texto}
                {i.previsao_id && (
                  <button onClick={() => setCartao(i.previsao_id)} className="ml-2 border border-linha px-1 text-[11px] font-semibold text-[#5b3fa6] hover:border-[#5b3fa6]">
                    cartão
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
      <p className="border-t border-linha pt-2 text-[12px] italic text-cinza">{d.rodape}</p>
      {cartao != null && <GavetaCartao id={cartao} fechar={() => setCartao(null)} />}
    </div>
  );
}
