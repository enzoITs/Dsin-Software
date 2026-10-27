import { Fragment, type ReactNode } from "react";

/** Markdown mínimo das respostas do copiloto: parágrafos, listas com "-", **negrito** e [prev_123] como link do cartão. */
function inline(texto: string, abrir: (id: number) => void): ReactNode[] {
  const partes = texto.split(/(\*\*[^*]+\*\*|\[prev_\d+\])/g).filter(Boolean);
  return partes.map((p, i) => {
    const prev = p.match(/^\[prev_(\d+)\]$/);
    if (prev) {
      return (
        <button key={i} onClick={() => abrir(Number(prev[1]))} title="Abrir o cartão de previsão"
          className="mx-[2px] inline border border-linha bg-neutro px-1 align-baseline text-[11px] font-semibold text-previsao hover:border-previsao">
          cartão
        </button>
      );
    }
    if (p.startsWith("**") && p.endsWith("**")) return <b key={i}>{p.slice(2, -2)}</b>;
    return <Fragment key={i}>{p}</Fragment>;
  });
}

export default function TextoRico({ texto, abrir }: { texto: string; abrir: (id: number) => void }) {
  const blocos: ReactNode[] = [];
  let lista: string[] = [];
  const fecharLista = () => {
    if (lista.length) {
      blocos.push(<ul key={blocos.length} className="list-disc space-y-1 pl-5">{lista.map((l, i) => <li key={i}>{inline(l, abrir)}</li>)}</ul>);
      lista = [];
    }
  };
  for (const linha of texto.split("\n")) {
    const t = linha.trim();
    if (/^[-*] /.test(t)) { lista.push(t.slice(2)); continue; }
    fecharLista();
    if (!t) continue;
    if (t.startsWith("#")) blocos.push(<p key={blocos.length} className="font-bold">{inline(t.replace(/^#+\s*/, ""), abrir)}</p>);
    else blocos.push(<p key={blocos.length}>{inline(t, abrir)}</p>);
  }
  fecharLista();
  return <div className="space-y-2">{blocos}</div>;
}
