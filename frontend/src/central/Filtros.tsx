import type { ReactNode } from "react";
import { PenLine, X } from "lucide-react";
import { useBairros, useCidades, useOrgaos, useTipos } from "../api/hooks";
import { ORDEM_SITUACAO, SITUACAO } from "../lib/rotulos";
import { useFiltrosCentral } from "./filtros";
import { useTela } from "./store";
import { COR_NIVEL, ROTULO_NIVEL } from "./visual";

const REGIOES = ["Centro", "Norte", "Sul", "Leste", "Oeste"];

function Grupo({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <fieldset className="border-t border-linha py-2">
      <legend className="sr-only">{titulo}</legend>
      <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.06em] text-cinza" aria-hidden>{titulo}</div>
      {children}
    </fieldset>
  );
}

function Marca({ marcado, onChange, children, cor }: { marcado: boolean; onChange: () => void; children: ReactNode; cor?: string }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 py-[2px] text-[13px] hover:text-tinta">
      <input type="checkbox" checked={marcado} onChange={onChange} className="accent-[var(--color-acento)]" />
      {cor && <span className="h-[9px] w-[9px] shrink-0" style={{ background: cor }} />}
      <span className="truncate">{children}</span>
    </label>
  );
}

export default function Filtros() {
  const { filtros: f, alternar, definir, limpar, total } = useFiltrosCentral();
  const tipos = useTipos().data ?? [];
  const orgaos = useOrgaos().data ?? [];
  const cidade = (useCidades().data ?? []).find((c) => c.tem_lista_bairros)?.id;
  const bairros = useBairros(cidade).data ?? [];
  const desenhando = useTela((s) => s.desenhando);
  const setDesenhando = useTela((s) => s.setDesenhando);
  const bairrosVisiveis = f.regiao.length ? bairros.filter((b) => b.regiao && f.regiao.includes(b.regiao)) : bairros;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-baseline justify-between px-3 pb-1 pt-3">
        <h2 className="text-[13px] font-bold uppercase tracking-[0.06em]">Filtros{total ? <span className="num ml-1 text-acento">{total}</span> : null}</h2>
        {total > 0 && <button className="text-[12px] text-cinza underline hover:text-tinta" onClick={limpar}>Limpar</button>}
      </div>
      <p className="px-3 pb-2 text-[11px] leading-snug text-cinza">Valem para o mapa, os indicadores, as regiões e as listas. Ficam no endereço da página.</p>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        <Grupo titulo="Região">
          {REGIOES.map((r) => <Marca key={r} marcado={f.regiao.includes(r)} onChange={() => alternar("regiao", r)}>{r}</Marca>)}
          <select
            className="campo mt-1 !py-1 text-[13px]" aria-label="Bairro" value={f.bairro_id[0] ?? ""}
            onChange={(e) => definir({ bairro_id: e.target.value ? [Number(e.target.value)] : [] })}
          >
            <option value="">Todos os bairros</option>
            {bairrosVisiveis.map((b) => <option key={b.id} value={b.id}>{b.nome}</option>)}
          </select>
        </Grupo>
        <Grupo titulo="Criticidade">
          {(["critica", "alta", "media"] as const).map((n) => (
            <Marca key={n} cor={COR_NIVEL[n]} marcado={f.nivel.includes(n)} onChange={() => alternar("nivel", n)}>Com alerta {ROTULO_NIVEL[n].toLowerCase()}</Marca>
          ))}
          <Marca marcado={f.sem_sinal} onChange={() => definir({ sem_sinal: !f.sem_sinal })}>Sem sinal (falha silenciosa)</Marca>
        </Grupo>
        <Grupo titulo="Tipo de equipamento">
          {tipos.map((t) => <Marca key={t.id} marcado={f.tipo_id.includes(t.id)} onChange={() => alternar("tipo_id", t.id)}>{t.nome}</Marca>)}
        </Grupo>
        <Grupo titulo="Situação">
          {ORDEM_SITUACAO.map((s) => (
            <Marca key={s} cor={SITUACAO[s].cor} marcado={f.situacao.includes(s)} onChange={() => alternar("situacao", s)}>{SITUACAO[s].rotulo}</Marca>
          ))}
        </Grupo>
        <Grupo titulo="Órgão responsável">
          {orgaos.map((o) => <Marca key={o.id} marcado={f.orgao_id.includes(o.id)} onChange={() => alternar("orgao_id", o.id)}>{o.sigla} · {o.nome}</Marca>)}
        </Grupo>
        <Grupo titulo="Manutenção">
          {[["imediata", "Imediata"], ["vencida", "Vencida"], ["proxima", "Próxima em 7 dias"]].map(([v, r]) => (
            <Marca key={v} marcado={f.manutencao.includes(v)} onChange={() => alternar("manutencao", v)}>{r}</Marca>
          ))}
        </Grupo>
        <Grupo titulo="Score de saúde">
          <label className="block text-[13px]">
            <span className="flex justify-between"><span>Abaixo de</span><span className="num font-semibold">{f.score_max ?? "—"}</span></span>
            <input
              type="range" min={10} max={100} step={5} value={f.score_max ?? 100} className="w-full accent-[var(--color-acento)]"
              onChange={(e) => definir({ score_max: Number(e.target.value) >= 100 ? null : Number(e.target.value) })}
              aria-label="Score de saúde máximo"
            />
          </label>
        </Grupo>
        <Grupo titulo="Área desenhada">
          {desenhando ? (
            <p className="text-[12px] leading-snug">Clique no mapa para marcar os cantos; <b>duplo clique</b> termina. Esc cancela.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              <button className="inline-flex items-center gap-1 border border-tinta px-2 py-1 text-[12px] font-semibold hover:bg-neutro" onClick={() => setDesenhando(true)}>
                <PenLine size={13} /> {f.area.length ? "Redesenhar" : "Desenhar no mapa"}
              </button>
              {f.area.length > 0 && (
                <button className="inline-flex items-center gap-1 px-2 py-1 text-[12px] text-cinza hover:text-tinta" onClick={() => definir({ area: [] })}>
                  <X size={13} /> Tirar área
                </button>
              )}
            </div>
          )}
        </Grupo>
      </div>
    </div>
  );
}
