import { useState } from "react";
import { Link } from "react-router-dom";
import { ShieldCheck, Wrench, X } from "lucide-react";
import { ApiError } from "../api/client";
import { Botao, Carregando, Erro } from "../components/ui";
import CartaoPrevisao, { SeloNivel } from "../preditivo/CartaoPrevisao";
import { useCartao, useOrdensLote, useRanking } from "../preditivo/api";
import { COR_NIVEL, ROTULO_NIVEL, pct } from "../preditivo/formato";

const TIPOS = [["", "Todos os tipos"], ["CAM", "Câmeras"], ["RAD", "Radares"], ["TOT", "Totens"], ["BAL", "Balanças"],
  ["CAN", "Cancelas"], ["PAT", "Patinetes"], ["VAF", "Veículos de fiscalização"], ["VTR", "Táxis e escolares"],
  ["MOT", "Motos"], ["VIA", "Viaturas"]];
const REGIOES = ["", "Centro", "Leste", "Norte", "Oeste", "Sul"];
const NIVEIS = ["MUITO_ALTO", "ALTO", "MODERADO", "BAIXO"];

function Gaveta({ id, fechar }: { id: number; fechar: () => void }) {
  const c = useCartao(id);
  return (
    <div className="fixed inset-y-0 right-0 z-40 w-full max-w-[460px] overflow-y-auto border-l border-tinta bg-papel p-3 shadow-xl">
      <button onClick={fechar} className="mb-2 inline-flex items-center gap-1 text-[13px] font-semibold"><X size={14} /> Fechar</button>
      {c.isLoading ? <Carregando /> : c.data ? <CartaoPrevisao c={c.data} /> : <Erro erro={c.error} />}
    </div>
  );
}

export default function EquipamentosRisco() {
  const [janela, setJanela] = useState<7 | 30>(7);
  const [niveis, setNiveis] = useState<string[]>(["MUITO_ALTO", "ALTO"]);
  const [tipo, setTipo] = useState("");
  const [regiao, setRegiao] = useState("");
  const [busca, setBusca] = useState("");
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [aberto, setAberto] = useState<number | null>(null);
  const r = useRanking({ janela, nivel: niveis, tipo: tipo || undefined, regiao: regiao || undefined, busca: busca || undefined, limite: 300 });
  const lote = useOrdensLote();
  const itens = r.data?.itens ?? [];
  const elegiveis = itens.filter((x) => !x.decisao && !x.os_aberta);

  const alternar = (n: string) => setNiveis(niveis.includes(n) ? niveis.filter((x) => x !== n) : [...niveis, n]);
  const marcar = (id: number) => { const s = new Set(sel); if (s.has(id)) s.delete(id); else s.add(id); setSel(s); };

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-bold tracking-[-0.02em]">Equipamentos em risco</h1>
          <p className="text-cinza">Probabilidade de cada equipamento em operação entrar em mau funcionamento. Dados sintéticos.</p>
        </div>
        <div className="flex border border-tinta text-[13px] font-semibold">
          {([7, 30] as const).map((j) => (
            <button key={j} onClick={() => { setJanela(j); setSel(new Set()); }} className={`px-3 py-1 ${janela === j ? "bg-tinta text-papel" : ""}`}>
              Próximos {j} dias
            </button>
          ))}
        </div>
      </div>

      {r.data && (
        <div className="mt-3 flex items-start gap-2 border border-linha bg-neutro p-2 text-[13px]">
          <ShieldCheck size={15} className="mt-[2px] shrink-0" /><span>{r.data.selo.texto}.</span>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {NIVEIS.map((n) => (
          <button key={n} onClick={() => alternar(n)}
            className={`border px-2 py-1 text-[12px] font-semibold ${niveis.includes(n) ? "border-tinta" : "border-linha text-cinza"}`}>
            <span className="mr-1 inline-block h-[8px] w-[8px]" style={{ background: COR_NIVEL[n] }} />
            {ROTULO_NIVEL[n]} <span className="num">({(r.data?.totais_por_nivel[n] ?? 0).toLocaleString("pt-BR")})</span>
          </button>
        ))}
        <select className="campo w-auto" value={tipo} onChange={(e) => setTipo(e.target.value)}>
          {TIPOS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
        <select className="campo w-auto" value={regiao} onChange={(e) => setRegiao(e.target.value)}>
          {REGIOES.map((v) => <option key={v} value={v}>{v || "Todas as regiões"}</option>)}
        </select>
        <input className="campo w-[160px]" placeholder="Código (ex.: RAD-0042)" value={busca} onChange={(e) => setBusca(e.target.value)} />
        <Botao variante="primario" className="ml-auto" disabled={!sel.size} carregando={lote.isPending}
          onClick={() => lote.mutate([...sel], { onSuccess: () => setSel(new Set()) })}>
          <Wrench size={14} /> Abrir OS preventivas ({sel.size})
        </Botao>
      </div>
      {lote.data && (
        <p className="mt-2 text-[13px]">
          {lote.data.abertas.length} ordem(ns) de serviço aberta(s){lote.data.puladas.length ? `; ${lote.data.puladas.length} pulada(s) (já decididas)` : ""}.
        </p>
      )}
      {lote.error instanceof ApiError && <p className="mt-2 text-critico">{lote.error.erro.mensagem}</p>}

      {r.isLoading ? <Carregando /> : r.error ? <Erro erro={r.error} /> : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-tinta text-left text-[11px] uppercase tracking-[0.06em] text-cinza">
                <th className="py-2 pr-2">
                  <input type="checkbox" aria-label="Selecionar todos"
                    checked={elegiveis.length > 0 && elegiveis.every((x) => sel.has(x.previsao_id))}
                    onChange={(e) => setSel(e.target.checked ? new Set(elegiveis.map((x) => x.previsao_id)) : new Set())} />
                </th>
                <th className="pr-3">Equipamento</th><th className="pr-3">Região</th><th className="pr-3">Probabilidade</th>
                <th className="pr-3">Nível</th><th className="pr-3">Principais motivos</th><th className="pr-3">Situação</th>
              </tr>
            </thead>
            <tbody>
              {itens.map((x) => (
                <tr key={x.previsao_id} className="cursor-pointer border-b border-linha align-top hover:bg-neutro" onClick={() => setAberto(x.previsao_id)}>
                  <td className="py-2 pr-2" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" disabled={!!x.decisao || x.os_aberta} checked={sel.has(x.previsao_id)} onChange={() => marcar(x.previsao_id)}
                      aria-label={`Selecionar ${x.codigo}`} />
                  </td>
                  <td className="pr-3">
                    <Link to={`/equipamentos/${x.equipamento_id}`} onClick={(e) => e.stopPropagation()} className="font-semibold underline">{x.codigo}</Link>
                    <div className="text-[12px] text-cinza">{x.modelo} ({x.marca})</div>
                  </td>
                  <td className="pr-3">{x.regiao ?? "—"}</td>
                  <td className="num pr-3">
                    <b>{pct(x.probabilidade)}</b> <span className="text-[11px] text-cinza">({pct(x.faixa[0])} a {pct(x.faixa[1])})</span>
                    <div className="mt-1 h-[4px] w-[100px] bg-linha"><div className="h-full" style={{ width: `${Math.min(100, x.probabilidade * 200)}%`, background: COR_NIVEL[x.nivel] }} /></div>
                  </td>
                  <td className="pr-3"><SeloNivel nivel={x.nivel} /></td>
                  <td className="pr-3 text-[12px]">{x.fatores.map((f) => f.descricao).join(" · ")}</td>
                  <td className="pr-3 text-[12px]">
                    {x.os_aberta ? "OS aberta" : x.decisao ? `Recomendação ${x.decisao}` : "Sem decisão"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {itens.length === 0 && <p className="py-6 text-cinza">Nenhum equipamento com esses filtros.</p>}
        </div>
      )}
      {aberto != null && <Gaveta id={aberto} fechar={() => setAberto(null)} />}
    </div>
  );
}
