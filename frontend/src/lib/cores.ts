/** Paleta do tema preto e amarelo, para onde CSS não chega (gráficos, mapas, canvas).
 *  Os mesmos valores estão em src/index.css (tokens do Tailwind). */
export const COR = {
  fundo: "#111110",
  superficie: "#1A1A18",
  texto: "#ECE9E1",
  suave: "#A8A49A",
  linha: "#2E2D29",
  grade: "#2A2926",
  referencia: "#5C5950",
  acento: "#F2C230",
  ok: "#3DBE6E",
  atencao: "#E0A800",
  alta: "#F07A2B",
  critico: "#E5484D",
  inativo: "#8A877F",
  previsao: "#B9A3FF",
} as const;

/** Fundo e contorno dos mapas no tema escuro. */
export const MAPA_FUNDO = "#15171a";
export const MAPA_RASTER = { "raster-saturation": -1, "raster-brightness-max": 0.32, "raster-contrast": 0.1 } as const;
