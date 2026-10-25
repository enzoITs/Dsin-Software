import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import circle from "@turf/circle";
import { ouvirEventos } from "./eventos";
import { instalarIcones } from "./icones";
import { useTela } from "./store";
import type { EstadoCentral, Feicao, LinhaDoTempo, PropsAgente, PropsEquip, RegiaoSaude } from "./tipos";
import { COR_REGIAO, RANK_NIVEL, gravidade } from "./visual";
import { SITUACAO } from "../lib/rotulos";

const CENTRO: [number, number] = [-46.62, -23.565];
const TRILHA_MAX = 8; // últimas posições (15 s cada): uns 2 minutos de rastro
const FC = (features: unknown[] = []) => ({ type: "FeatureCollection" as const, features }) as GeoJSON.FeatureCollection;

function estilo(escuro: boolean): StyleSpecification {
  return {
    version: 8,
    sources: {
      osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap", maxzoom: 19 },
    },
    layers: [
      { id: "fundo", type: "background", paint: { "background-color": escuro ? "#15171a" : "#f2f2f3" } },
      {
        id: "osm", type: "raster", source: "osm",
        paint: escuro
          ? { "raster-saturation": -1, "raster-brightness-max": 0.32, "raster-contrast": 0.1 }
          : { "raster-saturation": -0.85, "raster-opacity": 0.75 },
      },
    ],
  };
}

interface Props {
  estado?: EstadoCentral;
  semFiltro: boolean;
  regioesGeo?: GeoJSON.FeatureCollection;
  saude?: RegiaoSaude[];
  calor?: GeoJSON.FeatureCollection;
  linha?: LinhaDoTempo;
  area: [number, number][];
  onArea: (pontos: [number, number][]) => void;
  escuro?: boolean;
  alcanceCameraM?: number;
}

export default function Mapa({ estado, semFiltro, regioesGeo, saude, calor, linha, area, onArea, escuro = false, alcanceCameraM = 120 }: Props) {
  const div = useRef<HTMLDivElement>(null);
  const mapa = useRef<maplibregl.Map | null>(null);
  const [pronto, setPronto] = useState(false);
  const equip = useRef(new Map<number, Feicao<PropsEquip>>());
  const agentes = useRef(new Map<number, Feicao<PropsAgente>>());
  const trilhas = useRef(new Map<number, [number, number][]>());
  const sujo = useRef(false);
  const desenho = useRef<[number, number][]>([]);
  const ultimaCobertura = useRef(0);

  const camadas = useTela((s) => s.camadas);
  const selecao = useTela((s) => s.selecao);
  const desenhando = useTela((s) => s.desenhando);
  const voo = useTela((s) => s.voo);

  // Linha do tempo: situação e alertas no momento escolhido
  const passado = useMemo(() => {
    if (!linha) return null;
    const sit = new Map(linha.equipamentos.map((e) => [e.i, e.s]));
    const nivel = new Map<number, number>();
    for (const a of linha.alertas) {
      if (a.equipamento_id == null) continue;
      nivel.set(a.equipamento_id, Math.max(nivel.get(a.equipamento_id) ?? 0, RANK_NIVEL[a.nivel]));
    }
    return { sit, nivel, depois: new Set(linha.criados_depois) };
  }, [linha]);

  // ---------- montar o mapa ----------
  useEffect(() => {
    if (!div.current) return;
    const m = new maplibregl.Map({
      container: div.current, style: estilo(escuro), center: CENTRO, zoom: 11, attributionControl: { compact: true },
      doubleClickZoom: true,
    });
    mapa.current = m;
    instalarIcones(m);
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

    m.on("load", () => {
      m.addSource("regioes", { type: "geojson", data: FC(), promoteId: "nome" });
      m.addSource("calor", { type: "geojson", data: FC() });
      m.addSource("cobertura", { type: "geojson", data: FC() });
      m.addSource("area", { type: "geojson", data: FC() });
      m.addSource("trilhas", { type: "geojson", data: FC() });
      m.addSource("equip", {
        type: "geojson", data: FC(), cluster: true, clusterRadius: 46, clusterMaxZoom: 14,
        clusterProperties: {
          g: ["max", ["get", "g"]],
          c4: ["+", ["case", [">=", ["get", "n"], 4], 1, 0]],
          s0: ["+", ["case", ["==", ["get", "g"], 0], 1, 0]],
          s1: ["+", ["case", ["==", ["get", "g"], 1], 1, 0]],
          s2: ["+", ["case", ["==", ["get", "g"], 2], 1, 0]],
          s3: ["+", ["case", ["==", ["get", "g"], 3], 1, 0]],
          s4: ["+", ["case", ["==", ["get", "g"], 4], 1, 0]],
        },
      });
      m.addSource("agentes", { type: "geojson", data: FC() });
      m.addSource("sel", { type: "geojson", data: FC() });

      const corEstado = ["match", ["coalesce", ["feature-state", "estado"], "normal"],
        "critica", COR_REGIAO.critica, "atencao", COR_REGIAO.atencao, COR_REGIAO.normal] as unknown as string;
      m.addLayer({ id: "regioes-fill", type: "fill", source: "regioes", paint: {
        "fill-color": corEstado,
        "fill-opacity": ["match", ["coalesce", ["feature-state", "estado"], "normal"], "critica", 0.16, "atencao", 0.12, 0.03] as unknown as number,
      } });
      m.addLayer({ id: "regioes-line", type: "line", source: "regioes", paint: {
        "line-color": corEstado, "line-width": ["match", ["coalesce", ["feature-state", "estado"], "normal"], "normal", 1.2, 2.6] as unknown as number,
        "line-opacity": 0.9,
      } });
      m.addLayer({ id: "calor", type: "heatmap", source: "calor", maxzoom: 16, paint: {
        "heatmap-weight": ["get", "w"], "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 9, 0.8, 15, 2.2],
        "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 9, 14, 15, 40],
        "heatmap-opacity": 0.75,
        "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"], 0, "rgba(0,0,0,0)", 0.2, "#fde68a", 0.5, "#f59e0b", 0.8, "#ea6c13", 1, "#b91c1c"],
      } });
      m.addLayer({ id: "cobertura", type: "fill", source: "cobertura", paint: { "fill-color": "#2563eb", "fill-opacity": 0.16 } });
      m.addLayer({ id: "cobertura-borda", type: "line", source: "cobertura", minzoom: 13, paint: { "line-color": "#2563eb", "line-width": 0.6, "line-opacity": 0.5 } });
      m.addLayer({ id: "area-fill", type: "fill", source: "area", paint: { "fill-color": "#ff4f00", "fill-opacity": 0.06 } });
      m.addLayer({ id: "area-line", type: "line", source: "area", paint: { "line-color": "#ff4f00", "line-width": 2, "line-dasharray": [2, 1.5] } });
      m.addLayer({ id: "trilhas", type: "line", source: "trilhas", minzoom: 12.5, layout: { "line-cap": "round" }, paint: {
        "line-color": "#334155", "line-width": 2, "line-opacity": 0.35,
      } });
      m.addLayer({ id: "pulso", type: "circle", source: "equip",
        filter: ["any", [">", ["coalesce", ["get", "c4"], 0], 0], [">=", ["coalesce", ["get", "n"], 0], 4]],
        paint: { "circle-color": "#d62828", "circle-opacity": 0.4, "circle-radius": 14, "circle-stroke-width": 0 } });
      m.addLayer({ id: "grupos", type: "symbol", source: "equip", filter: ["has", "point_count"], layout: {
        // proporções arredondadas em passos de 5% (menos imagens diferentes)
        "icon-image": ["concat", "k|", ["to-string", ["get", "g"]], "|", ["to-string", ["get", "point_count_abbreviated"]],
          ...[4, 3, 2, 1, 0].flatMap((k) => ["|", ["to-string", ["max", ["case", [">", ["get", `s${k}`], 0], 1, 0],
            ["round", ["/", ["*", 20, ["get", `s${k}`]], ["get", "point_count"]]]]]])] as unknown as string,
        "icon-allow-overlap": true, "symbol-sort-key": ["get", "g"],
      } });
      m.addLayer({ id: "pontos", type: "symbol", source: "equip", filter: ["!", ["has", "point_count"]], layout: {
        "icon-image": ["concat", "e|", ["get", "f"], "|", ["to-string", ["get", "g"]], "|", ["to-string", ["get", "v"]], "|", ["get", "p"]],
        "icon-allow-overlap": true, "icon-ignore-placement": true, "symbol-sort-key": ["get", "g"],
        "icon-size": ["interpolate", ["linear"], ["zoom"], 10, 0.75, 14, 0.95, 17, 1.15],
      } });
      m.addLayer({ id: "agentes", type: "symbol", source: "agentes", layout: {
        "icon-image": ["concat", "a|", ["get", "o"], "|", ["case", ["to-boolean", ["get", "at"]], "1", "0"]],
        "icon-allow-overlap": true, "icon-ignore-placement": true,
        "icon-size": ["interpolate", ["linear"], ["zoom"], 10, 0.5, 13, 0.75, 15, 1],
        "symbol-sort-key": ["case", ["to-boolean", ["get", "at"]], 1, 0],
      } });
      m.addLayer({ id: "sel", type: "circle", source: "sel", paint: {
        "circle-radius": 19, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#ff4f00", "circle-stroke-width": 3,
      } });
      setPronto(true);
    });

    // Pulsar os críticos
    let raf = 0;
    const animar = (t: number) => {
      if (m.getLayer("pulso")) {
        const f = (t % 1600) / 1600;
        m.setPaintProperty("pulso", "circle-radius", 12 + f * 20);
        m.setPaintProperty("pulso", "circle-opacity", 0.55 * (1 - f));
      }
      raf = requestAnimationFrame(animar);
    };
    raf = requestAnimationFrame(animar);

    // Interação
    m.on("click", "grupos", async (e) => {
      const f = e.features?.[0];
      if (!f) return;
      const src = m.getSource("equip") as GeoJSONSource;
      const zoom = await src.getClusterExpansionZoom(f.properties!.cluster_id as number);
      m.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom: zoom + 0.3 });
    });
    m.on("click", "pontos", (e) => {
      if (useTela.getState().desenhando) return;
      const p = e.features?.[0]?.properties as PropsEquip | undefined;
      if (p) useTela.getState().selecionar({ tipo: "equipamento", id: p.i });
    });
    m.on("click", "agentes", (e) => {
      if (useTela.getState().desenhando) return;
      const p = e.features?.[0]?.properties as PropsAgente | undefined;
      if (p) useTela.getState().selecionar({ tipo: "agente", id: p.i });
    });
    const dica = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14, className: "dica-mapa" });
    for (const camada of ["pontos", "agentes", "grupos"]) {
      m.on("mouseenter", camada, () => { m.getCanvas().style.cursor = "pointer"; });
      m.on("mouseleave", camada, () => { m.getCanvas().style.cursor = ""; dica.remove(); });
    }
    m.on("mousemove", "pontos", (e) => {
      const p = e.features?.[0]?.properties as PropsEquip | undefined;
      if (!p) return;
      const sit = SITUACAO[p.s]?.rotulo ?? p.s;
      dica.setLngLat(e.lngLat).setHTML(`<b>${p.c}</b> · ${sit}${p.v ? " · sinal atrasado" : ""}${p.n >= 3 ? " · alerta aberto" : ""}`).addTo(m);
    });
    m.on("mousemove", "agentes", (e) => {
      const p = e.features?.[0]?.properties as PropsAgente | undefined;
      if (!p) return;
      dica.setLngLat(e.lngLat).setHTML(`<b>${p.nome}</b> · ${p.o}${p.at ? " · em atendimento" : ""}`).addTo(m);
    });
    m.on("mousemove", "grupos", (e) => {
      const p = e.features?.[0]?.properties;
      if (!p) return;
      const partes = [[4, "vermelho"], [3, "laranja"], [2, "amarelo"], [1, "verde"], [0, "cinza"]]
        .filter(([k]) => p[`s${k}`]).map(([k, r]) => `${p[`s${k}`]} ${r}`).join(" · ");
      dica.setLngLat(e.lngLat).setHTML(`<b>${p.point_count} equipamentos</b>${p.c4 ? ` · <b>${p.c4} com alerta crítico</b>` : ""}<br>${partes}`).addTo(m);
    });

    return () => { cancelAnimationFrame(raf); m.remove(); mapa.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- desenhar os dados ----------
  const desenhar = useRef<() => void>(() => {});
  desenhar.current = () => {
    const m = mapa.current;
    if (!m || !pronto) return;
    const { camadas: cam, selecao: sel } = useTela.getState();
    const lista: Feicao<PropsEquip>[] = [];
    for (const f of equip.current.values()) {
      const movel = f.properties.m === 1;
      if ((movel && !cam.moveis) || (!movel && !cam.fixos)) continue;
      if (passado) {
        if (passado.depois.has(f.properties.i)) continue;
        const s = passado.sit.get(f.properties.i) ?? f.properties.s;
        const n = passado.nivel.get(f.properties.i) ?? 0;
        if (s !== f.properties.s || n !== f.properties.n) {
          let g = gravidade(s, n);
          if (g === 1 && f.properties.g === 2 && f.properties.n < 2) g = 2; // amarelo de manutenção
          lista.push({ ...f, properties: { ...f.properties, s, n, g, v: 0 } });
          continue;
        }
      }
      lista.push(f);
    }
    (m.getSource("equip") as GeoJSONSource).setData(FC(lista));
    (m.getSource("agentes") as GeoJSONSource).setData(FC(passado ? [] : [...agentes.current.values()]));
    const linhas = [];
    if (!passado && cam.moveis) {
      for (const [id, pts] of trilhas.current) {
        if (pts.length > 1 && equip.current.has(id)) linhas.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pts } });
      }
    }
    (m.getSource("trilhas") as GeoJSONSource).setData(FC(linhas));
    let ponto: [number, number] | null = null;
    if (sel?.tipo === "equipamento") ponto = equip.current.get(sel.id)?.geometry.coordinates ?? null;
    if (sel?.tipo === "agente") ponto = agentes.current.get(sel.id)?.geometry.coordinates ?? null;
    (m.getSource("sel") as GeoJSONSource).setData(FC(ponto ? [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: ponto } }] : []));
    if (cam.cobertura && Date.now() - ultimaCobertura.current > 10_000) {
      ultimaCobertura.current = Date.now();
      const circulos = [];
      for (const f of lista) {
        const p = f.properties;
        if (p.p === "CAM" && p.s === "operacional" && p.n < 3 && !p.v) {
          circulos.push(circle(f.geometry.coordinates, alcanceCameraM / 1000, { steps: 20, units: "kilometers" }));
        }
      }
      (m.getSource("cobertura") as GeoJSONSource).setData(FC(circulos));
    }
    sujo.current = false;
  };

  // Estado inicial (e a cada troca de filtro)
  useEffect(() => {
    if (!estado) return;
    equip.current = new Map(estado.equipamentos.features.map((f) => [f.properties.i, f]));
    agentes.current = new Map(estado.agentes.features.map((f) => [f.properties.i, f]));
    trilhas.current = new Map();
    ultimaCobertura.current = 0;
    desenhar.current();
  }, [estado, pronto]);

  useEffect(() => { ultimaCobertura.current = 0; desenhar.current(); }, [camadas, selecao, passado, pronto]);

  // Mudanças em tempo real: aplicadas na hora, desenhadas no máximo a cada 0,7 s
  useEffect(() => {
    const parar = ouvirEventos((eventos) => {
      for (const ev of eventos) {
        if (ev.tipo === "equipamentos") {
          for (const f of ev.feicoes) {
            if (equip.current.has(f.properties.i) || semFiltro) equip.current.set(f.properties.i, f);
          }
          for (const id of ev.removidos) equip.current.delete(id);
          sujo.current = true;
        } else if (ev.tipo === "posicoes") {
          for (const [id, x, y] of ev.equipamentos ?? []) {
            const f = equip.current.get(id);
            if (!f) continue;
            f.geometry = { type: "Point", coordinates: [x, y] };
            const t = trilhas.current.get(id) ?? [];
            t.push([x, y]);
            if (t.length > TRILHA_MAX) t.shift();
            trilhas.current.set(id, t);
          }
          for (const [id, x, y] of ev.agentes ?? []) {
            const f = agentes.current.get(id);
            if (f) {
              f.geometry = { type: "Point", coordinates: [x, y] };
              f.properties = { ...f.properties, pe: new Date().toISOString() };
            }
          }
          sujo.current = true;
        } else if (ev.tipo === "alerta" && ev.alerta.agente) {
          const f = agentes.current.get(ev.alerta.agente.id);
          if (f) {
            const ativo = !ev.alerta.resolvido_em;
            f.properties = { ...f.properties, at: ativo ? ev.alerta.id : f.properties.at === ev.alerta.id ? null : f.properties.at };
            sujo.current = true;
          }
        }
      }
    });
    const t = setInterval(() => { if (sujo.current) desenhar.current(); }, 700);
    return () => { parar(); clearInterval(t); };
  }, [semFiltro]);

  // Regiões: contorno pintado pelo estado (ao vivo ou no momento da linha do tempo)
  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto || !regioesGeo) return;
    (m.getSource("regioes") as GeoJSONSource).setData(regioesGeo);
  }, [regioesGeo, pronto]);
  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto || !regioesGeo) return;
    const estados = linha ? linha.regioes : saude;
    for (const r of estados ?? []) m.setFeatureState({ source: "regioes", id: r.regiao }, { estado: r.estado });
  }, [saude, linha, regioesGeo, pronto]);

  // Mapa de calor
  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto) return;
    (m.getSource("calor") as GeoJSONSource).setData(calor ?? FC());
  }, [calor, pronto]);

  // Visibilidade das camadas
  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto) return;
    const vis = (id: string, v: boolean) => m.getLayer(id) && m.setLayoutProperty(id, "visibility", v ? "visible" : "none");
    vis("regioes-fill", camadas.regioes);
    vis("regioes-line", camadas.regioes);
    vis("calor", camadas.calor);
    vis("cobertura", camadas.cobertura);
    vis("cobertura-borda", camadas.cobertura);
    vis("agentes", camadas.agentes);
  }, [camadas, pronto]);

  // Área do filtro e desenho de uma nova área
  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto) return;
    const mostrar = (pts: [number, number][], fechar: boolean) => {
      const feats = [];
      if (pts.length >= 2) feats.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: fechar ? [...pts, pts[0]] : pts } });
      if (fechar && pts.length >= 3) feats.push({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[...pts, pts[0]]] } });
      (m.getSource("area") as GeoJSONSource).setData(FC(feats));
    };
    if (!desenhando) {
      mostrar(area, true);
      return;
    }
    desenho.current = [];
    mostrar([], false);
    m.getCanvas().style.cursor = "crosshair";
    m.doubleClickZoom.disable();
    const clique = (e: maplibregl.MapMouseEvent) => {
      desenho.current = [...desenho.current, [e.lngLat.lng, e.lngLat.lat]];
      mostrar(desenho.current, false);
    };
    const terminar = (e: maplibregl.MapMouseEvent) => {
      e.preventDefault();
      const pts = desenho.current.filter((p, i, a) => i === 0 || p[0] !== a[i - 1][0] || p[1] !== a[i - 1][1]);
      useTela.getState().setDesenhando(false);
      if (pts.length >= 3) onArea(pts);
    };
    const tecla = (e: KeyboardEvent) => { if (e.key === "Escape") useTela.getState().setDesenhando(false); };
    m.on("click", clique);
    m.on("dblclick", terminar);
    window.addEventListener("keydown", tecla);
    return () => {
      m.off("click", clique);
      m.off("dblclick", terminar);
      window.removeEventListener("keydown", tecla);
      m.getCanvas().style.cursor = "";
      setTimeout(() => m.doubleClickZoom.enable(), 300);
    };
  }, [desenhando, area, pronto, onArea]);

  // Voar até um ponto ou região
  useEffect(() => {
    const m = mapa.current;
    if (!m || !voo) return;
    if (voo.bbox) m.fitBounds([[voo.bbox[0], voo.bbox[1]], [voo.bbox[2], voo.bbox[3]]], { padding: 50, duration: 900 });
    else if (voo.lon != null && voo.lat != null) m.flyTo({ center: [voo.lon, voo.lat], zoom: voo.zoom ?? Math.max(m.getZoom(), 15.5), duration: 900 });
  }, [voo]);

  return (
    <div className={`absolute inset-0 ${escuro ? "mapa-escuro" : ""}`}>
      <div ref={div} className="h-full w-full" />
    </div>
  );
}

/** Caixa que envolve uma geometria de região (para aproximar o mapa). */
export function caixa(geom: GeoJSON.Geometry): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const visitar = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") {
      const [x, y] = c as number[];
      x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
    } else if (Array.isArray(c)) c.forEach(visitar);
  };
  visitar((geom as GeoJSON.Polygon).coordinates);
  return [x0, y0, x1, y1];
}
