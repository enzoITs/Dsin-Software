import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Presentation, X } from "lucide-react";

/** X6: modo apresentação. Um roteiro guiado pelas telas, com o que mostrar e o que dizer em cada passo.
 *  Abre pelo botão "Apresentar" ou com ?apresentar na URL. Avança com PageDown / seta do passador e volta com PageUp. */

export interface Passo { rota: string; titulo: string; mostrar: string[]; dizer: string }

export const ROTEIRO: Passo[] = [
  { rota: "/previsao/briefing", titulo: "1. O dia começa com o briefing",
    mostrar: ["Resumo: momento mais crítico do dia", "Reforços para decidir e manutenção preventiva", "Acertômetro de ontem"],
    dizer: "Às 6 h o gestor já sabe onde e quando o risco vai ser maior, o que precisa decidir e quanto o sistema acertou ontem." },
  { rota: "/amanha", titulo: "2. Amanhã: sexta às 20 h, Centro em risco muito alto",
    mostrar: ["Arraste o controle até sexta, 20 h", "Centro em vermelho: show grande no Pacaembu + noite de sexta", "Clique na região: cartão com os três títulos"],
    dizer: "O que estamos prevendo, com base em quê e como isso ajuda. Cada fator aparece com o peso que teve." },
  { rota: "/previsao/equipes", titulo: "3. A recomendação: reforçar o Centro",
    mostrar: ["Risco não coberto antes e depois", "Equipes vindas de regiões mais calmas, só no período", "Aceitar (o turno é movido) ou rejeitar com motivo"],
    dizer: "O sistema recomenda; quem decide é a pessoa. Tudo fica registrado." },
  { rota: "/previsao/cenarios", titulo: "4. E se...?",
    mostrar: ["Cancelar o show: o risco do Centro cai", "Derrubar 5 câmeras: a cobertura cai e o índice sobe", "Salvar o cenário com um nome"],
    dizer: "Antes de decidir, o gestor testa a decisão. Os mesmos modelos rodam com e sem a mudança." },
  { rota: "/previsao/equipamentos", titulo: "5. Equipamentos em risco",
    mostrar: ["Ranking de 7 dias: câmeras de uma marca, antigas, depois de chuva", "Abrir OS preventivas em lote"],
    dizer: "De cada 50 equipamentos que o modelo aponta, vários falham na semana. Pela média histórica, quase nenhum." },
  { rota: "/central", titulo: "6 e 7. Na central: anomalia e alerta preventivo",
    mostrar: ["Radar que passou a registrar 80% menos infrações (gráfico esperado × observado)", "Alerta com a faixa \"Previsão\": acontece daqui a horas", "Camada \"Risco previsto (próximas 6 h)\""],
    dizer: "A central passa a ver o que ainda não aconteceu, com antecedência, e o que está estranho mesmo sem estar quebrado." },
  { rota: "/previsao/tendencias", titulo: "Extra: tendências",
    mostrar: ["Leste abaixo da meta de disponibilidade", "\"Seguindo o P1\" volta para cima da meta", "Carga de manutenção das próximas 4 semanas"],
    dizer: "Semanas antes, dá para ver a disponibilidade caindo e planejar técnicos e peças." },
  { rota: "/previsao/expansao", titulo: "Extra: furtos e expansão",
    mostrar: ["Brás e Itaquera: mais risco de furto, de madrugada, longe de câmeras", "Onde uma câmera nova cobriria mais"],
    dizer: "Prevê lugares e equipamentos, nunca pessoas." },
  { rota: "/previsao/confianca", titulo: "8. Confiança e padrões descobertos",
    mostrar: ["Cada modelo ao lado da média histórica", "Monitor dos modelos em operação", "Padrões plantados × descobertos"],
    dizer: "Os modelos não leram os padrões que plantamos nos dados e acharam quase todos. A confiança baixa é dita abertamente." },
  { rota: "/previsao/copiloto", titulo: "9. Copiloto",
    mostrar: ["\"Onde o risco é maior amanhã?\"", "\"E se chover forte amanhã de manhã?\"", "A resposta cita os cartões"],
    dizer: "Funciona com ou sem IA: sem internet, responde às perguntas prontas com as mesmas consultas." },
  { rota: "/previsao/etica", titulo: "Fechamento",
    mostrar: ["Nunca pessoas; o humano decide; incerteza à mostra"],
    dizer: "PROMETHEUS agora enxerga o que pode acontecer amanhã, explica por quê e diz o que fazer." },
];

const CHAVE = "atalaia.apresentacao";

function ler(): number | null {
  try {
    const v = localStorage.getItem(CHAVE);
    return v == null ? null : Number(v);
  } catch {
    return null;
  }
}

function gravar(v: number | null) {
  try {
    if (v == null) localStorage.removeItem(CHAVE);
    else localStorage.setItem(CHAVE, String(v));
  } catch { /* sem armazenamento: o modo funciona só nesta aba */ }
}

export function iniciarApresentacao() {
  gravar(0);
  window.dispatchEvent(new Event("atalaia-apresentacao"));
}

export default function ModoApresentacao() {
  const nav = useNavigate();
  const loc = useLocation();
  const [passo, setPasso] = useState<number | null>(() => (new URLSearchParams(window.location.search).has("apresentar") ? 0 : ler()));
  const [aberto, setAberto] = useState(true);

  useEffect(() => {
    const abrir = () => { setPasso(0); setAberto(true); };
    window.addEventListener("atalaia-apresentacao", abrir);
    return () => window.removeEventListener("atalaia-apresentacao", abrir);
  }, []);

  useEffect(() => {
    gravar(passo);
    if (passo != null && ROTEIRO[passo] && loc.pathname !== ROTEIRO[passo].rota) nav(ROTEIRO[passo].rota);
    // só ao mudar de passo: o apresentador pode navegar à vontade dentro do passo
  }, [passo]);

  useEffect(() => {
    if (passo == null) return;
    const tecla = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement | null;
      if (alvo && ["INPUT", "TEXTAREA", "SELECT"].includes(alvo.tagName)) return;
      if (e.key === "PageDown") { e.preventDefault(); setPasso((p) => Math.min((p ?? 0) + 1, ROTEIRO.length - 1)); }
      if (e.key === "PageUp") { e.preventDefault(); setPasso((p) => Math.max((p ?? 0) - 1, 0)); }
      if (e.key === "Escape") setAberto((a) => !a);
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [passo]);

  if (passo == null) return null;
  const p = ROTEIRO[passo];
  return (
    <div className="fixed bottom-3 left-3 z-50 w-[380px] max-w-[calc(100vw-24px)] border border-acento bg-neutro text-tinta shadow-xl rounded-xl"
         role="region" aria-label="Modo apresentação">
      <div className="flex items-center justify-between gap-2 px-3 py-2 text-[12px]">
        <span className="inline-flex items-center gap-1 font-semibold"><Presentation size={14} /> Passo {passo + 1} de {ROTEIRO.length}</span>
        <span className="flex items-center gap-1">
          <button aria-label="Passo anterior" disabled={passo === 0} onClick={() => setPasso(passo - 1)} className="p-1 disabled:opacity-40"><ChevronLeft size={16} /></button>
          <button aria-label="Próximo passo" disabled={passo === ROTEIRO.length - 1} onClick={() => setPasso(passo + 1)} className="p-1 disabled:opacity-40"><ChevronRight size={16} /></button>
          <button aria-label={aberto ? "Recolher" : "Abrir"} onClick={() => setAberto(!aberto)} className="p-1">{aberto ? <ChevronDown size={16} /> : <ChevronUp size={16} />}</button>
          <button aria-label="Sair da apresentação" onClick={() => setPasso(null)} className="p-1"><X size={16} /></button>
        </span>
      </div>
      {aberto && (
        <div className="border-t border-linha px-3 pb-3 pt-2">
          <div className="text-[15px] font-bold">{p.titulo}</div>
          <ul className="mt-1 list-disc pl-4 text-[13px]">{p.mostrar.map((m) => <li key={m}>{m}</li>)}</ul>
          <p className="mt-2 border-l-[3px] border-acento pl-2 text-[13px] italic">"{p.dizer}"</p>
          <p className="mt-2 text-[11px] opacity-60">PageDown / PageUp para avançar e voltar · Esc recolhe</p>
        </div>
      )}
    </div>
  );
}
