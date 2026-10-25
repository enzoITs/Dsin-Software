/** Som curto e aviso do navegador para alertas críticos (Web Audio, sem arquivo de áudio). */

let ctx: AudioContext | null = null;
let ultimo = 0;

export function tocarAlarme() {
  const agora = Date.now();
  if (agora - ultimo < 1500) return; // vários críticos juntos: um som só
  ultimo = agora;
  try {
    ctx = ctx ?? new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    const t0 = ctx.currentTime;
    for (const [i, freq] of [880, 660, 880].entries()) {
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = "square";
      osc.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, t0 + i * 0.16);
      g.gain.exponentialRampToValueAtTime(0.08, t0 + i * 0.16 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + i * 0.16 + 0.14);
      osc.connect(g).connect(ctx.destination);
      osc.start(t0 + i * 0.16);
      osc.stop(t0 + i * 0.16 + 0.15);
    }
  } catch {
    /* navegador sem áudio */
  }
}

/** Liberado por um clique do usuário (política de autoplay dos navegadores). */
export function liberarSom() {
  try {
    ctx = ctx ?? new AudioContext();
    void ctx.resume();
  } catch { /* sem áudio */ }
  if ("Notification" in window && Notification.permission === "default") void Notification.requestPermission();
}

export function avisar(titulo: string, corpo: string) {
  if (!("Notification" in window) || Notification.permission !== "granted" || document.visibilityState === "visible") return;
  try { new Notification(titulo, { body: corpo, tag: "atalaia-critico" }); } catch { /* sem aviso */ }
}
