import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Minimize2, SlidersHorizontal } from "lucide-react";
import { SeletorPerfil } from "../components/Layout";
import {
  useAlertasCentral, useCalor, useEstadoCentral, useIndicadores, useLinhaDoTempo, useOcorrenciasRecentes, useRegioesGeo,
  useRegioesSaude,
} from "../central/api";
import Camadas from "../central/Camadas";
import { useConexaoEventos } from "../central/eventos";
import Ferramentas from "../central/Ferramentas";
import Ficha from "../central/Ficha";
import Filtros from "../central/Filtros";
import { useFiltrosCentral } from "../central/filtros";
import Indicadores from "../central/Indicadores";
import LinhaTempo from "../central/LinhaTempo";
import Mapa, { caixa } from "../central/Mapa";
import PainelAlertas, { CardAlerta } from "../central/PainelAlertas";
import Regioes from "../central/Regioes";
import RegistrarOcorrencia from "../central/RegistrarOcorrencia";
import { useTela } from "../central/store";
import { COR_REGIAO, ROTULO_REGIAO } from "../central/visual";

function Conexao() {
  const c = useTela((s) => s.conexao);
  const cor = c === "ao_vivo" ? "var(--color-ok)" : c === "caiu" ? "var(--color-critico)" : "var(--color-atencao)";
  const texto = c === "ao_vivo" ? "Ao vivo" : c === "caiu" ? "Sem conexão: reconectando" : "Conectando";
  return (
    <span className="inline-flex items-center gap-[6px] text-[12px] font-semibold" role="status">
      <span className={`h-[9px] w-[9px] rounded-full ${c === "ao_vivo" ? "animate-pulse" : ""}`} style={{ background: cor }} />{texto}
    </span>
  );
}

/** Modo sala de situação: tela cheia para TV, sem menus, alternando entre a cidade e as regiões em atenção. */
function useRodizio(ativo: boolean, regioes: { regiao: string; estado: string }[] | undefined, geo?: GeoJSON.FeatureCollection) {
  const [vista, setVista] = useState("Cidade inteira");
  useEffect(() => {
    if (!ativo) return;
    let i = 0;
    const passo = () => {
      const foco = (regioes ?? []).filter((r) => r.estado !== "normal").map((r) => r.regiao);
      const ordem = ["Cidade inteira", ...foco];
      const atual = ordem[i % ordem.length];
      i += 1;
      setVista(atual);
      const f = geo?.features.find((x) => x.properties?.nome === atual);
      if (f) useTela.getState().voar({ bbox: caixa(f.geometry) });
      else useTela.getState().voar({ lon: -46.62, lat: -23.565, zoom: 11 });
    };
    passo();
    const t = setInterval(passo, 15_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ativo, geo, JSON.stringify((regioes ?? []).map((r) => [r.regiao, r.estado]))]);
  return vista;
}

export default function Central() {
  useConexaoEventos();
  const [sp, setSp] = useSearchParams();
  const sala = sp.get("sala") === "1";
  const { params, chave, filtros, definir, total } = useFiltrosCentral();
  const [filtrosAbertos, setFiltrosAbertos] = useState(true);
  const camadas = useTela((s) => s.camadas);
  const minutos = useTela((s) => s.minutos);
  const linhaAberta = useTela((s) => s.linhaAberta);
  const registrando = useTela((s) => s.registrando);

  const estado = useEstadoCentral(params, chave);
  const geo = useRegioesGeo();
  const ind = useIndicadores(params, chave, minutos === 0);
  const saude = useRegioesSaude(params, chave);
  const calor = useCalor(params, chave, camadas.calor);
  const ocorrencias = useOcorrenciasRecentes(camadas.ocorrencias);
  const linha = useLinhaDoTempo(params, chave, linhaAberta ? minutos : 0);
  const passado = linhaAberta && minutos > 0 ? linha.data : undefined;
  const criticos = useAlertasCentral(params, chave, { nivel_alerta: ["critica", "alta"] }, 8);
  const vista = useRodizio(sala, saude.data, geo.data);

  const onArea = useCallback((pts: [number, number][]) => definir({ area: pts }), [definir]);
  const sairSala = () => {
    setSp((a) => { const n = new URLSearchParams(a); n.delete("sala"); return n; });
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  };
  useEffect(() => {
    if (!sala) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") sairSala(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sala]);

  const regiaoVista = useMemo(() => saude.data?.find((r) => r.regiao === vista), [saude.data, vista]);

  return (
    <div className={`flex h-screen flex-col overflow-hidden ${sala ? "sala" : ""}`}>
      {/* Cabeçalho */}
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-tinta px-3 py-2">
        <div className="flex items-baseline gap-2">
          <Link to="/" className="text-[20px] font-bold tracking-[-0.02em]">Atalaia</Link>
          <span className="h-[9px] w-[9px] bg-acento" aria-hidden />
          <span className="text-[12px] font-semibold uppercase tracking-[0.06em]">Central de operações</span>
        </div>
        <Conexao />
        {sala ? (
          <>
            <span className="text-[14px]">
              Mostrando: <b>{vista}</b>
              {regiaoVista && <span style={{ color: COR_REGIAO[regiaoVista.estado] }}> · {ROTULO_REGIAO[regiaoVista.estado]} — {regiaoVista.motivo}</span>}
            </span>
            <span className="num ml-auto text-[22px] font-bold">{new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>
            <button onClick={sairSala} className="inline-flex items-center gap-1 border border-linha px-2 py-1 text-[12px]"><Minimize2 size={13} /> Sair (Esc)</button>
          </>
        ) : (
          <>
            <Link to="/amanha" className="ml-auto text-[13px] font-semibold underline">Amanhã (previsões)</Link>
            <div><Ferramentas /></div>
            <SeletorPerfil />
          </>
        )}
      </header>

      <Indicadores dados={ind.data} passado={passado?.indicadores ?? null} grande={sala} />

      {/* Filtros | mapa | alertas */}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {!sala && filtrosAbertos && (
          <aside className="hidden w-[230px] shrink-0 border-r border-linha md:block"><Filtros /></aside>
        )}
        <main className="relative min-h-[320px] flex-1">
          <Mapa
            estado={estado.data} semFiltro={total === 0} regioesGeo={geo.data} saude={saude.data} calor={calor.data}
            linha={passado} area={filtros.area} onArea={onArea} escuro={sala}
            ocorrencias={camadas.ocorrencias && !passado ? ocorrencias.data?.itens : undefined}
          />
          {!sala && (
            <>
              <Camadas />
              <button
                onClick={() => setFiltrosAbertos(!filtrosAbertos)}
                className="absolute bottom-8 left-2 z-10 hidden items-center gap-1 border border-tinta bg-papel px-2 py-[5px] text-[12px] font-semibold md:inline-flex"
              >
                <SlidersHorizontal size={13} /> {filtrosAbertos ? "Esconder filtros" : `Filtros${total ? ` (${total})` : ""}`}
              </button>
            </>
          )}
          {estado.isFetching && <div className="absolute left-1/2 top-2 z-10 -translate-x-1/2 bg-tinta px-2 py-1 text-[12px] text-papel">Carregando o mapa…</div>}
          {estado.isError && <div className="absolute left-1/2 top-2 z-10 -translate-x-1/2 border border-critico bg-papel px-3 py-2 text-[13px]">Não foi possível carregar o mapa. A API está no ar?</div>}
          {!sala && <Ficha />}
          {!sala && registrando && <RegistrarOcorrencia />}
          {!sala && linhaAberta && <LinhaTempo dados={linha.data} carregando={linha.isFetching} />}
          {passado && <div className="absolute left-1/2 top-2 z-10 -translate-x-1/2 bg-acento px-3 py-1 text-[12px] font-semibold text-white">Vendo o passado: há {minutos} min</div>}
        </main>
        <aside className={`flex min-h-0 shrink-0 flex-col border-l border-linha md:w-[370px] ${sala ? "md:w-[440px]" : "h-[45vh] md:h-auto"}`}>
          {sala ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="border-b border-tinta px-3 py-2 text-[13px] font-bold uppercase tracking-[0.06em]">Críticos e altos</div>
              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto bg-neutro p-2">
                {(criticos.data?.itens ?? []).map((a) => <CardAlerta key={a.id} a={a} compacto />)}
                {criticos.data?.itens.length === 0 && <p className="p-3 text-[18px]">Nenhum alerta crítico ou alto.</p>}
              </div>
            </div>
          ) : <PainelAlertas />}
        </aside>
      </div>

      <footer className={`shrink-0 border-t border-tinta ${sala ? "h-[120px]" : "h-[92px]"}`}>
        <Regioes dados={saude.data} geo={geo.data} passado={passado ? passado.regioes : null} grande={sala} />
      </footer>
    </div>
  );
}
