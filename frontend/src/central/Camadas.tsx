import { useMemo, useState } from "react";
import { Layers } from "lucide-react";
import { urlIcone } from "./icones";
import { useTela, type Camada } from "./store";
import { COR_GRAVIDADE, COR_ORGAO, ROTULO_GRAVIDADE, SIMBOLO_GRAVIDADE } from "./visual";
import { COR_NIVEL as COR_RISCO, ROTULO_NIVEL as ROTULO_RISCO } from "../preditivo/formato";

const CAMADAS: [Camada, string, string][] = [
  ["fixos", "Equipamentos fixos", "Radares, câmeras, balanças, cancelas, totens"],
  ["moveis", "Equipamentos móveis", "Viaturas, motos, táxis, escolares, patinetes, autônomos"],
  ["agentes", "Agentes", "Em atividade, na cor do órgão"],
  ["regioes", "Regiões", "Contorno pintado pelo estado"],
  ["calor", "Mapa de calor de alertas", "Concentração nas últimas 24 horas"],
  ["cobertura", "Cobertura de câmeras", "Alcance das operacionais; o que fica em branco é ponto cego"],
  ["ocorrencias", "Ocorrências (24 h)", "Acidentes, alagamentos, furtos...; quanto maior, mais grave"],
  ["risco", "Risco previsto (próximas 6 h)", "Maior índice de risco previsto em cada região; contorno tracejado. Clique para ver a previsão"],
];

/** Camadas (liga e desliga) e legenda: forma = o que é, cor = como está. */
export default function Camadas() {
  const [aberto, setAberto] = useState(false);
  const camadas = useTela((s) => s.camadas);
  const alternar = useTela((s) => s.alternarCamada);
  const icones = useMemo(() => ({
    c: urlIcone("e|c|1|0|R"), q: urlIcone("e|q|1|0|C"), t: urlIcone("e|t|1|0|V"), d: urlIcone("a|CET|0"),
    velho: urlIcone("e|q|1|1|C"), at: urlIcone("a|GCM|1"), grupo: urlIcone("k|4|12|1|0|3|15|1"),
  }), []);
  return (
    <div className="absolute left-2 top-2 z-10 max-w-[300px]">
      <button
        onClick={() => setAberto(!aberto)} aria-expanded={aberto}
        className="inline-flex items-center gap-2 border border-tinta bg-papel px-2 py-[5px] text-[12px] font-semibold shadow-sm"
      >
        <Layers size={14} /> Camadas e legenda
      </button>
      {aberto && (
        <div className="mt-1 max-h-[70vh] overflow-y-auto border border-tinta bg-papel p-3 text-[12px] shadow-[0_6px_20px_rgba(0,0,0,0.15)]">
          <div className="space-y-1">
            {CAMADAS.map(([k, r, d]) => (
              <label key={k} className="flex cursor-pointer gap-2">
                <input type="checkbox" checked={camadas[k]} onChange={() => alternar(k)} className="mt-[2px] accent-[var(--color-acento)]" />
                <span><span className="font-semibold">{r}</span><span className="block text-[11px] text-cinza">{d}</span></span>
              </label>
            ))}
          </div>
          <div className="mt-3 border-t border-linha pt-2">
            <div className="mb-1 font-bold uppercase tracking-[0.05em] text-[11px]">Forma = o que é</div>
            <div className="grid grid-cols-2 gap-1">
              <span className="flex items-center gap-1"><img src={icones.c} width={18} alt="" /> Fiscalização</span>
              <span className="flex items-center gap-1"><img src={icones.q} width={18} alt="" /> Monitoramento</span>
              <span className="flex items-center gap-1"><img src={icones.t} width={18} alt="" /> Veículos</span>
              <span className="flex items-center gap-1"><img src={icones.d} width={16} alt="" /> Agentes</span>
            </div>
            <div className="mb-1 mt-2 font-bold uppercase tracking-[0.05em] text-[11px]">Cor e símbolo = como está</div>
            <ul className="space-y-[2px]">
              {[4, 3, 2, 1, 0].map((g) => (
                <li key={g} className="flex items-center gap-2">
                  <span className="inline-flex h-[14px] w-[14px] items-center justify-center text-[9px] font-bold text-papel" style={{ background: COR_GRAVIDADE[g] }}>{SIMBOLO_GRAVIDADE[g]}</span>
                  {ROTULO_GRAVIDADE[g]}
                </li>
              ))}
            </ul>
            <div className="mt-2 space-y-1">
              <span className="flex items-center gap-2"><img src={icones.velho} width={18} alt="" /> Esmaecido e tracejado: sem sinal há mais de 2× o intervalo esperado</span>
              <span className="flex items-center gap-2"><img src={icones.grupo} width={22} alt="" /> Grupo: o miolo tem a cor da pior situação dentro dele; o anel, a proporção de cada cor. Pulsa se tiver alerta crítico</span>
              <span className="flex items-center gap-2"><img src={icones.at} width={16} alt="" /> Agente em atendimento (contorno amarelo)</span>
            </div>
            {camadas.risco && (
              <div className="mt-2">
                <div className="mb-1 font-bold uppercase tracking-[0.05em] text-[11px]">Risco previsto (tracejado)</div>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {(["MUITO_ALTO", "ALTO", "MODERADO", "BAIXO"] as const).map((n) => (
                    <span key={n} className="flex items-center gap-1">
                      <span className="h-[10px] w-[14px] border-2 border-dashed" style={{ borderColor: COR_RISCO[n], background: `${COR_RISCO[n]}33` }} />
                      {ROTULO_RISCO[n]}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
              {Object.entries(COR_ORGAO).filter(([s]) => s !== "SMT").map(([s, c]) => (
                <span key={s} className="flex items-center gap-1"><span className="h-[9px] w-[9px] rotate-45" style={{ background: c }} />{s}</span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
