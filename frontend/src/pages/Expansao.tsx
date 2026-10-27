import { useMemo, useState } from "react";
import { Camera, ShieldAlert } from "lucide-react";
import { Carregando, Erro } from "../components/ui";
import { useRegioesGeo } from "../central/api";
import AvisoTreino from "../preditivo/AvisoTreino";
import MapaPontos, { type Ponto } from "../preditivo/MapaPontos";
import { useExpansao } from "../preditivo/api";
import { num } from "../preditivo/formato";

const CRITERIOS = [["combinado", "Ocorrências e furtos"], ["ocorrencias", "Só ocorrências"], ["furtos", "Só furtos de equipamento"]];

export default function Expansao() {
  const [criterio, setCriterio] = useState("combinado");
  const [sel, setSel] = useState<number | null>(null);
  const e = useExpansao(criterio, 10);
  const geo = useRegioesGeo();
  const s = e.data?.sugestoes ?? [];
  const pontos: Ponto[] = useMemo(() => s.map((x) => ({
    id: x.ordem, lon: x.lon, lat: x.lat, raio: 6 + x.pontuacao / 20, alcance_m: e.data?.resumo?.alcance_m ?? 300,
    cor: x.furtos_evitados_ano >= 0.05 ? "#d62828" : "#ff4f00",
    rotulo: `${x.ordem}. ${x.bairro}: ${num(x.ocorrencias_mes)} ocorrências/mês sem câmera`,
  })), [s, e.data?.resumo?.alcance_m]);
  const r = e.data?.resumo;

  return (
    <div>
      <h1 className="text-[26px] font-bold tracking-[-0.02em]">Expansão: onde pôr as próximas câmeras</h1>
      <p className="text-cinza">{e.data?.como_ajuda ?? "Pontos sem cobertura com mais ocorrências e mais risco de furto"}. Dados sintéticos.</p>
      <div className="mt-3"><AvisoTreino /></div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <div className="flex border border-tinta text-[13px] font-semibold">
          {CRITERIOS.map(([v, t]) => (
            <button key={v} onClick={() => { setCriterio(v); setSel(null); }} className={`px-3 py-1 ${criterio === v ? "bg-tinta text-papel" : ""}`}>{t}</button>
          ))}
        </div>
        {r && (
          <span className="text-[13px]">
            Hoje, <b>{num(r.cobertura_hoje_pct ?? 0)}%</b> das ocorrências dos últimos 90 dias aconteceram a menos de {r.alcance_m} m de uma câmera
            em operação. Com as {s.length} sugestões: <b>{num(r.cobertura_com_sugestoes_pct ?? 0)}%</b> (+{num(r.novas_cobertas_mes)} ocorrências
            por mês){r.furtos_evitados_ano >= 0.05 ? ` e cerca de ${num(r.furtos_evitados_ano)} furtos de equipamento a menos por ano` : ""}.
          </span>
        )}
      </div>
      {e.isLoading ? <Carregando texto="Calculando a cobertura da cidade…" /> : e.error ? <Erro erro={e.error} /> : (
        <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
          <div className="relative h-[560px] border border-linha">
            <MapaPontos geo={geo.data} pontos={pontos} selecionado={sel} onSelecionar={setSel} />
          </div>
          <div className="max-h-[560px] space-y-2 overflow-y-auto">
            {e.data?.mensagem && <p className="text-cinza">{e.data.mensagem}</p>}
            {s.map((x) => (
              <button key={x.ordem} onClick={() => setSel(x.ordem)}
                className={`w-full border p-2 text-left text-[13px] ${sel === x.ordem ? "border-tinta bg-neutro" : "border-linha"}`}>
                <div className="flex items-center justify-between gap-2">
                  <b className="inline-flex items-center gap-1"><Camera size={14} /> {x.ordem}. {x.bairro} <span className="font-normal text-cinza">({x.regiao})</span></b>
                  <span className="num text-[12px]">pontuação {num(x.pontuacao, 0)}</span>
                </div>
                <ul className="mt-1 list-disc pl-4 text-[12px]">
                  {x.motivos.map((m) => <li key={m}>{m}</li>)}
                </ul>
                {x.furtos_evitados_ano >= 0.05 && (
                  <div className="mt-1 inline-flex items-center gap-1 text-[12px] text-critico"><ShieldAlert size={12} /> Ponto de furto de equipamento</div>
                )}
              </button>
            ))}
            {e.data && (
              <details className="border border-linha p-2 text-[12px]">
                <summary className="cursor-pointer font-semibold">Como as sugestões são calculadas</summary>
                <p className="mt-1">{e.data.metodo}.</p>
                <p className="mt-1">Com base em: {e.data.dados_considerados.join("; ")}.</p>
                <p className="mt-1">É uma sugestão para avaliar no local (poste, energia, visada), não uma decisão.</p>
              </details>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
