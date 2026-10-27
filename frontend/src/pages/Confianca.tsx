import { useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ComposedChart, Tooltip, XAxis, YAxis,
} from "recharts";
import { ApiError } from "../api/client";
import { Botao, Carregando, Erro, Secao } from "../components/ui";
import { usePerfil } from "../lib/perfil";
import AvisoTreino from "../preditivo/AvisoTreino";
import { useAcertometro, useModelos, useMonitor, usePadroes, useTreinar } from "../preditivo/api";
import type { SituacaoModelo } from "../preditivo/tipos";
import { num, pct } from "../preditivo/formato";
import type { Acertometro, MetricasConferidas, ModeloAvaliado, PadroesDescobertos } from "../preditivo/tipos";

const COR_MODELO = "#ff4f00";
const COR_BASE = "#6b6b6b";
const COR_REAL = "#111111";
const COR_CONFIANCA = { alta: "#1f9d55", moderada: "#d99a00", baixa: "#d62828" } as const;
const diaCurto = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

function Confianca({ nivel }: { nivel: "alta" | "moderada" | "baixa" }) {
  return (
    <span className="inline-flex items-center gap-1 text-[12px] font-semibold" style={{ color: COR_CONFIANCA[nivel] }}>
      <ShieldCheck size={14} /> Confiança {nivel}
    </span>
  );
}

function Linha({ rotulo, modelo, base, formato, melhorMenor }: {
  rotulo: string; modelo?: number; base?: number; formato: (v: number) => string; melhorMenor?: boolean;
}) {
  if (modelo == null) return null;
  const melhor = base == null ? null : melhorMenor ? modelo < base : modelo > base;
  return (
    <tr className="border-b border-linha">
      <td className="py-1 pr-3">{rotulo}</td>
      <td className="num py-1 pr-3 text-right font-semibold" style={{ color: melhor == null ? undefined : melhor ? "var(--color-ok)" : "var(--color-critico)" }}>
        {formato(modelo)}
      </td>
      <td className="num py-1 text-right text-cinza">{base == null ? "—" : formato(base)}</td>
    </tr>
  );
}

function CartaoModelo({ m }: { m: ModeloAvaliado }) {
  const p1 = m.modulo === "P1";
  const met = m.metricas as Record<string, number>;
  const base = m.baseline as Record<string, number>;
  const calib = (m.calibracao ?? []).map((c, i) => ({ prevista: c.prevista, observada: c.observada, base: m.calibracao_baseline?.[i]?.observada }));
  const maxCal = Math.max(0.01, ...calib.map((c) => Math.max(c.prevista, c.observada)));
  return (
    <Secao titulo={`${m.modulo} · ${m.titulo}`} acao={<Confianca nivel={m.selo.confianca} />}>
      <p className="text-[13px]">{m.o_que_preve}.</p>
      <p className="mt-1 text-[12px] text-cinza">{m.metodo}. Versão {m.versao}, treinada com dados até {m.treino_fim ? diaCurto(m.treino_fim) : "—"}.</p>
      <p className="mt-2 border-l-[3px] border-acento bg-neutro px-3 py-2 text-[13px] font-semibold">{m.selo.texto}</p>

      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <div>
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-tinta text-left text-[11px] uppercase tracking-[0.05em] text-cinza">
                <th className="py-1">Métrica (backtest)</th><th className="py-1 text-right">Modelo</th><th className="py-1 text-right">Média histórica</th>
              </tr>
            </thead>
            <tbody>
              {p1 ? (
                <>
                  <Linha rotulo="AUC (ordenação; 0,5 = sorteio)" modelo={met.auc} base={base.auc} formato={(v) => num(v, 3)} />
                  <Linha rotulo="Brier (erro da probabilidade)" modelo={met.brier} base={base.brier} formato={(v) => num(v, 4)} melhorMenor />
                  <Linha rotulo="Acerto nos 50 mais arriscados" modelo={met.precisao_50} base={base.precisao_50} formato={(v) => pct(v)} />
                  {m.logistica && <Linha rotulo="Regressão logística (comparação): AUC" modelo={m.logistica.auc} formato={(v) => num(v, 3)} />}
                  <Linha rotulo="Taxa de falha no período" modelo={met.taxa_base} formato={(v) => pct(v, 1)} />
                </>
              ) : (
                <>
                  <Linha rotulo="Erro médio por região e hora (MAE)" modelo={met.mae} base={base.mae} formato={(v) => num(v, 2)} melhorMenor />
                  <Linha rotulo="Erro médio nos horários de pico" modelo={met.mae_pico} base={base.mae_pico} formato={(v) => num(v, 2)} melhorMenor />
                  <Linha rotulo="Erro relativo" modelo={met.erro_pct} base={base.erro_pct} formato={(v) => `${num(v, 0)}%`} melhorMenor />
                  <Linha rotulo="Real dentro da faixa de 90%" modelo={met.cobertura_90} formato={(v) => pct(v)} />
                </>
              )}
            </tbody>
          </table>
          {!p1 && m.metricas.mae_por_horizonte && (
            <p className="mt-2 text-[12px] text-cinza">
              Erro por antecedência: {Object.entries(m.metricas.mae_por_horizonte as Record<string, number>).map(([k, v]) => `${k}: ${num(v, 2)}`).join(" · ")}
            </p>
          )}
          <h4 className="mb-1 mt-3 text-[11px] font-bold uppercase tracking-[0.06em]">O que mais pesa nas previsões</h4>
          <ul className="space-y-1">
            {m.importancia.slice(0, 7).map((f) => (
              <li key={f.grupo} className="grid grid-cols-[1fr_auto] items-center gap-x-2 text-[12px]">
                <span>{f.nome}</span><span className="num text-cinza">{pct(f.peso)}</span>
                <span className="col-span-2 h-[5px] bg-neutro"><span className="block h-full bg-tinta" style={{ width: `${f.peso * 100}%` }} /></span>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-3">
          <div>
            <h4 className="mb-1 text-[11px] font-bold uppercase tracking-[0.06em]">
              Semana a semana no backtest ({p1 ? "AUC, maior é melhor" : "erro médio, menor é melhor"})
            </h4>
            <div className="h-[190px]">
              <ResponsiveContainer>
                <LineChart data={m.backtest} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
                  <CartesianGrid stroke="#eee" vertical={false} />
                  <XAxis dataKey="data_corte" tickFormatter={diaCurto} fontSize={11} />
                  <YAxis fontSize={11} domain={["auto", "auto"]} tickFormatter={(v) => num(v, 2)} />
                  <Tooltip formatter={(v: number) => num(v, 3)} labelFormatter={(l) => `Corte de ${diaCurto(String(l))}`} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line dataKey="modelo" name="Modelo" stroke={COR_MODELO} strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line dataKey="baseline" name="Média histórica" stroke={COR_BASE} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
          {p1 && calib.length > 0 && (
            <div>
              <h4 className="mb-1 text-[11px] font-bold uppercase tracking-[0.06em]">Calibração: quando diz X%, falham X%?</h4>
              <div className="h-[190px]">
                <ResponsiveContainer>
                  <ComposedChart data={calib} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
                    <CartesianGrid stroke="#eee" />
                    <XAxis dataKey="prevista" type="number" domain={[0, maxCal]} tickFormatter={(v) => pct(v, 0)} fontSize={11} name="Prevista" />
                    <YAxis type="number" domain={[0, maxCal]} tickFormatter={(v) => pct(v, 0)} fontSize={11} />
                    <Tooltip formatter={(v: number) => pct(v, 1)} labelFormatter={(l) => `Prevista ${pct(Number(l), 1)}`} />
                    <ReferenceLine segment={[{ x: 0, y: 0 }, { x: maxCal, y: maxCal }]} stroke="#bbb" strokeDasharray="3 3" />
                    <Line dataKey="observada" name="Observada" stroke={COR_MODELO} strokeWidth={2} isAnimationActive={false} />
                    <Scatter dataKey="observada" fill={COR_MODELO} isAnimationActive={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <p className="text-[11px] text-cinza">Cada ponto é um décimo dos equipamentos, do menor para o maior risco. Na diagonal, a probabilidade dita bate com o que aconteceu.</p>
            </div>
          )}
        </div>
      </div>
    </Secao>
  );
}

function Numero({ rotulo, valor, sub }: { rotulo: string; valor: string; sub?: string }) {
  return (
    <div className="border border-linha p-3">
      <div className="text-[11px] font-bold uppercase tracking-[0.05em] text-cinza">{rotulo}</div>
      <div className="num text-[24px] font-bold leading-tight">{valor}</div>
      {sub && <div className="text-[12px] text-cinza">{sub}</div>}
    </div>
  );
}

function TabelaConferida({ linhas, titulo }: { linhas: (MetricasConferidas & { rotulo: string })[]; titulo: string }) {
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="border-b border-tinta text-left text-[11px] uppercase tracking-[0.05em] text-cinza">
          <th className="py-1">{titulo}</th><th className="py-1 text-right">Horas</th><th className="py-1 text-right">Erro do modelo</th>
          <th className="py-1 text-right">Erro da média</th><th className="py-1 text-right">Na faixa</th>
        </tr>
      </thead>
      <tbody>
        {linhas.map((l) => (
          <tr key={l.rotulo} className="border-b border-linha">
            <td className="py-1">{l.rotulo}</td>
            <td className="num py-1 text-right text-cinza">{l.n}</td>
            <td className="num py-1 text-right font-semibold" style={{ color: l.mae <= l.mae_baseline ? "var(--color-ok)" : "var(--color-critico)" }}>{num(l.mae, 2)}</td>
            <td className="num py-1 text-right text-cinza">{num(l.mae_baseline, 2)}</td>
            <td className="num py-1 text-right">{pct(l.cobertura_intervalo)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AcertometroP2({ a }: { a: Acertometro["P2"] }) {
  if (!a.conferidas || !a.geral) {
    return <p className="text-[13px] text-cinza">Nenhuma hora prevista terminou ainda. A conferência começa uma hora depois do primeiro lote de previsões.</p>;
  }
  const g = a.geral;
  const pouco = g.n < 480; // menos de 4 dias das 5 regiões
  const serie = (a.serie_48h ?? []).map((s) => ({ ...s, hora: `${new Date(s.em).toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", "")} ${new Date(s.em).getHours()} h` }));
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-4">
        <Numero rotulo="Horas conferidas" valor={g.n.toLocaleString("pt-BR")} sub="região × hora, previsão mais recente" />
        <Numero rotulo="Erro do modelo" valor={num(g.mae, 2)} sub="ocorrências por região e hora" />
        <Numero rotulo="Erro da média histórica" valor={num(g.mae_baseline, 2)}
                sub={g.ganho_pct == null ? undefined : g.ganho_pct >= 0 ? `modelo erra ${num(g.ganho_pct, 0)}% menos` : `modelo erra ${num(-g.ganho_pct, 0)}% mais`} />
        <Numero rotulo="Real dentro da faixa" valor={pct(g.cobertura_intervalo)} sub="meta: cerca de 90%" />
      </div>
      {pouco && (
        <p className="border-l-[3px] border-atencao bg-neutro px-3 py-2 text-[12px]">
          Amostra pequena ({g.n} horas conferidas): com tão poucas, o sorteio natural das contagens pesa mais que o modelo. O backtest acima,
          com 13 semanas, é a medida mais firme; esta conferência fica mais confiável a cada dia.
        </p>
      )}
      {serie.length > 0 && (
        <div>
          <h4 className="mb-1 text-[11px] font-bold uppercase tracking-[0.06em]">Cidade inteira, últimas 48 h: previsto × real</h4>
          <div className="h-[220px]">
            <ResponsiveContainer>
              <LineChart data={serie} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
                <CartesianGrid stroke="#eee" vertical={false} />
                <XAxis dataKey="hora" fontSize={11} interval="preserveStartEnd" />
                <YAxis fontSize={11} />
                <Tooltip formatter={(v: number) => num(v, 1)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line dataKey="real" name="Aconteceu" stroke={COR_REAL} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line dataKey="previsto" name="Previsto" stroke={COR_MODELO} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line dataKey="baseline" name="Média histórica" stroke={COR_BASE} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        {a.por_antecedencia && <TabelaConferida linhas={a.por_antecedencia.map((l) => ({ ...l, rotulo: l.faixa }))} titulo="Antecedência" />}
        {a.por_regiao && <TabelaConferida linhas={a.por_regiao.map((l) => ({ ...l, rotulo: l.regiao }))} titulo="Região" />}
        {a.por_dia && <TabelaConferida linhas={a.por_dia.map((l) => ({ ...l, rotulo: diaCurto(l.dia) }))} titulo="Dia" />}
      </div>
    </div>
  );
}

function AcertometroP1({ a }: { a: Acertometro["P1"] }) {
  if (!a.lotes.length) return <p className="text-[13px] text-cinza">Ainda não há lotes de previsão de falha.</p>;
  const dados = a.lotes.slice().reverse().map((l) => ({
    lote: diaCurto(l.inicio), apontados: l.taxa_apontados, geral: l.taxa_geral,
  }));
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-tinta text-left text-[11px] uppercase tracking-[0.05em] text-cinza">
            <th className="py-1">Semana a partir de</th><th className="py-1">Situação</th>
            <th className="py-1 text-right">Dos {a.top} apontados, falharam</th><th className="py-1 text-right">Esperado</th>
            <th className="py-1 text-right">Taxa nos demais</th>
          </tr>
        </thead>
        <tbody>
          {a.lotes.map((l) => (
            <tr key={l.inicio} className="border-b border-linha">
              <td className="py-1">{diaCurto(l.inicio)}</td>
              <td className="py-1 text-cinza">{l.encerrado ? "encerrada" : `em andamento (${l.decorrido_pct}% da semana)`}</td>
              <td className="num py-1 text-right font-semibold">{l.falharam_apontados} ({pct(l.taxa_apontados)})</td>
              <td className="num py-1 text-right text-cinza">{num(l.esperado_apontados, 1)}</td>
              <td className="num py-1 text-right">{pct(l.taxa_geral, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="h-[180px]">
        <ResponsiveContainer>
          <BarChart data={dados} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="#eee" vertical={false} />
            <XAxis dataKey="lote" fontSize={11} />
            <YAxis fontSize={11} tickFormatter={(v) => pct(v)} domain={[0, (max: number) => Math.max(max, 0.1)]} />
            <Tooltip formatter={(v: number) => pct(v, 1)} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="apontados" name={`${a.top} apontados`} fill={COR_MODELO} isAnimationActive={false} />
            <Bar dataKey="geral" name="Todos" fill={COR_BASE} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

const VEREDITO = {
  encontrado: { r: "Encontrado", cor: "#1f9d55" }, fraco: { r: "Sinal fraco", cor: "#d99a00" },
  nao_encontrado: { r: "Não encontrado", cor: "#d62828" }, sem_dados: { r: "Sem dados", cor: "#9a9aa0" },
} as const;

function Curva({ titulo, dados, x, series, fmtX, fmtY }: {
  titulo: string; dados: Record<string, number>[]; x: string; series: [string, string, string, boolean?][];
  fmtX: (v: number) => string; fmtY: (v: number) => string;
}) {
  return (
    <div>
      <h4 className="mb-1 text-[11px] font-bold uppercase tracking-[0.06em]">{titulo}</h4>
      <div className="h-[170px]">
        <ResponsiveContainer>
          <LineChart data={dados} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="#eee" vertical={false} />
            <XAxis dataKey={x} fontSize={11} tickFormatter={fmtX} />
            <YAxis fontSize={11} tickFormatter={fmtY} domain={[0, "auto"]} />
            <Tooltip formatter={(v: number) => fmtY(v)} labelFormatter={(l) => fmtX(Number(l))} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {series.map(([k, nome, cor, trac]) => (
              <Line key={k} dataKey={k} name={nome} stroke={cor} strokeWidth={2} strokeDasharray={trac ? "4 3" : undefined} dot={false} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Padroes({ d }: { d: PadroesDescobertos }) {
  const c = d.curvas;
  return (
    <div className="space-y-4">
      <p className="border border-linha bg-neutro px-3 py-2 text-[12px]">
        {d.aviso} Resultado: <b>{d.resumo.encontrado ?? 0} encontrados</b>, {d.resumo.fraco ?? 0} com sinal fraco, {d.resumo.nao_encontrado ?? 0} não encontrados.
      </p>
      <ul className="grid gap-3 lg:grid-cols-2">
        {d.padroes.map((p) => (
          <li key={p.padrao} className="border border-linha p-3 text-[13px]">
            <div className="flex items-start justify-between gap-2">
              <b>{p.padrao}. {p.titulo}</b>
              <span className="shrink-0 px-2 py-[1px] text-[11px] font-bold uppercase tracking-[0.04em] text-white" style={{ background: VEREDITO[p.veredito].cor }}>
                {VEREDITO[p.veredito].r}
              </span>
            </div>
            <p className="mt-1"><span className="text-cinza">O que o sistema achou:</span> {p.descoberto}.{p.detalhe ? ` ${p.detalhe}.` : ""}</p>
            <p className="mt-1"><span className="text-cinza">O que foi plantado:</span> {p.plantado}.</p>
            <p className="mt-1 text-[11px] text-cinza">{p.modulo} · {p.metodo}</p>
          </li>
        ))}
      </ul>
      <div className="grid gap-4 lg:grid-cols-2">
        {c.idade_camera && <Curva titulo="P1: risco previsto de câmera por idade (dependência parcial)" dados={c.idade_camera} x="meses"
          series={[["marca_fragil", "Marca do padrão 4", COR_MODELO], ["outras", "Outras marcas", COR_BASE, true]]}
          fmtX={(v) => `${v} meses`} fmtY={(v) => pct(v, 1)} />}
        {c.calor_radar && <Curva titulo="P1: risco previsto de radar pela temperatura da semana" dados={c.calor_radar} x="temperatura"
          series={[["rodovia", "Rodovia (80 km/h ou mais)", COR_MODELO], ["urbano", "Urbano", COR_BASE, true]]}
          fmtX={(v) => `${v} °C`} fmtY={(v) => pct(v, 1)} />}
        {c.atraso && <Curva titulo="P1: risco previsto pelo atraso da preventiva" dados={c.atraso} x="dias"
          series={[["risco", "Risco médio em 7 dias", COR_MODELO]]} fmtX={(v) => `${v} dias`} fmtY={(v) => pct(v, 1)} />}
        {c.centro_por_hora && <Curva titulo="P2: Centro por hora, últimas 4 semanas (ocorrências por hora)" dados={c.centro_por_hora} x="hora"
          series={[["previsto_sex_sab", "Previsto sex/sáb", COR_MODELO], ["real_sex_sab", "Real sex/sáb", COR_REAL],
                   ["previsto_outros", "Previsto outros dias", COR_MODELO, true], ["real_outros", "Real outros dias", COR_BASE, true]]}
          fmtX={(v) => `${v} h`} fmtY={(v) => num(v, 1)} />}
      </div>
    </div>
  );
}

const COR_SIT: Record<SituacaoModelo, string> = { ok: "#1f9d55", sem_dados: "#6b6b6b", atencao: "#d99a00", retreinar: "#d62828" };
const ROT_SIT: Record<SituacaoModelo, string> = { ok: "OK", sem_dados: "Sem dados ainda", atencao: "Atenção", retreinar: "Retreinar" };

function MonitorModelos() {
  const m = useMonitor();
  if (m.isLoading) return <Carregando texto="Conferindo os modelos…" />;
  if (!m.data) return <Erro erro={m.error} />;
  return (
    <Secao titulo="Monitor dos modelos em operação">
      <p className="mb-2 text-[13px]">
        <b style={{ color: COR_SIT[m.data.situacao] }}>{m.data.texto}.</b> <span className="text-cinza">{m.data.como_funciona}</span>
      </p>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {m.data.modelos.map((x) => (
          <div key={x.nome} className="border border-linha p-2 text-[12px]" style={{ borderLeft: `4px solid ${COR_SIT[x.situacao]}` }}>
            <div className="flex items-center justify-between gap-2">
              <b className="text-[13px]">{x.titulo}</b>
              <span className="font-semibold" style={{ color: COR_SIT[x.situacao] }}>{ROT_SIT[x.situacao]}</span>
            </div>
            <ul className="mt-1 space-y-1">
              {x.verificacoes.map((c) => (
                <li key={c.verificacao} className="flex gap-1">
                  <span className="mt-[5px] inline-block h-[7px] w-[7px] shrink-0" style={{ background: COR_SIT[c.situacao] }} />
                  <span>{c.texto}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Secao>
  );
}

export default function ConfiancaModelos() {
  const modelos = useModelos();
  const [dias, setDias] = useState(7);
  const ac = useAcertometro(dias);
  const treinar = useTreinar();
  const padroes = usePadroes();
  const { perfil } = usePerfil();
  const rodando = modelos.data?.treino.situacao === "rodando";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[24px] font-bold tracking-[-0.02em]">Confiança dos modelos</h1>
          <p className="max-w-[760px] text-[13px] text-cinza">
            Toda previsão é comparada com a média histórica e com o que aconteceu. {modelos.data?.avaliacao}
          </p>
        </div>
        {perfil.perfil === "gestor" && (
          <Botao carregando={treinar.isPending} disabled={rodando} onClick={() => treinar.mutate()}>
            <RefreshCw size={14} /> Retreinar agora
          </Botao>
        )}
      </div>
      {treinar.error instanceof ApiError && <p className="text-[13px] text-critico">{treinar.error.erro.mensagem}</p>}
      <AvisoTreino />
      <p className="border border-linha bg-neutro px-3 py-2 text-[12px]">
        Os dados desta demonstração são sintéticos, gerados com padrões plantados (documentados em docs/parte3/padroes-plantados.md).
        Os números mostram que o método funciona; numa cidade real, os modelos seriam treinados e avaliados com os dados dela.
      </p>

      <MonitorModelos />
      {modelos.isLoading ? <Carregando /> : modelos.error ? <Erro erro={modelos.error} /> : (
        <>
          {modelos.data!.modelos.map((m) => <CartaoModelo key={m.nome} m={m} />)}
          <Secao titulo="Módulos que usam esses modelos">
            <ul className="grid gap-3 md:grid-cols-3">
              {modelos.data!.derivados.map((d) => (
                <li key={d.modulo} className="border border-linha p-3 text-[13px]">
                  <b>{d.modulo} · {d.titulo}</b>
                  <p className="mt-1 text-cinza">{d.texto}</p>
                </li>
              ))}
            </ul>
          </Secao>
        </>
      )}

      <Secao titulo="Padrões descobertos: o que os modelos aprenderam × o que foi plantado">
        <p className="mb-3 text-[13px] text-cinza">
          Depois do treino, o modelo pronto é interrogado: "e se este mesmo equipamento fosse mais velho, estivesse mais quente, com a
          preventiva atrasada?"; "quantas ocorrências você prevê nas noites de sexta no Centro?". Só no fim a resposta é posta ao lado
          da regra plantada no gerador.
        </p>
        {padroes.isLoading ? <Carregando texto="Interrogando os modelos (alguns segundos na primeira vez)…" />
          : padroes.error ? <Erro erro={padroes.error} /> : <Padroes d={padroes.data!} />}
      </Secao>

      <Secao
        titulo="Acertômetro: previsto × o que aconteceu"
        acao={(
          <select className="campo !w-auto !py-1 text-[13px]" value={dias} onChange={(e) => setDias(Number(e.target.value))} aria-label="Período">
            <option value={1}>Últimas 24 h</option><option value={7}>Últimos 7 dias</option><option value={30}>Últimos 30 dias</option>
          </select>
        )}
      >
        <p className="mb-3 text-[13px] text-cinza">
          As previsões ficam guardadas e, quando o período passa, são conferidas com o que foi registrado. A média histórica usada na
          comparação é a mesma hora e dia da semana nas 8 semanas anteriores.
        </p>
        {ac.isLoading ? <Carregando /> : ac.error ? <Erro erro={ac.error} /> : (
          <div className="space-y-5">
            <div>
              <h3 className="mb-2 text-[14px] font-bold">P2 · Ocorrências por região e hora</h3>
              <AcertometroP2 a={ac.data!.P2} />
            </div>
            <div>
              <h3 className="mb-2 text-[14px] font-bold">P1 · Risco de falha em 7 dias</h3>
              <AcertometroP1 a={ac.data!.P1} />
            </div>
          </div>
        )}
      </Secao>
    </div>
  );
}
