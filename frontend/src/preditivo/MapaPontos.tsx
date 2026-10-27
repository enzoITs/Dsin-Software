import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { COR, MAPA_FUNDO, MAPA_RASTER } from "../lib/cores";

const CENTRO: [number, number] = [-46.62, -23.565];

export interface Ponto { id: number; lon: number; lat: number; cor: string; raio: number; rotulo: string; alcance_m?: number }

interface Props {
  geo?: GeoJSON.FeatureCollection;
  pontos: Ponto[];
  selecionado: number | null;
  onSelecionar: (id: number) => void;
}

/** Mapa com pontos (sugestões de câmera, equipamentos em risco) sobre o contorno das regiões. Sem rótulos de texto: funciona offline. */
export default function MapaPontos({ geo, pontos, selecionado, onSelecionar }: Props) {
  const div = useRef<HTMLDivElement>(null);
  const mapa = useRef<maplibregl.Map | null>(null);
  const [pronto, setPronto] = useState(false);
  const cb = useRef(onSelecionar);
  cb.current = onSelecionar;

  useEffect(() => {
    if (!div.current) return;
    const m = new maplibregl.Map({
      container: div.current, center: CENTRO, zoom: 10.4, attributionControl: { compact: true },
      style: {
        version: 8,
        sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap" } },
        layers: [
          { id: "fundo", type: "background", paint: { "background-color": MAPA_FUNDO } },
          { id: "osm", type: "raster", source: "osm", paint: { ...MAPA_RASTER } },
        ],
      },
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => {
      m.addSource("regioes", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "borda", type: "line", source: "regioes", paint: { "line-color": COR.texto, "line-width": 0.8, "line-opacity": 0.6 } });
      m.addSource("alcance", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      // Alcance aproximado (raio em metros convertido para pixels no zoom atual)
      m.addLayer({ id: "alcance", type: "circle", source: "alcance", paint: {
        "circle-radius": ["interpolate", ["exponential", 2], ["zoom"], 10, ["/", ["get", "alcance"], 150], 16, ["/", ["get", "alcance"], 2.3]],
        "circle-color": ["get", "cor"], "circle-opacity": 0.12, "circle-stroke-color": ["get", "cor"], "circle-stroke-width": 1 } });
      m.addSource("pontos", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "pontos", type: "circle", source: "pontos", paint: {
        "circle-radius": ["get", "raio"], "circle-color": ["get", "cor"], "circle-stroke-color": COR.fundo,
        "circle-stroke-width": ["get", "borda"] } });
      const dica = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "dica-mapa" });
      m.on("click", "pontos", (e) => { const id = e.features?.[0]?.properties?.id; if (id != null) cb.current(Number(id)); });
      m.on("mousemove", "pontos", (e) => {
        m.getCanvas().style.cursor = "pointer";
        const t = e.features?.[0]?.properties?.rotulo;
        if (t) dica.setLngLat(e.lngLat).setText(String(t)).addTo(m);
      });
      m.on("mouseleave", "pontos", () => { m.getCanvas().style.cursor = ""; dica.remove(); });
      setPronto(true);
    });
    mapa.current = m;
    return () => m.remove();
  }, []);

  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto) return;
    if (geo) (m.getSource("regioes") as GeoJSONSource).setData(geo);
    const feats = (comAlcance: boolean) => pontos.filter((p) => !comAlcance || p.alcance_m).map((p) => ({
      type: "Feature" as const, geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] },
      properties: { id: p.id, cor: p.cor, raio: p.raio, rotulo: p.rotulo, alcance: p.alcance_m ?? 0, borda: p.id === selecionado ? 3 : 1 },
    }));
    (m.getSource("pontos") as GeoJSONSource).setData({ type: "FeatureCollection", features: feats(false) });
    (m.getSource("alcance") as GeoJSONSource).setData({ type: "FeatureCollection", features: feats(true) });
    const sel = pontos.find((p) => p.id === selecionado);
    if (sel) m.easeTo({ center: [sel.lon, sel.lat], zoom: Math.max(m.getZoom(), 13) });
  }, [geo, pontos, selecionado, pronto]);

  return <div className="absolute inset-0"><div ref={div} className="h-full w-full" /></div>;
}
