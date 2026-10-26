import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Check, X } from "lucide-react";
import { ApiError } from "../api/client";
import { Botao, Carregando, Erro } from "../components/ui";
import { SeloNivel } from "../preditivo/CartaoPrevisao";
import { useDecidirRecomendacao, usePlano, useRecalcularPlano } from "../preditivo/api";
import { num } from "../preditivo/formato";
import type { Plano, Recomendacao } from "../preditivo/tipos";
import { usePerfil } from "../lib/perfil";
import AvisoTreino from "../preditivo/AvisoTreino";

const REGIOES = ["Centro", "Leste", "Norte", "Oeste", "Sul"];

function Pendente({ r }: { r: Recomendacao }) {
  const decidir = useDecidirRecomendacao();
  const [motivo, setMotivo] = useState("");
  const [rejeitando, setRejeitando] = useState(false);
  return (
    <li className="border border-linha p-3">
      <p className="text-[13px]">{r.texto}</p>
      {r.impacto_estimado?.falta_destino_antes != null && (
        <p className="mt-1 text-[12px] text-cinza">
          Falta no destino: {num(Number(r.impacto_estimado.falta_destino_antes), 0)} → {num(Number(r.impacto_estimado.falta_destino_depois), 0)} agentes-hora
        </p>
      )}
      {rejeitando && <textarea className="campo mt-2 h-[50px] text-[13px]" placeholder="Por que rejeitar?" value={motivo} onChange={(e) => setMotivo(e.target.value)} />}
      <div className="mt-2 flex gap-2">
        {rejeitando ? (
          <>
            <Botao variante="perigo" disabled={!motivo.trim()} carregando={decidir.isPending}
              onClick={() => decidir.mutate({ id: r.id, acao: "rejeitar", motivo })}>Confirmar rejeição</Botao>
            <Botao variante="fantasma" onClick={() => setRejeitando(false)}>Voltar</Botao>
          </>
        ) : (
          <>
            <Botao variante="primario" carregando={decidir.isPending} onClick={() => decidir.mutate({ id: r.id, acao: "aceitar" })}><Check size={14} /> Aceitar</Botao>
            <Botao variante="perigo" onClick={() => setRejeitando(true)}><X size={14} /> Rejeitar</Botao>
          </>
        )}
      </div>
      {decidir.error instanceof ApiError && <p className="mt-1 text-[12px] text-critico">{decidir.error.erro.mensagem}</p>}
    </li>
  );
}

export default function Planejamento() {
  const plano = usePlano();
  const recalc = useRecalcularPlano();
  const { perfil } = usePerfil();
  const [maxDesl, setMaxDesl] = useState(4);
  const [minReg, setMinReg] = useState(1);
  const [fixas, setFixas] = useState<string[]>([]);
  const [atual, setAtual] = useState<Plano | null>(null);
  useEffect(() => { if (plano.data && !atual) setAtual(plano.data); }, [plano.data, atual]);

  const rodar = (salvar: boolean) =>
    recalc.mutate({ max_deslocamentos: maxDesl, min_por_regiao: minReg, regioes_fixas: fixas, salvar }, { onSuccess: (p) => setAtual(p) });

  if (plano.isLoading) return <Carregando />;
  if (plano.error) return <div className="space-y-3"><AvisoTreino /><Erro erro={plano.error} /></div>;
  const p = atual ?? plano.data!;
  const pendentes = plano.data?.recomendacoes ?? [];
  return (
    <div>
      <h1 className="text-[26px] font-bold tracking-[-0.02em]">Planejamento de equipes</h1>
      <p className="text-cinza">
        Escala atual × recomendada nas próximas 72 h, por região e período. A recomendação só redistribui quem já está escalado.
        Dados sintéticos. Veja também a tela <Link to="/amanha" className="underline">Amanhã</Link>.
      </p>

      <div className="mt-4 grid gap-4 md:grid-cols-[1fr_340px]">
        <div>
          <div className="flex flex-wrap items-end gap-6 border border-tinta p-3">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-[0.08em] text-cinza">Risco não coberto (72 h)</div>
              <div className="cond num text-[36px] font-bold leading-none">
                {num(p.nao_coberto_antes, 0)} <ArrowRight className="inline" size={22} /> <span className="text-ok">{num(p.nao_coberto_depois, 0)}</span>
              </div>
              <div className="text-[12px] text-cinza">{p.unidade}{p.reducao_pct != null && ` · ${num(p.reducao_pct, 0)}% menor com a escala recomendada`}</div>
            </div>
            <label className="text-[12px]">Deslocamentos por período
              <input type="number" min={0} max={30} className="campo mt-1 w-[90px]" value={maxDesl} onChange={(e) => setMaxDesl(+e.target.value)} />
            </label>
            <label className="text-[12px]">Mínimo de equipes por região
              <input type="number" min={0} max={10} className="campo mt-1 w-[90px]" value={minReg} onChange={(e) => setMinReg(+e.target.value)} />
            </label>
            <fieldset className="text-[12px]">
              <legend>Regiões que não cedem equipes</legend>
              <div className="mt-1 flex flex-wrap gap-2">
                {REGIOES.map((r) => (
                  <label key={r} className="flex items-center gap-1">
                    <input type="checkbox" checked={fixas.includes(r)} onChange={(e) => setFixas(e.target.checked ? [...fixas, r] : fixas.filter((x) => x !== r))} />{r}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="flex gap-2">
              <Botao carregando={recalc.isPending && !recalc.variables?.salvar} onClick={() => rodar(false)}>Recalcular</Botao>
              {perfil.perfil === "gestor" && (
                <Botao variante="primario" carregando={recalc.isPending && !!recalc.variables?.salvar} onClick={() => rodar(true)}>Salvar como recomendações</Botao>
              )}
            </div>
          </div>
          {recalc.data?.gravado && <p className="mt-2 text-[13px]">Plano salvo: {recalc.data.gravado.recomendacoes} recomendações pendentes.</p>}
          {recalc.error instanceof ApiError && <p className="mt-2 text-critico">{recalc.error.erro.mensagem}</p>}

          <div className="mt-4 space-y-5">
            {p.periodos.map((per) => (
              <section key={per.inicio} className="border-t border-tinta pt-2">
                <div className="flex flex-wrap items-baseline gap-3">
                  <h2 className="text-[16px] font-bold">{per.rotulo}</h2>
                  <span className="num text-[12px] text-cinza">
                    Risco não coberto {num(per.nao_coberto_antes, 0)} → {num(per.nao_coberto_depois, 0)}
                    {per.metodo === "heuristica" && " · heurística de reserva"}
                  </span>
                </div>
                {per.avisos.map((a) => <p key={a} className="text-[12px] text-atencao">{a}</p>)}
                <table className="mt-2 w-full text-[12px]">
                  <thead>
                    <tr className="text-left text-[10px] uppercase tracking-[0.06em] text-cinza">
                      <th className="py-1">Região</th><th>Risco</th><th>Ocorrências previstas</th><th>Demanda (agentes-hora)</th>
                      <th>Equipes atual → recomendada</th><th>Falta atual → recomendada</th>
                    </tr>
                  </thead>
                  <tbody>
                    {per.regioes.map((r) => (
                      <tr key={r.regiao} className="border-t border-linha">
                        <td className="py-1 font-semibold">{r.regiao}</td>
                        <td><SeloNivel nivel={r.nivel} /> <span className="num">({Math.round(r.indice)})</span></td>
                        <td className="num">{num(r.previstas)}</td>
                        <td className="num">{num(r.demanda, 0)}</td>
                        <td className="num">{r.equipes_antes} → <b className={r.equipes_depois > r.equipes_antes ? "text-acento" : ""}>{r.equipes_depois}</b></td>
                        <td className="num">{num(r.falta_antes, 0)} → <b>{num(r.falta_depois, 0)}</b></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {per.recomendacoes.length > 0 && (
                  <ul className="mt-2 list-disc pl-5 text-[13px]">{per.recomendacoes.map((t) => <li key={t}>{t}</li>)}</ul>
                )}
              </section>
            ))}
          </div>
        </div>
        <aside>
          <h2 className="text-[13px] font-bold uppercase tracking-[0.06em]">Recomendações pendentes ({pendentes.length})</h2>
          <p className="text-[12px] text-cinza">Aceitar move as equipes na escala; rejeitar pede um motivo.</p>
          <ul className="mt-2 space-y-2">{pendentes.map((r) => <Pendente key={r.id} r={r} />)}</ul>
        </aside>
      </div>
    </div>
  );
}
