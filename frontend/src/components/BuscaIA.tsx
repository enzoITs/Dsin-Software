import { useState } from "react";
import { Sparkles } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useStatusApi } from "../api/hooks";
import { Botao } from "./ui";

interface RespostaBusca { params: Record<string, string | string[]>; interpretacao: string[] }

/** Busca em linguagem natural: a frase vira filtros estruturados que o usuário vê e pode remover. */
export function BuscaIA({ onFiltros }: { onFiltros: (params: Record<string, string | string[]>) => void }) {
  const ia = useStatusApi().data?.ia_disponivel;
  const [aberto, setAberto] = useState(false);
  const [texto, setTexto] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [interp, setInterp] = useState<string[]>([]);

  async function buscar() {
    if (!texto.trim()) return;
    setCarregando(true); setErro(null);
    try {
      const r = await api<RespostaBusca>("/busca", { method: "POST", body: { texto } });
      setInterp(r.interpretacao);
      onFiltros(r.params);
    } catch (e) {
      setErro(e instanceof ApiError ? e.erro.mensagem : "Falha na busca.");
    } finally {
      setCarregando(false);
    }
  }

  if (!aberto) {
    return (
      <Botao onClick={() => setAberto(true)} disabled={ia === false} title={ia === false ? "IA indisponível: configure ANTHROPIC_API_KEY. A busca por filtros continua normal." : undefined}>
        <Sparkles size={14} /> Perguntar em linguagem natural
      </Botao>
    );
  }
  return (
    <div className="w-full border border-tinta p-3">
      <div className="flex flex-wrap gap-2">
        <input
          autoFocus
          className="campo flex-1"
          placeholder="Ex.: câmeras sem visão noturna no Centro com manutenção vencendo"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && buscar()}
        />
        <Botao variante="primario" carregando={carregando} onClick={buscar}>Buscar</Botao>
        <Botao variante="fantasma" onClick={() => { setAberto(false); setInterp([]); setErro(null); }}>Fechar</Botao>
      </div>
      {erro && <div className="mt-2 text-[13px] text-critico">{erro}</div>}
      {interp.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
          <span className="text-cinza">Entendido como:</span>
          {interp.map((i) => <span key={i} className="border border-linha px-2 py-[2px]">{i}</span>)}
        </div>
      )}
    </div>
  );
}
