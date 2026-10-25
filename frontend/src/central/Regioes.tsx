import { useFiltrosCentral } from "./filtros";
import { caixa } from "./Mapa";
import { useTela } from "./store";
import type { RegiaoSaude } from "./tipos";
import { COR_REGIAO, ROTULO_REGIAO, fmt } from "./visual";

/** Faixa de regiões, da pior para a melhor. Clicar aproxima o mapa e aplica o filtro da região. */
export default function Regioes({ dados, geo, passado, grande }: {
  dados?: RegiaoSaude[];
  geo?: GeoJSON.FeatureCollection;
  passado?: { regiao: string; nota: number; estado: RegiaoSaude["estado"]; motivo: string }[] | null;
  grande?: boolean;
}) {
  const { filtros, definir } = useFiltrosCentral();
  const lista = passado
    ? [...passado].sort((a, b) => a.nota - b.nota).map((r) => ({ ...r, disponibilidade: null, agentes_ativos: null, pico: false, alertas: null }))
    : dados ?? [];
  const escolher = (nome: string) => {
    const ativa = filtros.regiao.length === 1 && filtros.regiao[0] === nome;
    definir({ regiao: ativa ? [] : [nome], bairro_id: [] });
    const f = geo?.features.find((x) => x.properties?.nome === nome);
    if (!ativa && f) useTela.getState().voar({ bbox: caixa(f.geometry) });
    if (ativa) useTela.getState().voar({ lon: -46.62, lat: -23.565, zoom: 11 });
  };
  return (
    <div className="flex h-full gap-[1px] overflow-x-auto bg-linha" role="list" aria-label="Regiões da pior para a melhor">
      {lista.length === 0 && <div className="flex-1 bg-papel p-3 text-cinza">Sem dados de região{passado ? " neste momento" : ""}.</div>}
      {lista.map((r) => {
        const ativa = filtros.regiao.includes(r.regiao);
        return (
          <button
            key={r.regiao} role="listitem" onClick={() => escolher(r.regiao)}
            className={`flex min-w-[210px] flex-1 items-stretch gap-3 bg-papel px-3 py-2 text-left hover:bg-neutro ${ativa ? "outline outline-2 -outline-offset-2 outline-acento" : ""}`}
          >
            <div className="w-[6px] shrink-0" style={{ background: COR_REGIAO[r.estado] }} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className={`font-bold ${grande ? "text-[20px]" : "text-[14px]"}`}>{r.regiao}</span>
                <span className="text-[11px] font-bold uppercase tracking-[0.05em]" style={{ color: COR_REGIAO[r.estado] }}>
                  {ROTULO_REGIAO[r.estado]}{r.pico ? " · pico" : ""}
                </span>
              </div>
              <div className="flex items-baseline gap-2">
                <span className={`cond num font-bold leading-none ${grande ? "text-[44px]" : "text-[30px]"}`} style={{ color: COR_REGIAO[r.estado] }}>{r.nota}</span>
                <span className="line-clamp-2 text-[12px] leading-tight">{r.motivo}</span>
              </div>
              {r.disponibilidade !== null && (
                <div className="num mt-[2px] text-[11px] text-cinza">
                  disp. {fmt(r.disponibilidade, 1)}% · {r.agentes_ativos} agente{r.agentes_ativos === 1 ? "" : "s"}
                  {r.alertas && (r.alertas.critica + r.alertas.alta) > 0 ? ` · ${r.alertas.critica} crít. ${r.alertas.alta} altos` : ""}
                </div>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
