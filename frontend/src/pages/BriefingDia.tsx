import { useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { Botao, Carregando, Erro } from "../components/ui";
import { usePerfil } from "../lib/perfil";
import AvisoTreino from "../preditivo/AvisoTreino";
import GavetaCartao from "../preditivo/GavetaCartao";
import { useBriefing, useGerarBriefing } from "../preditivo/api";

/** Briefing diário (C4): gerado às 6 h com o que o gestor precisa saber no dia. */
export default function BriefingDia() {
  const b = useBriefing();
  const gerar = useGerarBriefing();
  const { perfil } = usePerfil();
  const [cartao, setCartao] = useState<number | null>(null);
  const baixar = () => {
    if (!b.data) return;
    const url = URL.createObjectURL(new Blob([b.data.markdown], { type: "text/markdown;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `briefing-${b.data.data}.md` });
    a.click();
    URL.revokeObjectURL(url);
  };
  if (b.isLoading) return <Carregando texto="Montando o briefing…" />;
  if (!b.data) return <Erro erro={b.error} />;
  const d = b.data;
  return (
    <div className="mx-auto max-w-[860px] space-y-4">
      <AvisoTreino />
      <div className="flex flex-wrap items-end justify-between gap-3 border-b-2 border-tinta pb-3">
        <div>
          <div className="text-[12px] font-semibold uppercase tracking-[0.06em] text-cinza">Briefing diário · 6 h</div>
          <h1 className="text-[26px] font-bold tracking-[-0.02em]">{d.titulo}</h1>
          <p className="text-[12px] text-cinza">Gerado em {new Date(d.gerado_em).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} ({d.gerado_por})</p>
        </div>
        <div className="flex gap-2">
          <Botao onClick={baixar}><Download size={14} /> Markdown</Botao>
          {perfil.perfil === "gestor" && <Botao carregando={gerar.isPending} onClick={() => gerar.mutate()}><RefreshCw size={14} /> Atualizar agora</Botao>}
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
