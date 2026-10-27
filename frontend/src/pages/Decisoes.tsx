import { useState } from "react";
import { Carregando, Erro, Secao } from "../components/ui";
import GavetaCartao from "../preditivo/GavetaCartao";
import { useRetorno } from "../preditivo/api";
import { num, pct } from "../preditivo/formato";

const ROTULO_ESTADO: Record<string, string> = { aceita: "Aceita", ajustada: "Ajustada", rejeitada: "Rejeitada", pendente: "Pendente", expirada: "Expirada" };
const COR_ESTADO: Record<string, string> = { aceita: "#1f9d55", ajustada: "#d99a00", rejeitada: "#d62828", pendente: "#6b6b6b", expirada: "#9a9aa0" };
const quando = (iso: string | null) => (iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");

function Numero({ rotulo, valor, sub }: { rotulo: string; valor: string; sub?: string }) {
  return (
    <div className="border border-linha p-3">
      <div className="text-[11px] font-bold uppercase tracking-[0.05em] text-cinza">{rotulo}</div>
      <div className="num text-[26px] font-bold leading-tight">{valor}</div>
      {sub && <div className="text-[12px] text-cinza">{sub}</div>}
    </div>
  );
}

/** Retorno das recomendações (C5): quem decidiu o quê, por quê, e o que aconteceu depois. */
export default function Decisoes() {
  const [dias, setDias] = useState(30);
  const [cartao, setCartao] = useState<number | null>(null);
  const r = useRetorno(dias);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-bold tracking-[-0.02em]">Decisões e retorno</h1>
          <p className="max-w-[760px] text-cinza">
            O PROMETHEUS recomenda; as pessoas decidem. Toda decisão fica registrada (quem, quando, por quê) e, quando o período passa,
            o resultado é comparado com o previsto.
          </p>
        </div>
        <select className="campo !w-auto" value={dias} onChange={(e) => setDias(Number(e.target.value))} aria-label="Período">
          <option value={7}>Últimos 7 dias</option><option value={30}>Últimos 30 dias</option><option value={90}>Últimos 90 dias</option>
        </select>
      </div>
      {r.isLoading ? <Carregando /> : r.error ? <Erro erro={r.error} /> : (() => {
        const d = r.data!;
        const os = d.comparacao.os;
        const ref = d.comparacao.reforco;
        return (
          <>
            <div className="grid gap-2 sm:grid-cols-4">
              <Numero rotulo="Recomendações" valor={String(d.total)} sub={`${d.por_estado.pendente ?? 0} pendentes · ${d.por_estado.expirada ?? 0} expiradas`} />
              <Numero rotulo="Decididas" valor={String(d.decididas)} />
              <Numero rotulo="Aceitas ou ajustadas" valor={d.taxa_aceitacao == null ? "—" : pct(d.taxa_aceitacao)} sub="das decididas" />
              <Numero rotulo="Rejeitadas" valor={String(d.por_estado.rejeitada ?? 0)} sub="sempre com motivo" />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Secao titulo="Por tipo">
                <table className="w-full text-[13px]">
                  <thead><tr className="border-b border-tinta text-left text-[11px] uppercase tracking-[0.05em] text-cinza">
                    <th className="py-1">Tipo</th><th className="py-1 text-right">Total</th><th className="py-1 text-right">Aceitas</th>
                    <th className="py-1 text-right">Rejeitadas</th><th className="py-1 text-right">Pendentes</th><th className="py-1 text-right">Expiradas</th>
                  </tr></thead>
                  <tbody>{d.por_tipo.map((t) => (
                    <tr key={t.tipo} className="border-b border-linha">
                      <td className="py-1">{t.rotulo}</td><td className="num py-1 text-right">{t.total}</td><td className="num py-1 text-right">{t.aceitas}</td>
                      <td className="num py-1 text-right">{t.rejeitadas}</td><td className="num py-1 text-right">{t.pendentes}</td><td className="num py-1 text-right">{t.expiradas}</td>
                    </tr>
                  ))}</tbody>
                </table>
                <h4 className="mb-1 mt-3 text-[11px] font-bold uppercase tracking-[0.06em]">Motivos de rejeição</h4>
                {d.motivos_rejeicao.length === 0 ? <p className="text-[13px] text-cinza">Nenhuma rejeição no período.</p> : (
                  <ul className="space-y-1 text-[13px]">{d.motivos_rejeicao.map((m) => <li key={m.motivo}>“{m.motivo}” <span className="text-cinza">({m.vezes}×)</span></li>)}</ul>
                )}
              </Secao>
              <Secao titulo="O que aconteceu depois">
                <div className="space-y-3 text-[13px]">
                  <div>
                    <b>OS preventivas</b> (equipamento falhou dentro da janela prevista?)
                    <div className="mt-1 grid grid-cols-2 gap-2">
                      <Numero rotulo="Aceitas" valor={os.aceitas.taxa_falha == null ? "—" : pct(os.aceitas.taxa_falha)} sub={`falharam, de ${os.aceitas.conferidas} conferidas`} />
                      <Numero rotulo="Rejeitadas" valor={os.rejeitadas.taxa_falha == null ? "—" : pct(os.rejeitadas.taxa_falha)} sub={`falharam, de ${os.rejeitadas.conferidas} conferidas`} />
                    </div>
                  </div>
                  <div>
                    <b>Reforços de equipes</b> (ocorrências registradas ÷ previstas no destino)
                    <div className="mt-1 grid grid-cols-2 gap-2">
                      <Numero rotulo="Aceitos" valor={ref.aceitas.real_sobre_previsto == null ? "—" : `${num(ref.aceitas.real_sobre_previsto, 2)}×`} sub={`${ref.aceitas.conferidas} conferidos`} />
                      <Numero rotulo="Rejeitados" valor={ref.rejeitadas.real_sobre_previsto == null ? "—" : `${num(ref.rejeitadas.real_sobre_previsto, 2)}×`} sub={`${ref.rejeitadas.conferidas} conferidos`} />
                    </div>
                    <p className="mt-1 text-[11px] text-cinza">Com mais agentes, a região tende a registrar mais ocorrências (mais olhos na rua): leia junto com o tempo de resposta da central.</p>
                  </div>
                  <p className="text-[12px] text-cinza">{d.comparacao.aviso}</p>
                </div>
              </Secao>
            </div>

            <Secao titulo="Histórico de decisões">
              {d.decisoes.length === 0 ? <p className="text-[13px] text-cinza">Nenhuma decisão no período.</p> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]">
                    <thead><tr className="border-b border-tinta text-left text-[11px] uppercase tracking-[0.05em] text-cinza">
                      <th className="py-1 pr-2">Quando</th><th className="py-1 pr-2">Quem</th><th className="py-1 pr-2">Decisão</th>
                      <th className="py-1 pr-2">Recomendação</th><th className="py-1">Resultado</th>
                    </tr></thead>
                    <tbody>{d.decisoes.map((x) => (
                      <tr key={x.id} className="border-b border-linha align-top">
                        <td className="num whitespace-nowrap py-1 pr-2">{quando(x.decidido_em)}</td>
                        <td className="py-1 pr-2">{x.decidido_por}</td>
                        <td className="py-1 pr-2">
                          <span className="font-semibold" style={{ color: COR_ESTADO[x.estado] }}>{ROTULO_ESTADO[x.estado] ?? x.estado}</span>
                          {x.motivo && <div className="text-[12px] text-cinza">“{x.motivo}”</div>}
                        </td>
                        <td className="py-1 pr-2">
                          <div className="text-[11px] uppercase tracking-[0.04em] text-cinza">{x.rotulo_tipo}</div>
                          {x.previsao_id ? <button className="text-left hover:underline" onClick={() => setCartao(x.previsao_id)}>{x.texto}</button> : x.texto}
                        </td>
                        <td className="py-1">{x.retorno ? x.retorno.texto : <span className="text-cinza">aguardando o fim do período</span>}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </Secao>
          </>
        );
      })()}
      {cartao != null && <GavetaCartao id={cartao} fechar={() => setCartao(null)} />}
    </div>
  );
}
