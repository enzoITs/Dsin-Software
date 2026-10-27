import { useEffect, useRef } from "react";
import maplibregl, { type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { COR, MAPA_FUNDO, MAPA_RASTER } from "../lib/cores";

// Tiles do OpenStreetMap. Sem internet, o mapa fica com fundo neutro e o ponto continua editável.
export const ESTILO_OSM: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap",
      maxzoom: 19,
    },
  },
  layers: [
    { id: "fundo", type: "background", paint: { "background-color": MAPA_FUNDO } },
    { id: "osm", type: "raster", source: "osm", paint: { ...MAPA_RASTER } },
  ],
};

function elementoMarcador(cor: string) {
  const el = document.createElement("div");
  el.style.cssText = `width:18px;height:18px;background:${cor};border:2px solid #fff;outline:1px solid #111;cursor:grab`;
  return el;
}

interface Props {
  lon: number | null;
  lat: number | null;
  centro?: [number, number];
  editavel?: boolean;
  onMover?: (lon: number, lat: number) => void;
  altura?: number;
  cor?: string;
}

export default function MapaPonto({ lon, lat, centro, editavel, onMover, altura = 320, cor = COR.acento }: Props) {
  const div = useRef<HTMLDivElement>(null);
  const mapa = useRef<maplibregl.Map | null>(null);
  const marcador = useRef<maplibregl.Marker | null>(null);
  const cb = useRef(onMover);
  cb.current = onMover;

  useEffect(() => {
    if (!div.current) return;
    const inicio: [number, number] = lon != null && lat != null ? [lon, lat] : centro ?? [-46.634, -23.5505];
    const m = new maplibregl.Map({ container: div.current, style: ESTILO_OSM, center: inicio, zoom: lon != null ? 15 : 11, attributionControl: { compact: true } });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapa.current = m;
    if (editavel) {
      m.on("click", (e) => {
        colocar(e.lngLat.lng, e.lngLat.lat);
        cb.current?.(e.lngLat.lng, e.lngLat.lat);
      });
    }
    return () => { m.remove(); mapa.current = null; marcador.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function colocar(x: number, y: number) {
    const m = mapa.current;
    if (!m) return;
    if (!marcador.current) {
      marcador.current = new maplibregl.Marker({ element: elementoMarcador(cor), draggable: !!editavel }).setLngLat([x, y]).addTo(m);
      marcador.current.on("dragend", () => {
        const p = marcador.current!.getLngLat();
        cb.current?.(p.lng, p.lat);
      });
    } else {
      marcador.current.setLngLat([x, y]);
    }
  }

  useEffect(() => {
    if (lon == null || lat == null) {
      marcador.current?.remove();
      marcador.current = null;
      return;
    }
    colocar(lon, lat);
    const m = mapa.current;
    if (m && !m.getBounds().contains([lon, lat])) m.easeTo({ center: [lon, lat], zoom: Math.max(m.getZoom(), 14) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lon, lat]);

  useEffect(() => {
    if (centro && lon == null && mapa.current) mapa.current.easeTo({ center: centro, zoom: 11 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centro?.[0], centro?.[1]]);

  return <div ref={div} style={{ height: altura }} className="w-full border border-linha" />;
}
