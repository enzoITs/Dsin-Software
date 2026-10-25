import { useEffect, useState } from "react";
import { Loader2, MapPin, X } from "lucide-react";
import { ApiError } from "../api/client";
import { useCategoriasOcorrencia, useRegistrarOcorrencia } from "./api";
import { COR_OCORRENCIA } from "./Mapa";
import { useTela } from "./store";

const GRAVIDADES = [
  [1, "Leve"],
  [2, "Moderada"],
  [3, "Séria"],
  [4, "Grave"],
] as const;

/** Painel sobre o mapa: clique no ponto, escolha a categoria e a gravidade, registre.
 * As ocorrências alimentam as previsões da Parte 3. */
export default function RegistrarOcorrencia() {
  const ponto = useTela((s) => s.pontoOcorrencia);
  const fechar = () => useTela.getState().setRegistrando(false);
  const cats = useCategoriasOcorrencia();
  const reg = useRegistrarOcorrencia();
  const [categoria, setCategoria] = useState("");
  const [gravidade, setGravidade] = useState<number | null>(null);
  const [descricao, setDescricao] = useState("");
  const [feito, setFeito] = useState<string | null>(null);

  const cat = cats.data?.find((c) => c.codigo === categoria);
  useEffect(() => { if (cat) setGravidade(cat.gravidade_padrao); }, [cat]);

  const enviar = () => {
    if (!ponto || !categoria || !gravidade) return;
    reg.mutate(
      { categoria, gravidade, lon: ponto[0], lat: ponto[1], descricao: descricao.trim() || undefined },
      {
        onSuccess: (o) => {
          setFeito(`${o.categoria_nome} registrada${o.bairro ? ` em ${o.bairro}` : ""}${o.regiao ? ` (${o.regiao})` : ""}.`);
          setDescricao("");
          useTela.getState().setPontoOcorrencia(null);
        },
      },
    );
  };

  return (
    <div className="absolute left-1/2 top-2 z-20 w-[min(380px,calc(100%-16px))] -translate-x-1/2 border border-tinta bg-papel p-3 shadow-[0_8px_28px_rgba(0,0,0,0.2)]" role="dialog" aria-label="Registrar ocorrência">
      <div className="mb-2 flex items-center justify-between">
        <span className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-[0.06em]">
          <span className="h-[10px] w-[10px] rounded-full" style={{ background: COR_OCORRENCIA }} /> Registrar ocorrência
        </span>
        <button onClick={fechar} aria-label="Fechar" className="text-cinza hover:text-tinta"><X size={16} /></button>
      </div>
      {!ponto ? (
        <p className="flex items-center gap-2 text-[13px]"><MapPin size={15} /> Clique no mapa onde aconteceu. <span className="text-cinza">Esc cancela.</span></p>
      ) : (
        <div className="space-y-2">
          <p className="text-[11px] text-cinza">Ponto: {ponto[1].toFixed(5)}, {ponto[0].toFixed(5)} · clique em outro lugar para mudar</p>
          <select className="campo" value={categoria} onChange={(e) => setCategoria(e.target.value)} aria-label="Categoria" autoFocus>
            <option value="">Categoria…</option>
            {(cats.data ?? []).map((c) => <option key={c.codigo} value={c.codigo}>{c.nome}</option>)}
          </select>
          <div className="flex gap-1" role="radiogroup" aria-label="Gravidade">
            {GRAVIDADES.map(([g, r]) => (
              <button
                key={g} role="radio" aria-checked={gravidade === g} onClick={() => setGravidade(g)}
                className={`flex-1 border px-1 py-[5px] text-[12px] font-semibold ${gravidade === g ? "border-tinta bg-tinta text-papel" : "border-linha hover:border-tinta"}`}
              >
                {g} · {r}
              </button>
            ))}
          </div>
          <input className="campo" placeholder="Descrição (opcional)" maxLength={500} value={descricao} onChange={(e) => setDescricao(e.target.value)} />
          <button
            className="flex w-full items-center justify-center gap-2 border px-3 py-2 text-[13px] font-semibold text-white disabled:opacity-50"
            style={{ background: COR_OCORRENCIA, borderColor: COR_OCORRENCIA }}
            disabled={!categoria || !gravidade || reg.isPending} onClick={enviar}
          >
            {reg.isPending && <Loader2 size={14} className="animate-spin" />} Registrar
          </button>
        </div>
      )}
      {reg.isError && <p className="mt-2 text-[12px] text-critico">{reg.error instanceof ApiError ? reg.error.erro.mensagem : "Não foi possível registrar."}</p>}
      {feito && !reg.isError && <p className="mt-2 text-[12px]">{feito} Clique no mapa para registrar outra.</p>}
    </div>
  );
}
