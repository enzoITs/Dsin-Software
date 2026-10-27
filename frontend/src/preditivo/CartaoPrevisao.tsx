import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, Info, PencilLine, ShieldCheck, X } from "lucide-react";
import { ApiError } from "../api/client";
import { Botao } from "../components/ui";
import { useDecidir } from "./api";
import { COR_NIVEL, ROTULO_NIVEL, dataHora, efeitoTexto, faixaTexto, valorPrincipal } from "./formato";
import type { Cartao } from "./tipos";
import { COR } from "../lib/cores";

const SEM_DECISAO = new Set(["NENHUMA", "VER_PLANEJAMENTO", "CEDER_EQUIPES"]);

function Titulo({ children }: { children: string }) {
  return <h4 className="mb-2 text-[11px] font-bold uppercase tracking-[0.08em] text-cinza">{children}</h4>;
}

export function SeloNivel({ nivel }: { nivel: string | null }) {
  if (!nivel) return null;
  return (
    <span className="inline-flex items-center gap-[6px] whitespace-nowrap text-[12px] font-semibold">
      <span className="inline-block h-[9px] w-[9px]" style={{ background: COR_NIVEL[nivel] ?? COR.inativo }} />
      {ROTULO_NIVEL[nivel] ?? nivel}
    </span>
  );
}

function Fatores({ c }: { c: Cartao }) {
  const max = Math.max(...c.fatores.map((f) => Math.abs(f.efeito)), 1e-9);
  return (
    <ul className="space-y-[6px]">
      {c.fatores.map((f, i) => (
        <li key={i} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
          <span className="text-[13px]">{f.descricao}</span>
          <span className="num text-right text-[12px] font-semibold" style={{ color: f.efeito > 0 ? "var(--color-acento)" : "var(--color-ok)" }}>
            {efeitoTexto(c.unidade, f.efeito)}
          </span>
          <span className="col-span-2 h-[5px] bg-neutro">
            <span className="block h-full" style={{
              width: `${(Math.abs(f.efeito) / max) * 100}%`,
              background: f.efeito > 0 ? "var(--color-acento)" : "var(--color-ok)",
            }} />
          </span>
        </li>
      ))}
    </ul>
  );
}

function Decisao({ c, onDecidido }: { c: Cartao; onDecidido?: () => void }) {
  const decidir = useDecidir();
  const [modo, setModo] = useState<null | "ajustar" | "rejeitar">(null);
  const [motivo, setMotivo] = useState("");
  const [prioridade, setPrioridade] = useState("media");
  const acao = c.acao_recomendada;
  const rec = c.recomendacao;
  if (!acao) return null;
  const decidida = rec && rec.estado !== "pendente";
  const enviar = (tipo: "aceitar" | "ajustar" | "rejeitar") =>
    decidir.mutate(
      {
        previsaoId: c.previsao_id, acao: tipo, motivo: motivo || undefined,
        parametros: tipo === "ajustar" ? { ajuste: motivo, ...(acao.tipo.includes("ORDEM") || acao.tipo.includes("ROTA") ? { prioridade } : {}) } : undefined,
      },
      { onSuccess: () => { setModo(null); setMotivo(""); onDecidido?.(); } },
    );
  const erro = decidir.error instanceof ApiError ? decidir.error.erro.mensagem : null;
  const execucao = rec?.resultado?.execucao as Record<string, unknown> | undefined;
  return (
    <div className="border border-tinta p-3">
      <div className="text-[11px] font-bold uppercase tracking-[0.08em] text-cinza">Ação recomendada</div>
      <p className="mt-1 text-[14px] font-semibold">{acao.texto}</p>
      {acao.tipo === "VER_PLANEJAMENTO" && <Link to="/previsao/equipes" className="mt-2 inline-block text-[13px] underline">Abrir o planejamento de equipes</Link>}
      {decidida ? (
        <div className="mt-2 text-[13px]">
          <b>{rec!.estado === "aceita" ? "Aceita" : rec!.estado === "ajustada" ? "Ajustada" : rec!.estado === "rejeitada" ? "Rejeitada" : "Expirada"}</b>
          {rec!.decidido_por && <> por {rec!.decidido_por}</>}{rec!.decidido_em && <> em {dataHora(rec!.decidido_em)}</>}
          {rec!.motivo && <div className="text-cinza">Motivo: {rec!.motivo}</div>}
          {execucao?.ordem_servico_id != null && (
            <div className="text-cinza">Ordem de serviço nº {String(execucao.ordem_servico_id)}{execucao.ja_existia ? " (já estava aberta)" : " aberta"}.</div>
          )}
          {Array.isArray(execucao?.equipes_movidas) && (
            <div className="text-cinza">{(execucao!.equipes_movidas as unknown[]).length} turno(s) movido(s) na escala.</div>
          )}
        </div>
      ) : !SEM_DECISAO.has(acao.tipo) && (
        <>
          {modo && (
            <div className="mt-2 space-y-2">
              {modo === "ajustar" && (acao.tipo.includes("ORDEM") || acao.tipo.includes("ROTA")) && (
                <label className="block text-[12px]">Prioridade da ordem de serviço
                  <select className="campo mt-1" value={prioridade} onChange={(e) => setPrioridade(e.target.value)}>
                    <option value="baixa">Baixa</option><option value="media">Média</option><option value="alta">Alta</option>
                    <option value="critica">Crítica</option>
                  </select>
                </label>
              )}
              <textarea
                className="campo h-[60px] text-[13px]" value={motivo} onChange={(e) => setMotivo(e.target.value)}
                placeholder={modo === "rejeitar" ? "Por que rejeitar? (obrigatório: ajuda a ajustar as regras)" : "O que foi ajustado?"}
              />
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {modo ? (
              <>
                <Botao variante={modo === "rejeitar" ? "perigo" : "primario"} carregando={decidir.isPending}
                  disabled={!motivo.trim()} onClick={() => enviar(modo)}>
                  Confirmar {modo === "rejeitar" ? "rejeição" : "ajuste"}
                </Botao>
                <Botao variante="fantasma" onClick={() => setModo(null)}>Voltar</Botao>
              </>
            ) : (
              <>
                <Botao variante="primario" carregando={decidir.isPending} onClick={() => enviar("aceitar")}><Check size={14} /> Aceitar</Botao>
                <Botao onClick={() => setModo("ajustar")}><PencilLine size={14} /> Ajustar</Botao>
                <Botao variante="perigo" onClick={() => setModo("rejeitar")}><X size={14} /> Rejeitar</Botao>
              </>
            )}
          </div>
          {erro && <p className="mt-2 text-[12px] text-critico">{erro}</p>}
        </>
      )}
    </div>
  );
}

/** Cartão de Previsão: o mesmo componente em todas as telas. Responde às três perguntas do enunciado. */
export default function CartaoPrevisao({ c, onDecidido, compacto = false }: { c: Cartao; onDecidido?: () => void; compacto?: boolean }) {
  const [abertos, setAbertos] = useState(!compacto);
  const faixa = faixaTexto(c.unidade, c.faixa.inferior, c.faixa.superior);
  const selo = c.qualidade_do_modelo?.selo;
  return (
    <article className="border border-linha bg-papel" aria-label={`Cartão de previsão: ${c.o_que_preve}`}>
      <header className="flex flex-wrap items-center gap-2 border-b border-linha px-3 py-2">
        <span className="text-[11px] font-bold uppercase tracking-[0.08em]">{c.modulo} · {c.modulo_nome}</span>
        <SeloNivel nivel={c.nivel} />
        <span className="ml-auto border border-linha px-[6px] py-[1px] text-[10px] uppercase tracking-[0.06em] text-cinza" title="Os dados da Parte 3 são gerados para a demonstração">
          Dados sintéticos
        </span>
      </header>

      <section className="px-3 pt-3">
        <Titulo>O que estamos prevendo</Titulo>
        <p className="text-[14px]">{c.o_que_preve}</p>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-3">
          <span className="cond num text-[40px] font-bold leading-none" style={{ color: c.nivel ? COR_NIVEL[c.nivel] : undefined }}>
            {valorPrincipal(c.unidade, c.valor)}
          </span>
          {faixa && <span className="text-[13px] text-cinza">faixa provável: {faixa}</span>}
        </div>
        <p className="mt-1 text-[12px] text-cinza">
          {dataHora(c.horizonte.inicio)} até {dataHora(c.horizonte.fim)}
          {c.valor_real != null && <> · <b className="text-tinta">aconteceu: {valorPrincipal(c.unidade, c.valor_real)}</b></>}
        </p>
      </section>

      {compacto && (
        <button className="mx-3 mt-2 text-[12px] font-semibold underline" onClick={() => setAbertos(!abertos)}>
          {abertos ? "Menos detalhes" : "Por quê? Com base em quê?"}
        </button>
      )}

      {abertos && (
        <section className="px-3 pt-3">
          <Titulo>Com base em quê</Titulo>
          {c.fatores.length > 0 && (
            <>
              <p className="mb-2 text-[12px] text-cinza">O que mais pesou nesta previsão:</p>
              <Fatores c={c} />
            </>
          )}
          <details className="mt-3 text-[12px]">
            <summary className="cursor-pointer font-semibold">Dados considerados ({c.dados_considerados.length})</summary>
            <ul className="mt-1 list-disc pl-5 text-cinza">{c.dados_considerados.map((d) => <li key={d}>{d}</li>)}</ul>
          </details>
        </section>
      )}

      <section className="px-3 py-3">
        <Titulo>Como isso ajuda</Titulo>
        {c.como_ajuda && <p className="mb-3 text-[13px]">{c.como_ajuda}</p>}
        <Decisao c={c} onDecidido={onDecidido} />
      </section>

      <footer className="space-y-1 border-t border-linha bg-neutro px-3 py-2 text-[12px]">
        {selo && (
          <div className="flex items-start gap-2"><ShieldCheck size={14} className="mt-[1px] shrink-0" />
            <span>{selo.texto}{selo.avaliado_em ? ` (${selo.avaliado_em}).` : "."}</span></div>
        )}
        {c.confianca.aviso && (
          <div className="flex items-start gap-2 text-cinza"><Info size={14} className="mt-[1px] shrink-0" /><span>{c.confianca.aviso}</span></div>
        )}
        {c.modelo && <div className="text-cinza">Modelo {c.modelo.nome}, versão {c.modelo.versao}</div>}
      </footer>
    </article>
  );
}
