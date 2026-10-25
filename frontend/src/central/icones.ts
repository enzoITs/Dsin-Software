import type maplibregl from "maplibre-gl";
import { COR_GRAVIDADE, SIMBOLO_GRAVIDADE, corOrgao } from "./visual";

/** Ícones do mapa desenhados em canvas sob demanda (evento styleimagemissing).
 * Não dependem de fontes nem de arquivos externos: funcionam sem internet.
 *
 * e|forma|gravidade|velho|prefixo  ponto de equipamento: forma = categoria, cor = situação,
 *                                   letra do tipo dentro, símbolo da situação no canto
 * a|orgao|emAtendimento             agente: losango na cor do órgão
 * k|gravidade|texto|p4|p3|p2|p1|p0  grupo: miolo na cor da pior situação, anel com a proporção de cada cor
 */

const PR = 2; // pixel ratio

function tela(lado: number) {
  const c = document.createElement("canvas");
  c.width = c.height = lado * PR;
  const g = c.getContext("2d")!;
  g.scale(PR, PR);
  return { c, g };
}

function caminhoForma(g: CanvasRenderingContext2D, forma: string, cx: number, cy: number, r: number) {
  g.beginPath();
  if (forma === "q") g.rect(cx - r * 0.86, cy - r * 0.86, r * 1.72, r * 1.72);
  else if (forma === "t") {
    g.moveTo(cx, cy - r * 1.05);
    g.lineTo(cx + r * 1.05, cy + r * 0.8);
    g.lineTo(cx - r * 1.05, cy + r * 0.8);
    g.closePath();
  } else if (forma === "d") {
    g.moveTo(cx, cy - r);
    g.lineTo(cx + r, cy);
    g.lineTo(cx, cy + r);
    g.lineTo(cx - r, cy);
    g.closePath();
  } else g.arc(cx, cy, r, 0, Math.PI * 2);
}

function equipamento(forma: string, gravidade: number, velho: boolean, prefixo: string) {
  const L = 30;
  const { c, g } = tela(L);
  const cx = 14, cy = 15, r = 10;
  caminhoForma(g, forma, cx, cy, r);
  g.globalAlpha = velho ? 0.45 : 1;
  g.fillStyle = COR_GRAVIDADE[gravidade];
  g.fill();
  g.globalAlpha = 1;
  g.lineWidth = 2;
  g.strokeStyle = "#ffffff";
  g.stroke();
  caminhoForma(g, forma, cx, cy, r + 1.4);
  g.lineWidth = 1;
  g.strokeStyle = "#111111";
  if (velho) g.setLineDash([2.5, 2]);
  g.stroke();
  g.setLineDash([]);
  g.fillStyle = gravidade === 2 ? "#111" : "#fff";
  g.font = "bold 10px Helvetica, Arial, sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(prefixo.slice(0, 1), cx, forma === "t" ? cy + 2.5 : cy + 0.5);
  // Símbolo da situação no canto (acessibilidade: não depende só da cor)
  const sim = SIMBOLO_GRAVIDADE[gravidade];
  g.beginPath();
  g.arc(L - 6, 6, 5.2, 0, Math.PI * 2);
  g.fillStyle = "#111";
  g.fill();
  g.fillStyle = "#fff";
  g.font = "bold 8px Helvetica, Arial, sans-serif";
  g.fillText(sim, L - 6, 6.5);
  return c;
}

function agente(orgao: string, atendimento: boolean) {
  const L = 26;
  const { c, g } = tela(L);
  const cx = 13, cy = 13;
  if (atendimento) {
    caminhoForma(g, "d", cx, cy, 12);
    g.fillStyle = "#111";
    g.fill();
  }
  caminhoForma(g, "d", cx, cy, 8.5);
  g.fillStyle = corOrgao(orgao);
  g.fill();
  g.lineWidth = 2;
  g.strokeStyle = atendimento ? "#ffd400" : "#fff";
  g.stroke();
  g.fillStyle = "#fff";
  g.beginPath();
  g.arc(cx, cy, 2.2, 0, Math.PI * 2);
  g.fill();
  return c;
}

/** Grupo: o miolo tem a cor da pior situação dentro dele (um furto nunca fica escondido num grupo verde)
 * e o anel mostra a proporção de cada cor, para o grupo dizer também o quanto está bem. */
function grupo(gravidade: number, texto: string, partes: number[]) {
  const r = texto.length <= 2 ? 15 : texto.length === 3 ? 18 : 21;
  const L = r * 2 + 6;
  const { c, g } = tela(L);
  const cx = L / 2, cy = L / 2;
  g.beginPath();
  g.arc(cx, cy, r + 2, 0, Math.PI * 2);
  g.fillStyle = "rgba(255,255,255,0.92)";
  g.fill();
  // anel de proporções (do pior para o melhor, começando no topo)
  const soma = partes.reduce((a, b) => a + b, 0) || 1;
  let ang = -Math.PI / 2;
  for (const gv of [4, 3, 2, 1, 0]) {
    const fr = (partes[gv] ?? 0) / soma;
    if (fr <= 0) continue;
    g.beginPath();
    g.moveTo(cx, cy);
    g.arc(cx, cy, r, ang, ang + fr * Math.PI * 2);
    g.closePath();
    g.fillStyle = COR_GRAVIDADE[gv];
    g.fill();
    ang += fr * Math.PI * 2;
  }
  // miolo na cor da pior situação
  const miolo = r * 0.62;
  g.beginPath();
  g.arc(cx, cy, miolo + 1.5, 0, Math.PI * 2);
  g.fillStyle = "#fff";
  g.fill();
  g.beginPath();
  g.arc(cx, cy, miolo, 0, Math.PI * 2);
  g.fillStyle = COR_GRAVIDADE[gravidade];
  g.fill();
  g.beginPath();
  g.arc(cx, cy, r, 0, Math.PI * 2);
  g.lineWidth = 1;
  g.strokeStyle = "#111";
  g.stroke();
  g.fillStyle = gravidade === 2 ? "#111" : "#fff";
  g.font = `bold ${texto.length > 3 ? 10 : 11}px Helvetica, Arial, sans-serif`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(texto, cx, cy + 0.5);
  return c;
}

export function instalarIcones(mapa: maplibregl.Map) {
  mapa.on("styleimagemissing", (e) => {
    const id = e.id;
    if (mapa.hasImage(id)) return;
    const p = id.split("|");
    let c: HTMLCanvasElement | null = null;
    if (p[0] === "e") c = equipamento(p[1], Number(p[2]), p[3] === "1", p[4] ?? "");
    else if (p[0] === "a") c = agente(p[1], p[2] === "1");
    else if (p[0] === "k") c = grupo(Number(p[1]), p[2] ?? "", p.slice(3).map(Number).reverse());
    if (!c) return;
    const img = c.getContext("2d")!.getImageData(0, 0, c.width, c.height);
    mapa.addImage(id, img, { pixelRatio: PR });
  });
}

/** Miniatura para a legenda (mesmo desenho do mapa). */
export function urlIcone(id: string): string {
  const p = id.split("|");
  const c = p[0] === "a" ? agente(p[1], p[2] === "1") : p[0] === "k" ? grupo(Number(p[1]), p[2], p.slice(3).map(Number).reverse()) : equipamento(p[1], Number(p[2]), p[3] === "1", p[4] ?? "");
  return c.toDataURL();
}
