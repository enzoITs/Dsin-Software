import { useState } from "react";
import { Link } from "react-router-dom";
import { Carregando, Erro } from "../components/ui";
import AvisoTreino from "../preditivo/AvisoTreino";
import { useFimDeVida } from "../preditivo/api";
import { num, pct } from "../preditivo/formato";

const TIPOS = [["", "Todos os tipos"], ["CAM", "Câmeras"], ["RAD", "Radares"], ["TOT", "Totens"], ["BAL", "Balanças"], ["CAN", "Cancelas"]];
const REGIOES = ["", "Centro", "Leste", "Norte", "Oeste", "Sul"];

export default function FimDeVida() {
  const [tipo, setTipo] = useState("");
  const [regiao, setRegiao] = useState("");
  const r = useFimDeVida({ tipo: tipo || undefined, regiao: regiao || undefined, limite: 200 });
  const d = r.data;
  const rs = d?.resumo;
  return (
    <div>
      <h1 className="text-[26px] font-bold tracking-[-0.02em]">Fim de vida útil</h1>
      <p className="text-cinza">{d?.como_ajuda ?? "Quais equipamentos vale trocar em vez de continuar consertando"}. Dados sintéticos.</p>
      <div className="mt-3"><AvisoTreino /></div>
      {rs && (
        <div className="mt-3 grid gap-3 md:grid-cols-4">
          <div className="border border-linha p-3"><div className="num text-[24px] font-bold">{rs.recomendados.toLocaleString("pt-BR")}</div>
            <div className="text-[12px] text-cinza">para trocar, de {rs.avaliados.toLocaleString("pt-BR")} fixos em operação</div></div>
          <div className="border border-linha p-3"><div className="num text-[24px] font-bold">{rs.passou_vida_util.toLocaleString("pt-BR")}</div>
            <div className="text-[12px] text-cinza">passaram da vida útil do tipo</div></div>
          <div className="border border-linha p-3"><div className="num text-[24px] font-bold">{rs.dias_parado_total.toLocaleString("pt-BR")}</div>
            <div className="text-[12px] text-cinza">dias parados no último ano, somados</div></div>
          <div className="border border-linha p-3"><div className="num text-[24px] font-bold">{num(rs.falhas_evitaveis_mes, 0)}</div>
            <div className="text-[12px] text-cinza">falhas a menos por mês, se todos fossem trocados (modelo P1)</div></div>
        </div>
      )}
      {rs && rs.marcas.length > 0 && (
        <p className="mt-2 text-[13px]">
          Mais frequentes na lista: {rs.marcas.slice(0, 3).map((m) => `${m.marca} (${m.tipo}, ${m.n})`).join(" · ")}.
        </p>
      )}
      {d && <p className="mt-1 text-[12px] text-cinza">Critério: {d.criterio}.</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <select className="campo w-auto" value={tipo} onChange={(e) => setTipo(e.target.value)}>
          {TIPOS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
        <select className="campo w-auto" value={regiao} onChange={(e) => setRegiao(e.target.value)}>
          {REGIOES.map((v) => <option key={v} value={v}>{v || "Todas as regiões"}</option>)}
        </select>
      </div>
      {r.isLoading ? <Carregando texto="Avaliando a frota…" /> : r.error ? <Erro erro={r.error} /> : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-tinta text-left text-[11px] uppercase tracking-[0.06em] text-cinza">
                <th className="py-2 pr-3">Equipamento</th><th className="pr-3">Idade</th><th className="pr-3">Último ano</th>
                <th className="pr-3">Falhar em 30 dias</th><th className="pr-3">Por quê</th>
              </tr>
            </thead>
            <tbody>
              {d!.itens.map((x) => (
                <tr key={x.equipamento_id} className="border-b border-linha align-top">
                  <td className="py-2 pr-3">
                    <Link to={`/equipamentos/${x.equipamento_id}`} className="font-semibold underline">{x.codigo}</Link>
                    <div className="text-[12px] text-cinza">{x.modelo} ({x.marca}) · {x.regiao ?? "—"}</div>
                  </td>
                  <td className="num pr-3">{num(x.idade_anos)} anos
                    <div className="mt-1 h-[4px] w-[90px] bg-linha"><div className="h-full" style={{ width: `${Math.min(100, x.uso_vida_pct)}%`, background: x.uso_vida_pct >= 100 ? "#d62828" : "#d99a00" }} /></div>
                    <div className="text-[11px] text-cinza">{x.uso_vida_pct}% de {x.vida_util_anos} anos</div>
                  </td>
                  <td className="num pr-3">{x.falhas_ano} falhas<div className="text-[12px] text-cinza">{x.dias_parado_ano} dias parado</div></td>
                  <td className="num pr-3"><b>{pct(x.p30)}</b> <span className="text-cinza">→ {pct(x.p30_novo)} se novo</span></td>
                  <td className="pr-3 text-[12px]"><b>{x.motivo_principal}</b><div className="text-cinza">{x.motivos.join(" · ")}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
          {d!.itens.length === 0 && <p className="py-6 text-cinza">{d!.mensagem ?? "Nenhum equipamento com esses filtros."}</p>}
        </div>
      )}
    </div>
  );
}
