import { useEffect, useRef, useState } from "react";
import { Bot, Send, Sparkles, User } from "lucide-react";
import { ApiError } from "../api/client";
import { Botao } from "../components/ui";
import GavetaCartao from "../preditivo/GavetaCartao";
import TextoRico from "../preditivo/TextoRico";
import { usePerguntar, usePerguntasProntas } from "../preditivo/api";
import type { RespostaCopiloto } from "../preditivo/tipos";

interface Msg { papel: "user" | "assistant"; texto: string; resposta?: RespostaCopiloto }

const NOME_FERRAMENTA: Record<string, string> = {
  risco_por_regiao: "risco por região", ocorrencias_previstas: "ocorrências previstas", equipamentos_em_risco: "equipamentos em risco",
  reforcos_de_equipes: "reforços de equipes", anomalias_abertas: "anomalias", alertas_preventivos: "alertas preventivos",
  qualidade_dos_modelos: "qualidade dos modelos", contexto_do_dia: "contexto do dia", simular_cenario: "simulação de cenário",
};

/** Copiloto (C3): perguntas em português, respondidas com os dados do sistema; com ou sem IA. */
export default function Copiloto() {
  const prontas = usePerguntasProntas();
  const perguntar = usePerguntar();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [texto, setTexto] = useState("");
  const [cartao, setCartao] = useState<number | null>(null);
  const fim = useRef<HTMLDivElement>(null);
  useEffect(() => { fim.current?.scrollIntoView?.({ behavior: "smooth" }); }, [msgs, perguntar.isPending]);
  const ia = prontas.data?.ia_disponivel;

  const enviar = (pergunta: string, pronta?: string) => {
    if (!pergunta.trim() || perguntar.isPending) return;
    const historico = msgs.map((m) => ({ papel: m.papel, texto: m.texto }));
    setMsgs((m) => [...m, { papel: "user", texto: pergunta }]);
    setTexto("");
    perguntar.mutate({ pergunta, pronta, historico }, {
      onSuccess: (r) => setMsgs((m) => [...m, { papel: "assistant", texto: r.resposta, resposta: r }]),
      onError: (e) => setMsgs((m) => [...m, { papel: "assistant", texto: e instanceof ApiError ? e.erro.mensagem : "Não foi possível responder agora." }]),
    });
  };

  return (
    <div className="mx-auto flex max-w-[900px] flex-col gap-4">
      <div>
        <h1 className="text-[26px] font-bold tracking-[-0.02em]">Copiloto</h1>
        <p className="text-cinza">
          Pergunte sobre as previsões: onde vai ser pior, o que mandar para manutenção, onde reforçar, e se chover. As respostas usam só
          os dados do sistema e apontam os cartões de previsão. O copiloto recomenda; quem decide é você.
        </p>
        <p className="mt-1 inline-flex items-center gap-1 text-[12px] font-semibold" style={{ color: ia ? "#5b3fa6" : "#6b6b6b" }}>
          <Sparkles size={13} /> {ia === undefined ? "" : ia ? "IA ligada: pergunte livremente" : "Sem IA (sem chave da API): use as perguntas prontas"}
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {prontas.data?.perguntas.map((p) => (
          <button key={p.id} disabled={perguntar.isPending} onClick={() => enviar(p.texto, p.id)}
            className="border border-linha bg-papel px-3 py-1 text-left text-[13px] hover:border-tinta disabled:opacity-50">{p.texto}</button>
        ))}
      </div>

      <div className="min-h-[300px] space-y-3 border border-linha bg-neutro p-3">
        {msgs.length === 0 && <p className="p-4 text-center text-[13px] text-cinza">Escolha uma pergunta pronta ou escreva a sua.</p>}
        {msgs.map((m, i) => (
          <div key={i} className={`flex gap-2 ${m.papel === "user" ? "justify-end" : ""}`}>
            {m.papel === "assistant" && <Bot size={18} className="mt-1 shrink-0 text-[#5b3fa6]" />}
            <div className={`max-w-[85%] px-3 py-2 text-[14px] ${m.papel === "user" ? "bg-tinta text-papel" : "border border-linha bg-papel"}`}>
              {m.papel === "user" ? m.texto : <TextoRico texto={m.texto} abrir={setCartao} />}
              {m.resposta && (
                <p className="mt-2 border-t border-linha pt-1 text-[11px] text-cinza">
                  {m.resposta.modo === "ia" ? "Respondido pela IA" : `Sem IA (${m.resposta.motivo})`}
                  {m.resposta.ferramentas.length > 0 && ` · consultou: ${[...new Set(m.resposta.ferramentas.map((f) => NOME_FERRAMENTA[f.nome] ?? f.nome))].join(", ")}`}
                  {" · dados sintéticos"}
                </p>
              )}
            </div>
            {m.papel === "user" && <User size={18} className="mt-1 shrink-0" />}
          </div>
        ))}
        {perguntar.isPending && <p className="text-[13px] text-cinza">Consultando as previsões…</p>}
        <div ref={fim} />
      </div>

      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); enviar(texto); }}>
        <input className="campo" placeholder={ia ? "Ex.: o Centro vai precisar de reforço sexta à noite?" : "Ex.: onde o risco vai ser maior?"}
          value={texto} onChange={(e) => setTexto(e.target.value)} maxLength={600} aria-label="Pergunta" />
        <Botao variante="primario" type="submit" disabled={!texto.trim()} carregando={perguntar.isPending}><Send size={14} /> Perguntar</Botao>
      </form>
      {cartao != null && <GavetaCartao id={cartao} fechar={() => setCartao(null)} />}
    </div>
  );
}
