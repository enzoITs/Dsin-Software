import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, X } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useEquipamento, useHistorico, useOrdens, usePlanos, useTipos } from "../api/hooks";
import type { Agente } from "../api/tipos";
import { Score, SeloSituacao } from "../components/ui";
import { CATEGORIA_AGENTE, SITUACAO, SITUACAO_AGENTE, data, dataHora } from "../lib/rotulos";
import { useAgentesProximos, useAlerta, useAlertasEquipamento, useAtribuir } from "./api";
import { CardAlerta } from "./PainelAlertas";
import { useTela } from "./store";
import type { AlertaC } from "./tipos";
import { RANK_NIVEL, corOrgao, fmt, idade } from "./visual";

function Titulo({ sobre, titulo, children }: { sobre: string; titulo: string; children?: React.ReactNode }) {
  const fechar = () => useTela.getState().selecionar(null);
  return (
    <div className="sticky top-0 z-10 flex items-start justify-between gap-2 border-b border-tinta bg-papel px-4 py-3">
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-[0.05em] text-cinza">{sobre}</div>
        <div className="truncate text-[20px] font-bold leading-tight">{titulo}</div>
        {children}
      </div>
      <button onClick={fechar} aria-label="Fechar ficha" className="p-1 hover:bg-neutro"><X size={18} /></button>
    </div>
  );
}

function Bloco({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-linha px-4 py-3">
      <h3 className="mb-2 text-[11px] font-bold uppercase tracking-[0.06em]">{titulo}</h3>
      {children}
    </section>
  );
}

export function AgentesProximos({ alerta }: { alerta: AlertaC }) {
  const q = useAgentesProximos(alerta.resolvido_em ? null : alerta.id);
  const atribuir = useAtribuir();
  if (alerta.lon == null) return null;
  return (
    <Bloco titulo="Agentes mais próximos">
      {q.isLoading && <p className="text-[12px] text-cinza">Procurando…</p>}
      {q.data?.length === 0 && <p className="text-[12px] text-cinza">Nenhum agente em atividade com posição.</p>}
      <ul className="space-y-1">
        {q.data?.map((ag) => {
          const atual = alerta.agente?.id === ag.id;
          return (
            <li key={ag.id} className="flex items-center gap-2 text-[13px]">
              <span className="h-[10px] w-[10px] shrink-0 rotate-45" style={{ background: corOrgao(ag.orgao) }} />
              <button className="min-w-0 flex-1 text-left" onClick={() => useTela.getState().selecionar({ tipo: "agente", id: ag.id })}>
                <div className="truncate font-semibold">{ag.nome}</div>
                <div className="num text-[11px] text-cinza">
                  {ag.orgao} · {ag.distancia_m < 1000 ? `${ag.distancia_m} m` : `${fmt(ag.distancia_m / 1000, 1)} km`}
                  {ag.em_atendimento && !atual ? " · já em atendimento" : ""} · posição {idade(ag.posicao_em)}
                </div>
              </button>
              {atual ? (
                <span className="text-[12px] font-semibold text-ok">Atribuído</span>
              ) : (
                <button
                  disabled={atribuir.isPending}
                  className="shrink-0 border border-tinta px-2 py-[3px] text-[12px] font-semibold hover:bg-neutro disabled:opacity-40"
                  onClick={() => atribuir.mutate({ id: alerta.id, agente_id: ag.id })}
                >
                  Atribuir
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {atribuir.isError && <p className="mt-1 text-[12px] text-critico">{atribuir.error instanceof ApiError ? atribuir.error.erro.mensagem : "Erro"}</p>}
    </Bloco>
  );
}

function FichaEquipamento({ id, alertaId }: { id: number; alertaId?: number }) {
  const e = useEquipamento(id);
  const alertas = useAlertasEquipamento(id);
  const planos = usePlanos(id);
  const ordens = useOrdens(id);
  const hist = useHistorico(id);
  const tipos = useTipos().data ?? [];
  if (e.isLoading) return <div className="p-4 text-cinza">Carregando…</div>;
  if (!e.data) return <div className="p-4 text-critico">Equipamento não encontrado.</div>;
  const d = e.data;
  const intervalo = tipos.find((t) => t.id === d.tipo.id)?.intervalo_sinal_esperado_min;
  const abertos = (alertas.data?.itens ?? []).filter((a) => !a.resolvido_em);
  const principal = abertos.find((a) => a.id === alertaId)
    ?? [...abertos].filter((a) => a.nivel !== "baixa").sort((a, b) => RANK_NIVEL[b.nivel] - RANK_NIVEL[a.nivel])[0];
  const proxPlano = (planos.data ?? []).filter((p) => p.ativo).sort((a, b) => (a.proxima_data ?? "").localeCompare(b.proxima_data ?? ""))[0];
  const osAberta = (ordens.data ?? []).find((o) => o.status === "aberta");
  const atrasoMin = d.ultimo_sinal_em ? (Date.now() - new Date(d.ultimo_sinal_em).getTime()) / 60000 : null;
  return (
    <>
      <Titulo sobre={`${d.tipo.nome} · ${d.orgao}`} titulo={d.codigo_interno}>
        <div className="mt-1 text-[13px]"><SeloSituacao situacao={d.situacao} /></div>
      </Titulo>
      {principal && (
        <div className="border-b border-linha bg-neutro p-2"><CardAlerta a={principal} /></div>
      )}
      {principal && <AgentesProximos alerta={principal} />}
      <Bloco titulo="Último sinal">
        {d.dispositivo_iot_id ? (
          <p className="text-[13px]">
            <b>{idade(d.ultimo_sinal_em)}</b>
            {intervalo ? <span className="text-cinza"> · esperado a cada {intervalo} min</span> : null}
            {atrasoMin != null && intervalo && atrasoMin > intervalo * 2 && <span className="block text-[12px] font-semibold text-atencao">Sinal atrasado: no mapa o ponto fica esmaecido.</span>}
            <span className="block text-[11px] text-cinza">Módulo {d.dispositivo_iot_id}</span>
          </p>
        ) : <p className="text-[13px] text-cinza">Sem módulo IoT: a central não recebe sinal deste equipamento.</p>}
      </Bloco>
      <Bloco titulo="Score de saúde">
        <div className="flex items-start gap-4">
          <Score valor={d.score_saude} />
          <ul className="flex-1 space-y-[2px] text-[12px]">
            {d.score_motivos.length === 0 && <li className="text-cinza">Nenhum problema encontrado</li>}
            {d.score_motivos.map((m) => <li key={m.chave}><span className="num font-semibold">{m.pontos}</span> {m.texto}</li>)}
          </ul>
        </div>
      </Bloco>
      {abertos.length > (principal ? 1 : 0) && (
        <Bloco titulo="Outros alertas abertos">
          <div className="space-y-1">{abertos.filter((a) => a.id !== principal?.id).map((a) => <CardAlerta key={a.id} a={a} compacto />)}</div>
        </Bloco>
      )}
      <Bloco titulo="Manutenção">
        <p className="text-[13px]">
          {proxPlano ? <>Próxima: <b>{data(proxPlano.proxima_data)}</b> <span className="text-cinza">({proxPlano.tipo})</span></> : "Sem plano ativo"}
        </p>
        <p className="text-[13px]">{osAberta ? <>OS aberta <b>#{osAberta.id}</b> · {osAberta.prioridade} · {osAberta.motivo}</> : <span className="text-cinza">Nenhuma ordem de serviço aberta</span>}</p>
      </Bloco>
      <Bloco titulo="Cadastro">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-[2px] text-[12px]">
          <dt className="text-cinza">Marca / modelo</dt><dd>{d.marca} {d.modelo}</dd>
          <dt className="text-cinza">Série</dt><dd className="num">{d.numero_serie}</dd>
          <dt className="text-cinza">Local</dt><dd>{d.localizacao ? `${d.localizacao.rua}${d.localizacao.referencia ? `, ${d.localizacao.referencia}` : ""}` : "—"}</dd>
          <dt className="text-cinza">Bairro</dt><dd>{d.bairro ?? "—"} · {d.regiao ?? "sem região"}</dd>
          <dt className="text-cinza">Instalado</dt><dd>{data(d.data_instalacao)}</dd>
        </dl>
      </Bloco>
      <Bloco titulo="Histórico recente">
        <ul className="space-y-1 text-[12px]">
          {(hist.data ?? []).slice(0, 5).map((h) => (
            <li key={h.id}>
              <span className="num text-cinza">{dataHora(h.em)}</span> · {SITUACAO[h.situacao_nova].rotulo}
              <span className="block text-cinza">{h.motivo} — {h.usuario}</span>
            </li>
          ))}
          {hist.data?.length === 0 && <li className="text-cinza">Sem mudanças registradas</li>}
        </ul>
      </Bloco>
      <div className="px-4 py-3">
        <Link to={`/equipamentos/${d.id}`} className="inline-flex items-center gap-1 text-[13px] font-semibold underline">
          Ficha completa no inventário <ExternalLink size={13} />
        </Link>
      </div>
    </>
  );
}

function FichaAgente({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["agente", id], queryFn: () => api<Agente>(`/agentes/${id}`) });
  const atendimento = useQuery({
    queryKey: ["central", "alertas-agente", id],
    queryFn: () => api<{ itens: AlertaC[] }>("/alertas", { params: { agente_id: id, por_pagina: 5 } }),
    select: (d) => d.itens[0] ?? null,
    refetchInterval: 15_000,
  });
  if (q.isLoading) return <div className="p-4 text-cinza">Carregando…</div>;
  if (!q.data) return <div className="p-4 text-critico">Agente não encontrado.</div>;
  const a = q.data;
  return (
    <>
      <Titulo sobre={`${CATEGORIA_AGENTE[a.categoria]} · ${a.orgao}`} titulo={a.nome}>
        <div className="mt-1 flex items-center gap-2 text-[13px]">
          <span className="h-[10px] w-[10px] rotate-45" style={{ background: corOrgao(a.orgao) }} />
          {SITUACAO_AGENTE[a.situacao]}
        </div>
      </Titulo>
      <Bloco titulo="Em atendimento">
        {atendimento.data ? <CardAlerta a={atendimento.data} /> : <p className="text-[13px] text-cinza">Livre: nenhum alerta atribuído.</p>}
      </Bloco>
      <Bloco titulo="Dados">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-[2px] text-[12px]">
          <dt className="text-cinza">Matrícula</dt><dd className="num">{a.matricula}</dd>
          <dt className="text-cinza">Equipe</dt><dd>{a.equipe ?? "—"}</dd>
          <dt className="text-cinza">Veículo</dt><dd>{a.veiculo ? `${a.veiculo.codigo_interno} · ${a.veiculo.tipo}${a.veiculo.placa ? ` · ${a.veiculo.placa}` : ""}` : "A pé"}</dd>
          <dt className="text-cinza">Base</dt><dd>{a.base ?? "—"}</dd>
          <dt className="text-cinza">Contato</dt><dd>{a.contato ?? "—"}</dd>
        </dl>
      </Bloco>
    </>
  );
}

function FichaAlerta({ id }: { id: number }) {
  const q = useAlerta(id);
  if (q.isLoading) return <div className="p-4 text-cinza">Carregando…</div>;
  if (!q.data) return <div className="p-4 text-critico">Alerta não encontrado.</div>;
  return (
    <>
      <Titulo sobre={q.data.rotulo_regra} titulo={q.data.regiao ? `Região ${q.data.regiao}` : `Alerta #${q.data.id}`} />
      <div className="border-b border-linha bg-neutro p-2"><CardAlerta a={q.data} /></div>
      <AgentesProximos alerta={q.data} />
      {q.data.lista_membros && q.data.lista_membros.length > 0 && (
        <Bloco titulo="Equipamentos dentro do incidente">
          <div className="space-y-1">{q.data.lista_membros.map((m) => <CardAlerta key={m.id} a={m} compacto />)}</div>
        </Bloco>
      )}
    </>
  );
}

export default function Ficha() {
  const sel = useTela((s) => s.selecao);
  if (!sel) return null;
  return (
    <aside className="absolute bottom-2 right-2 top-2 z-20 w-[min(380px,calc(100%-16px))] overflow-y-auto border border-tinta bg-papel shadow-[0_6px_24px_rgba(0,0,0,0.18)]">
      {sel.tipo === "equipamento" && <FichaEquipamento id={sel.id} alertaId={sel.alertaId} />}
      {sel.tipo === "agente" && <FichaAgente id={sel.id} />}
      {sel.tipo === "alerta" && <FichaAlerta id={sel.id} />}
    </aside>
  );
}
