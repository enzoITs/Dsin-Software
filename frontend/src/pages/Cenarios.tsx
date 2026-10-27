import { useState } from "react";
import { Play, Plus, RotateCcw, Save, Trash2, X } from "lucide-react";
import { ApiError } from "../api/client";
import { Botao, Carregando, Erro, Secao } from "../components/ui";
import AvisoTreino from "../preditivo/AvisoTreino";
import { SeloNivel } from "../preditivo/CartaoPrevisao";
import { useCenario, useCenarios, useOpcoesCenario, useRemoverCenario, useSalvarCenario, useSimular } from "../preditivo/api";
import { COR_NIVEL, num } from "../preditivo/formato";
import type { CenarioParams, ResultadoCenario } from "../preditivo/tipos";
import { COR } from "../lib/cores";

const vazio = (): CenarioParams => ({ eventos: [], cancelar_eventos: [], clima: [], equipes: [], equipamentos_fora: null, manutencoes: null });
const hora = (iso: string) => new Date(iso).toLocaleString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

/** "2026-10-30T20:00" (horário local) daqui a N horas, para os campos de data. */
function localDaqui(h: number) {
  const d = new Date(Date.now() + h * 3_600_000);
  d.setMinutes(0, 0, 0);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:00`;
}
const somarHoras = (local: string, h: number) => {
  const d = new Date(local);
  d.setHours(d.getHours() + h);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

function Bloco({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <fieldset className="border border-linha p-3">
      <legend className="px-1 text-[11px] font-bold uppercase tracking-[0.06em]">{titulo}</legend>
      <div className="space-y-2 text-[13px]">{children}</div>
    </fieldset>
  );
}

function Item({ children, remover }: { children: React.ReactNode; remover: () => void }) {
  return (
    <li className="flex items-center justify-between gap-2 bg-neutro px-2 py-1 text-[12px]">
      <span>{children}</span>
      <button onClick={remover} aria-label="Remover" className="text-cinza hover:text-tinta"><X size={13} /></button>
    </li>
  );
}

function Construtor({ p, setP }: { p: CenarioParams; setP: (p: CenarioParams) => void }) {
  const op = useOpcoesCenario();
  const o = op.data;
  const [ev, setEv] = useState({ nome: "", bairro_id: 0, publico: 30000, inicio: localDaqui(24), duracao: 4 });
  const [cl, setCl] = useState({ chuva_mm: 10, inicio: localDaqui(1), fim: localDaqui(13) });
  const [eq, setEq] = useState({ regiao: "", delta: -2 });
  const [fora, setFora] = useState({ regiao: "", prefixo: "CAM", quantidade: 5, codigos: "" });
  const [man, setMan] = useState({ regiao: "", quantidade: 10 });
  if (op.isLoading) return <Carregando />;
  if (!o) return <Erro erro={op.error} />;
  const bairro = (id: number) => o.bairros.find((b) => b.id === id);
  return (
    <div className="space-y-3">
      <Bloco titulo="Evento novo">
        <input className="campo" placeholder="Nome (ex.: Show no Pacaembu)" value={ev.nome} onChange={(e) => setEv({ ...ev, nome: e.target.value })} />
        <select className="campo" value={ev.bairro_id} onChange={(e) => setEv({ ...ev, bairro_id: Number(e.target.value) })} aria-label="Bairro do evento">
          <option value={0}>Bairro…</option>
          {o.regioes.map((r) => (
            <optgroup key={r} label={r}>{o.bairros.filter((b) => b.regiao === r).map((b) => <option key={b.id} value={b.id}>{b.nome}</option>)}</optgroup>
          ))}
        </select>
        <div className="grid grid-cols-3 gap-2">
          <label className="col-span-2">Início<input type="datetime-local" className="campo" value={ev.inicio} onChange={(e) => setEv({ ...ev, inicio: e.target.value })} /></label>
          <label>Horas<input type="number" min={1} max={24} className="campo" value={ev.duracao} onChange={(e) => setEv({ ...ev, duracao: Number(e.target.value) })} /></label>
        </div>
        <label className="block">Público<input type="number" min={0} step={1000} className="campo" value={ev.publico} onChange={(e) => setEv({ ...ev, publico: Number(e.target.value) })} /></label>
        <Botao disabled={!ev.bairro_id} onClick={() => setP({ ...p, eventos: [...(p.eventos ?? []), {
          nome: ev.nome || "Evento do cenário", bairro_id: ev.bairro_id, publico: ev.publico, inicio: ev.inicio, fim: somarHoras(ev.inicio, ev.duracao),
        }] })}><Plus size={14} /> Incluir evento</Botao>
        <ul className="space-y-1">
          {(p.eventos ?? []).map((x, i) => (
            <Item key={i} remover={() => setP({ ...p, eventos: p.eventos!.filter((_, k) => k !== i) })}>
              {x.nome}: {num(x.publico / 1000, 0)} mil pessoas em {bairro(x.bairro_id!)?.nome}, {hora(x.inicio!)}
            </Item>
          ))}
        </ul>
      </Bloco>

      <Bloco titulo="Cancelar evento programado">
        {o.eventos.length === 0 && <p className="text-cinza">Nenhum evento nas próximas 72 h.</p>}
        {o.eventos.map((e) => (
          <label key={e.id} className="flex gap-2">
            <input type="checkbox" checked={(p.cancelar_eventos ?? []).includes(e.id)}
              onChange={(x) => setP({ ...p, cancelar_eventos: x.target.checked ? [...(p.cancelar_eventos ?? []), e.id] : p.cancelar_eventos!.filter((i) => i !== e.id) })} />
            <span>{e.nome} <span className="text-cinza">({num(e.publico_estimado / 1000, 0)} mil, {hora(e.inicio_em)})</span></span>
          </label>
        ))}
      </Bloco>

      <Bloco titulo="Clima">
        <div className="grid grid-cols-2 gap-2">
          <label>De<input type="datetime-local" className="campo" value={cl.inicio} onChange={(e) => setCl({ ...cl, inicio: e.target.value })} /></label>
          <label>Até<input type="datetime-local" className="campo" value={cl.fim} onChange={(e) => setCl({ ...cl, fim: e.target.value })} /></label>
        </div>
        <label className="block">Chuva (mm por hora)<input type="number" min={0} max={80} className="campo" value={cl.chuva_mm} onChange={(e) => setCl({ ...cl, chuva_mm: Number(e.target.value) })} /></label>
        <Botao onClick={() => setP({ ...p, clima: [...(p.clima ?? []), { ...cl, tempestade: cl.chuva_mm >= 20 }] })}><Plus size={14} /> Incluir chuva</Botao>
        <ul className="space-y-1">
          {(p.clima ?? []).map((x, i) => (
            <Item key={i} remover={() => setP({ ...p, clima: p.clima!.filter((_, k) => k !== i) })}>{num(x.chuva_mm ?? 0, 0)} mm/h de {hora(x.inicio!)} a {hora(x.fim!)}</Item>
          ))}
        </ul>
      </Bloco>

      <Bloco titulo="Equipes">
        <div className="grid grid-cols-[1fr_90px] gap-2">
          <select className="campo" value={eq.regiao} onChange={(e) => setEq({ ...eq, regiao: e.target.value })} aria-label="Região">
            <option value="">Região…</option>{o.regioes.map((r) => <option key={r}>{r}</option>)}
          </select>
          <select className="campo" value={eq.delta} onChange={(e) => setEq({ ...eq, delta: Number(e.target.value) })} aria-label="Equipes a mais ou a menos">
            {[-5, -4, -3, -2, -1, 1, 2, 3, 4, 5].map((d) => <option key={d} value={d}>{d > 0 ? `+${d}` : d}</option>)}
          </select>
        </div>
        <p className="text-[11px] text-cinza">Equipes a mais ou a menos em cada período das próximas 72 h.</p>
        <Botao disabled={!eq.regiao} onClick={() => setP({ ...p, equipes: [...(p.equipes ?? []), { ...eq }] })}><Plus size={14} /> Incluir</Botao>
        <ul className="space-y-1">
          {(p.equipes ?? []).map((x, i) => (
            <Item key={i} remover={() => setP({ ...p, equipes: p.equipes!.filter((_, k) => k !== i) })}>{x.regiao}: {x.delta > 0 ? "+" : ""}{x.delta} equipes por período</Item>
          ))}
        </ul>
      </Bloco>

      <Bloco titulo="Equipamentos fora de operação">
        {p.equipamentos_fora ? (
          <Item remover={() => setP({ ...p, equipamentos_fora: null })}>
            {p.equipamentos_fora.codigos?.length ? p.equipamentos_fora.codigos.join(", ")
              : `${p.equipamentos_fora.quantidade} × ${o.tipos.find((t) => t.prefixo === p.equipamentos_fora!.prefixo)?.nome ?? "equipamento"}${p.equipamentos_fora.regiao ? ` na região ${p.equipamentos_fora.regiao}` : ""}`}
          </Item>
        ) : (
          <>
            <div className="grid grid-cols-[1fr_1fr_70px] gap-2">
              <select className="campo" value={fora.prefixo} onChange={(e) => setFora({ ...fora, prefixo: e.target.value })} aria-label="Tipo">
                {o.tipos.map((t) => <option key={t.prefixo} value={t.prefixo}>{t.nome}</option>)}
              </select>
              <select className="campo" value={fora.regiao} onChange={(e) => setFora({ ...fora, regiao: e.target.value })} aria-label="Região">
                <option value="">Qualquer região</option>{o.regioes.map((r) => <option key={r}>{r}</option>)}
              </select>
              <input type="number" min={1} max={200} className="campo" value={fora.quantidade} onChange={(e) => setFora({ ...fora, quantidade: Number(e.target.value) })} aria-label="Quantidade" />
            </div>
            <input className="campo" placeholder="ou códigos: CAM-0012, RAD-0451" value={fora.codigos} onChange={(e) => setFora({ ...fora, codigos: e.target.value })} />
            <Botao onClick={() => {
              const codigos = fora.codigos.split(/[\s,;]+/).map((c) => c.trim().toUpperCase()).filter(Boolean);
              setP({ ...p, equipamentos_fora: codigos.length ? { codigos } : { prefixo: fora.prefixo, regiao: fora.regiao || undefined, quantidade: fora.quantidade } });
            }}><Plus size={14} /> Derrubar</Botao>
          </>
        )}
      </Bloco>

      <Bloco titulo="Manutenções preventivas agora">
        {p.manutencoes ? (
          <Item remover={() => setP({ ...p, manutencoes: null })}>
            Preventiva nos {p.manutencoes.quantidade} de maior risco{p.manutencoes.regiao ? ` da região ${p.manutencoes.regiao}` : ""}
          </Item>
        ) : (
          <>
            <div className="grid grid-cols-[1fr_70px] gap-2">
              <select className="campo" value={man.regiao} onChange={(e) => setMan({ ...man, regiao: e.target.value })} aria-label="Região">
                <option value="">Cidade inteira</option>{o.regioes.map((r) => <option key={r}>{r}</option>)}
              </select>
              <input type="number" min={1} max={200} className="campo" value={man.quantidade} onChange={(e) => setMan({ ...man, quantidade: Number(e.target.value) })} aria-label="Quantidade" />
            </div>
            <Botao onClick={() => setP({ ...p, manutencoes: { regiao: man.regiao || undefined, quantidade: man.quantidade } })}><Plus size={14} /> Incluir</Botao>
          </>
        )}
      </Bloco>
    </div>
  );
}

function Variacao({ antes, depois, inverter }: { antes: number; depois: number; inverter?: boolean }) {
  const d = depois - antes;
  if (Math.abs(d) < 0.05) return <span className="text-cinza">=</span>;
  const pior = inverter ? d < 0 : d > 0;
  return <span className="num font-semibold" style={{ color: pior ? "var(--color-critico)" : "var(--color-ok)" }}>{d > 0 ? "+" : "−"}{num(Math.abs(d), d < 10 && d > -10 ? 1 : 0)}</span>;
}

export function Resultado({ r }: { r: ResultadoCenario }) {
  const eq = r.equipes;
  const max = Math.max(eq.base.nao_coberto_escala, eq.cenario.nao_coberto_escala, 1);
  const regioes = r.periodos[0]?.regioes.map((x) => x.regiao) ?? [];
  return (
    <div className="space-y-4">
      <ul className="space-y-1 border-l-[3px] border-acento bg-neutro px-3 py-2">
        {r.frases.map((f) => <li key={f} className="text-[14px] font-semibold">{f}</li>)}
      </ul>
      {typeof (r.aplicado.equipes as { nota?: string } | undefined)?.nota === "string" && (
        <p className="text-[12px] text-cinza">{(r.aplicado.equipes as { nota: string }).nota}</p>
      )}

      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-tinta text-left text-[11px] uppercase tracking-[0.05em] text-cinza">
            <th className="py-1">Região</th><th className="py-1 text-right">Ocorrências (72 h)</th><th className="py-1 text-right">Índice médio</th>
            <th className="py-1 text-right">Pior momento</th><th className="py-1 text-right">Períodos alto+</th>
          </tr>
        </thead>
        <tbody>
          {r.regioes.map((x) => (
            <tr key={x.regiao} className="border-b border-linha">
              <td className="py-1 font-semibold">{x.regiao}</td>
              <td className="num py-1 text-right">{num(x.ocorrencias_base, 0)} → {num(x.ocorrencias_cenario, 0)} <Variacao antes={x.ocorrencias_base} depois={x.ocorrencias_cenario} /></td>
              <td className="num py-1 text-right">{num(x.indice_medio_base, 0)} → {num(x.indice_medio_cenario, 0)} <Variacao antes={x.indice_medio_base} depois={x.indice_medio_cenario} /></td>
              <td className="py-1 text-right"><SeloNivel nivel={x.nivel_max_base} /> → <SeloNivel nivel={x.nivel_max_cenario} /></td>
              <td className="num py-1 text-right">{x.periodos_alto_base} → {x.periodos_alto_cenario}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div>
        <h4 className="mb-1 text-[11px] font-bold uppercase tracking-[0.06em]">Risco não coberto (agentes-hora ponderados pelo risco)</h4>
        {([["Hoje, escala como está", eq.base.nao_coberto_escala, COR.suave], ["Cenário, escala como está", eq.cenario.nao_coberto_escala, COR.alta],
           ["Cenário, seguindo a recomendação", eq.cenario.nao_coberto_otimizado, COR.ok]] as const).map(([rot, v, cor]) => (
          <div key={rot} className="grid grid-cols-[210px_1fr_70px] items-center gap-2 text-[12px]">
            <span>{rot}</span>
            <span className="h-[12px] bg-neutro"><span className="block h-full" style={{ width: `${(v / max) * 100}%`, background: cor }} /></span>
            <span className="num text-right">{num(v, 0)}</span>
          </div>
        ))}
        {eq.cenario.recomendacoes.length > 0 && (
          <details className="mt-2 text-[12px]">
            <summary className="cursor-pointer font-semibold">Reforços que a recomendação faria no cenário ({eq.cenario.recomendacoes.length})</summary>
            <ul className="mt-1 list-disc space-y-1 pl-5">{eq.cenario.recomendacoes.map((t) => <li key={t}>{t}</li>)}</ul>
          </details>
        )}
      </div>

      <div className="overflow-x-auto">
        <h4 className="mb-1 text-[11px] font-bold uppercase tracking-[0.06em]">Índice de risco por período: cenário (hoje)</h4>
        <table className="text-[11px]">
          <thead><tr><th />{regioes.map((rg) => <th key={rg} className="px-2 py-1 text-left">{rg}</th>)}</tr></thead>
          <tbody>
            {r.periodos.map((p) => (
              <tr key={p.inicio}>
                <td className="whitespace-nowrap pr-2 text-cinza">{p.rotulo}</td>
                {p.regioes.map((x) => (
                  <td key={x.regiao} className="px-[2px] py-[2px]">
                    <span className="num block min-w-[64px] px-2 py-[2px] text-papel rounded-md" title={`Hoje ${x.indice_base}; no cenário ${x.indice_cenario}`}
                          style={{ background: COR_NIVEL[x.nivel_cenario ?? x.nivel_base], outline: x.nivel_cenario !== x.nivel_base ? `2px solid ${COR.texto}` : undefined }}>
                      {num(x.indice_cenario ?? 0, 0)} <span className="opacity-75">({num(x.indice_base, 0)})</span>
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-[11px] text-cinza">Contorno preto: o nível mudou em relação a hoje.</p>
      </div>
      {Array.isArray(r.aplicado.manutencoes) && (
        <div className="text-[12px]">
          <h4 className="mb-1 text-[11px] font-bold uppercase tracking-[0.06em]">Preventivas simuladas</h4>
          <ul className="grid gap-x-4 sm:grid-cols-2">
            {(r.aplicado.manutencoes as { codigo: string; prob_antes: number | null; prob_depois: number | null }[]).map((m) => (
              <li key={m.codigo} className="num">{m.codigo}: {m.prob_antes == null ? "—" : `${num(m.prob_antes * 100, 0)}%`} → {m.prob_depois == null ? "—" : `${num(m.prob_depois * 100, 0)}%`} de chance de falhar em 7 dias</li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-[11px] text-cinza">Simulado a partir de {hora(r.origem)}{r.segundos ? ` em ${num(r.segundos, 1)} s` : ""}. Nada foi alterado no sistema. Dados sintéticos.</p>
    </div>
  );
}

function Salvos({ abrir }: { abrir: (id: number) => void }) {
  const l = useCenarios();
  const rem = useRemoverCenario();
  if (!l.data?.length) return <p className="text-[13px] text-cinza">Nenhum cenário salvo ainda.</p>;
  return (
    <ul className="space-y-2">
      {l.data.map((c) => (
        <li key={c.id} className="border border-linha p-2 text-[13px]">
          <div className="flex items-start justify-between gap-2">
            <button className="text-left font-semibold hover:underline" onClick={() => abrir(c.id)}>{c.nome}</button>
            <button aria-label="Remover cenário" className="text-cinza hover:text-critico" onClick={() => rem.mutate(c.id)}><Trash2 size={14} /></button>
          </div>
          <p className="text-[11px] text-cinza">{c.criado_por} · {hora(c.criado_em)}</p>
          {c.frases[0] && <p className="mt-1 text-[12px]">{c.frases[0]}</p>}
        </li>
      ))}
    </ul>
  );
}

export default function Cenarios() {
  const [p, setP] = useState<CenarioParams>(vazio());
  const [r, setR] = useState<ResultadoCenario | null>(null);
  const [nome, setNome] = useState("");
  const [aberto, setAberto] = useState<number | null>(null);
  const simular = useSimular();
  const salvar = useSalvarCenario();
  const salvo = useCenario(aberto);
  const vazioP = !p.eventos?.length && !p.cancelar_eventos?.length && !p.clima?.length && !p.equipes?.length && !p.equipamentos_fora && !p.manutencoes;
  const rodar = (params = p) => simular.mutate(params, { onSuccess: (x) => { setR(x); setAberto(null); } });
  const atual = aberto != null && salvo.data?.resultado ? salvo.data.resultado : r;
  const erro = simular.error ?? salvar.error;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-[26px] font-bold tracking-[-0.02em]">Cenários "e se"</h1>
        <p className="text-cinza">Mude o futuro das próximas 72 h e veja o efeito nas ocorrências, no risco e nas equipes antes de decidir. Nada é alterado no sistema.</p>
      </div>
      <AvisoTreino />
      <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
        <div className="space-y-3">
          <Construtor p={p} setP={setP} />
          <div className="sticky bottom-0 z-10 flex gap-2 border-t border-linha bg-papel py-2">
            <Botao variante="primario" disabled={vazioP} carregando={simular.isPending} onClick={() => rodar()}><Play size={14} /> Simular</Botao>
            <Botao variante="fantasma" onClick={() => { setP(vazio()); setR(null); setAberto(null); }}><RotateCcw size={14} /> Limpar</Botao>
          </div>
          {erro instanceof ApiError && <p className="text-[13px] text-critico">{erro.erro.mensagem}</p>}
          <Secao titulo="Cenários salvos"><Salvos abrir={setAberto} /></Secao>
        </div>
        <div>
          {simular.isPending && <Carregando texto="Simulando (cerca de 5 s)…" />}
          {!simular.isPending && !atual && (
            <div className="border border-dashed border-linha p-6 text-[13px] text-cinza">
              Monte o cenário à esquerda e clique em Simular. Exemplos: um show de 40 mil pessoas no sábado à noite; chuva forte amanhã cedo;
              duas equipes a menos no Centro; cinco câmeras fora do ar.
            </div>
          )}
          {!simular.isPending && atual && (
            <Secao
              titulo={aberto != null && salvo.data ? `Cenário salvo: ${salvo.data.nome}` : "Resultado"}
              acao={aberto != null && salvo.data?.parametros
                ? <Botao onClick={() => { setP({ ...vazio(), ...salvo.data!.parametros }); rodar({ ...vazio(), ...salvo.data!.parametros }); }}><Play size={14} /> Rodar com os dados de agora</Botao>
                : (
                  <div className="flex gap-2">
                    <input className="campo !w-[200px] !py-1 text-[13px]" placeholder="Nome do cenário" value={nome} onChange={(e) => setNome(e.target.value)} />
                    <Botao disabled={!nome.trim()} carregando={salvar.isPending} onClick={() => salvar.mutate({ nome, parametros: p }, { onSuccess: (c) => { setNome(""); setAberto(c.id); } })}>
                      <Save size={14} /> Salvar
                    </Botao>
                  </div>
                )}
            >
              <Resultado r={atual} />
            </Secao>
          )}
        </div>
      </div>
    </div>
  );
}
