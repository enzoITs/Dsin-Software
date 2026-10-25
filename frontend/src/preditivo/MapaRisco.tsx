import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { COR_NIVEL, ROTULO_NIVEL } from "./formato";
import type { RegiaoHora } from "./tipos";

const CENTRO: [number, number] = [-46.62, -23.565];

interface Props {
  geo?: GeoJSON.FeatureCollection;
  regioes: RegiaoHora[];
  selecionada: number | null;
  onSelecionar: (id: number) => void;
}

/** Regiões pintadas pelo índice de risco (P3) da hora escolhida. */
export default function MapaRisco({ geo, regioes, selecionada, onSelecionar }: Props) {
  const div = useRef<HTMLDivElement>(null);
  const mapa = useRef<maplibregl.Map | null>(null);
  const [pronto, setPronto] = useState(false);
  const cb = useRef(onSelecionar);
  cb.current = onSelecionar;

  useEffect(() => {
    if (!div.current) return;
    const m = new maplibregl.Map({
      container: div.current, center: CENTRO, zoom: 10.6, attributionControl: { compact: true },
      style: {
        version: 8,
        sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap" } },
        layers: [
          { id: "fundo", type: "background", paint: { "background-color": "#f2f2f3" } },
          { id: "osm", type: "raster", source: "osm", paint: { "raster-saturation": -0.9, "raster-opacity": 0.6 } },
        ],
      },
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => {
      m.addSource("regioes", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "risco", type: "fill", source: "regioes", paint: { "fill-color": ["get", "cor"], "fill-opacity": ["get", "opacidade"] } });
      m.addLayer({ id: "borda", type: "line", source: "regioes", paint: { "line-color": "#111", "line-width": ["get", "borda"] } });
      // Sem fontes do servidor de mapas (funciona offline): o nome aparece numa dica ao passar o mouse.
      const dica = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "dica-mapa" });
      m.on("click", "risco", (e) => { const id = e.features?.[0]?.properties?.regiao_id; if (id != null) cb.current(Number(id)); });
      m.on("mousemove", "risco", (e) => {
        m.getCanvas().style.cursor = "pointer";
        const t = e.features?.[0]?.properties?.rotulo;
        if (t) dica.setLngLat(e.lngLat).setText(String(t)).addTo(m);
      });
      m.on("mouseleave", "risco", () => { m.getCanvas().style.cursor = ""; dica.remove(); });
      setPronto(true);
    });
    mapa.current = m;
    return () => m.remove();
  }, []);

  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto || !geo) return;
    const por = new Map(regioes.map((r) => [r.regiao, r]));
    const feats = geo.features.map((f) => {
      const r = por.get(String(f.properties?.nome));
      return {
        ...f,
        properties: {
          ...f.properties, regiao_id: r?.regiao_id ?? null,
          cor: r ? COR_NIVEL[r.nivel] : "#cccccc", opacidade: r ? 0.25 + Math.min(r.indice, 100) / 100 * 0.45 : 0.1,
          borda: r && r.regiao_id === selecionada ? 3 : 0.8,
          rotulo: r ? `${f.properties?.nome}: risco ${Math.round(r.indice)} (${ROTULO_NIVEL[r.nivel].toLowerCase()})` : String(f.properties?.nome ?? ""),
        },
      };
    });
    (m.getSource("regioes") as GeoJSONSource).setData({ type: "FeatureCollection", features: feats });
  }, [geo, regioes, selecionada, pronto]);

  // O MapLibre põe position: relative no contêiner; o posicionamento absoluto fica num invólucro.
  return <div className="absolute inset-0"><div ref={div} className="h-full w-full" /></div>;
}
