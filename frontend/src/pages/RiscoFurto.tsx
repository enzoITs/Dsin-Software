import { useState } from "react";
import { Link } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { Carregando, Erro } from "../components/ui";
import { SeloNivel } from "../preditivo/CartaoPrevisao";
import AvisoTreino from "../preditivo/AvisoTreino";
import GavetaCartao from "../preditivo/GavetaCartao";
import { useRiscoFurto } from "../preditivo/api";
import { COR_NIVEL, ROTULO_NIVEL, num, pct } from "../preditivo/formato";

const TIPOS = [["", "Todos os tipos"], ["CAM", "Câmeras"], ["RAD", "Radares"], ["TOT", "Totens"], ["BAL", "Balanças"],
  ["CAN", "Cancelas"], ["PAT", "Patinetes"]];
const REGIOES = ["", "Centro", "Leste", "Norte", "Oeste", "Sul"];
const NIVEIS = ["MUITO_ALTO", "ALTO", "MODERADO", "BAIXO"];

export default function RiscoFurto() {
  const [niveis, setNiveis] = useState<string[]>(["MUITO_ALTO", "ALTO"]);
  const [tipo, setTipo] = useState("");
  const [regiao, setRegiao] = useState("");
  const [busca, setBusca] = useState("");
  const [aberto, setAberto] = useState<number | null>(null);
  const r = useRiscoFurto({ nivel: niveis, tipo: tipo || undefined, regiao: regiao || undefined, busca: busca || undefined, limite: 300 });
  const itens = r.data?.itens ?? [];
  const alternar = (n: string) => setNiveis(niveis.includes(n) ? niveis.filter((x) => x !== n) : [...niveis, n]);

  return (
    <div>
      <h1 className="text-[26px] font-bold tracking-[-0.02em]">Risco de furto de equipamentos</h1>
      <p className="text-cinza">Probabilidade de cada equipamento ser furtado nos próximos 30 dias. {r.data?.aviso ?? ""} Dados sintéticos.</p>
      {r.data && (
        <div className="mt-3 flex items-start gap-2 border border-linha bg-neutro p-2 text-[13px]">
          <ShieldCheck size={15} className="mt-[2px] shrink-0" /><span>{r.data.selo.texto}.</span>
        </div>
      )}
      <div className="mt-3"><AvisoTreino /></div>
      {r.data && (
        <div className="mt-3">
          <h2 className="text-[11px] font-bold uppercase tracking-[0.08em] text-cinza">
            Onde se esperam mais furtos ({num(r.data.furtos_esperados)} na cidade em 30 dias)
          </h2>
          <div className="mt-1 flex flex-wrap gap-2">
            {r.data.por_bairro.slice(0, 6).map((b) => (
              <button key={b.bairro} onClick={() => setBusca(b.bairro)} className="border border-linha px-2 py-1 text-left text-[12px] hover:border-tinta">
                <b>{b.bairro}</b> <span className="text-cinza">({b.regiao})</span>
                <span className="block num">{num(b.esperados)} esperados · {b.alto} em risco alto</span>
              </button>
            ))}
          </div>
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
        <input className="campo w-[200px]" placeholder="Código ou bairro" value={busca} onChange={(e) => setBusca(e.target.value)} />
        <Link to="/previsao/expansao" className="ml-auto text-[13px] font-semibold underline">Onde pôr câmeras novas →</Link>
      </div>
      {r.isLoading ? <Carregando /> : r.error ? <Erro erro={r.error} /> : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-tinta text-left text-[11px] uppercase tracking-[0.06em] text-cinza">
                <th className="py-2 pr-3">Equipamento</th><th className="pr-3">Local</th><th className="pr-3">Probabilidade</th>
                <th className="pr-3">Nível</th><th className="pr-3">Principais motivos</th><th className="pr-3">Câmera mais próxima</th>
              </tr>
            </thead>
            <tbody>
              {itens.map((x) => (
                <tr key={x.previsao_id} className="cursor-pointer border-b border-linha align-top hover:bg-neutro" onClick={() => setAberto(x.previsao_id)}>
                  <td className="py-2 pr-3">
                    <Link to={`/equipamentos/${x.equipamento_id}`} onClick={(e) => e.stopPropagation()} className="font-semibold underline">{x.codigo}</Link>
                  </td>
                  <td className="pr-3">{x.bairro ?? "—"} <span className="text-[12px] text-cinza">({x.regiao ?? "—"})</span></td>
                  <td className="num pr-3"><b>{pct(x.probabilidade, 1)}</b> <span className="text-[11px] text-cinza">({num(x.vezes_a_media, 0)}× a média)</span></td>
                  <td className="pr-3"><SeloNivel nivel={x.nivel} /></td>
                  <td className="pr-3 text-[12px]">{x.fatores.map((f) => f.descricao).join(" · ")}</td>
                  <td className="num pr-3 text-[12px]">{x.dist_camera_m >= 5000 ? "nenhuma por perto" : `${x.dist_camera_m} m`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {itens.length === 0 && <p className="py-6 text-cinza">Nenhum equipamento com esses filtros.</p>}
        </div>
      )}
      {aberto != null && <GavetaCartao id={aberto} fechar={() => setAberto(null)} />}
    </div>
  );
}
