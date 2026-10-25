import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import QRCode from "qrcode";
import { Printer, WifiOff } from "lucide-react";
import { api, ApiError } from "../api/client";
import {
  useAlertas, useEquipamento, useHistorico, useInvalidarEquipamento, useMudarSituacao, useOrdens, usePlanos, useRegistros, useTipos,
} from "../api/hooks";
import { camposOrdenados, type Equipamento, type Situacao } from "../api/tipos";
import { rotuloEnum } from "../components/FormDinamico";
import MapaPonto from "../components/MapaPonto";
import { Avisos, Botao, Campo, Carregando, Erro, Score, Secao, SeloSituacao } from "../components/ui";
import { MANUTENCAO, SITUACAO, data, dataHora, haQuanto } from "../lib/rotulos";

const ROTULO_ACAO: Record<string, string> = {
  plano_manutencao_imediata_criado: "plano de manutenção imediata criado",
  ordem_servico_aberta: "ordem de serviço aberta",
  alerta_critico_gerado: "alerta crítico gerado",
  orgao_notificado: "órgão responsável notificado",
  planos_suspensos: "planos de manutenção suspensos",
  fora_da_disponibilidade: "retirado do cálculo de disponibilidade",
  score_recalculado: "score recalculado",
  plano_periodico_criado: "plano periódico criado",
};

function MudarSituacao({ e }: { e: Equipamento }) {
  const [nova, setNova] = useState<Situacao | "">("");
  const [motivo, setMotivo] = useState("");
  const [resultado, setResultado] = useState<string | null>(null);
  const m = useMudarSituacao(e.id);
  if (!e.transicoes_permitidas.length) return null;
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Campo rotulo="Nova situação">
          <select className="campo" value={nova} onChange={(ev) => setNova(ev.target.value as Situacao)}>
            <option value="">Escolha</option>
            {e.transicoes_permitidas.map((s) => <option key={s} value={s}>{SITUACAO[s].rotulo}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Motivo" obrigatorio>
          <input className="campo" value={motivo} onChange={(ev) => setMotivo(ev.target.value)} placeholder="Ex.: lente quebrada" />
        </Campo>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Botao
          variante={nova === "furtado" ? "perigo" : "primario"}
          disabled={!nova || motivo.trim().length < 3}
          carregando={m.isPending}
          onClick={() => {
            const antes = e.score_saude;
            m.mutate({ situacao: nova as Situacao, motivo }, {
              onSuccess: (r) => {
                const acoes = r.acoes.map((a) => ROTULO_ACAO[a] ?? a).join(", ");
                setResultado(`${SITUACAO[nova as Situacao].rotulo}. Automações: ${acoes}. Score ${antes} → ${r.equipamento.score_saude}.`);
                setNova(""); setMotivo("");
              },
            });
          }}
        >
          Registrar mudança
        </Botao>
        <span className="text-[12px] text-cinza">Só aparecem as transições permitidas pela regra.</span>
      </div>
      {m.isError && <p className="text-[13px] text-critico">{(m.error as ApiError).erro?.mensagem ?? "Erro"}</p>}
      {resultado && <p className="border-l-[3px] border-ok bg-neutro px-3 py-2 text-[13px]">{resultado}</p>}
    </div>
  );
}

function RegistrarManutencao({ e }: { e: Equipamento }) {
  const planos = usePlanos(e.id).data?.filter((p) => p.ativo) ?? [];
  const invalidar = useInvalidarEquipamento();
  const [tecnico, setTecnico] = useState("");
  const [descricao, setDescricao] = useState("");
  const [resultado, setResultado] = useState("concluida");
  const [planoId, setPlanoId] = useState<string>("");
  const m = useMutation({
    mutationFn: () => api<{ acoes: string[] }>(`/equipamentos/${e.id}/registros-manutencao`, {
      method: "POST", body: { tecnico, descricao: descricao || null, resultado, plano_id: planoId ? Number(planoId) : null },
    }),
    onSuccess: () => { invalidar(e.id); setDescricao(""); },
  });
  if (["nao_instalado", "desativado", "furtado"].includes(e.situacao)) return null;
  return (
    <div className="space-y-3 border border-linha p-3">
      <div className="text-[13px] font-semibold">Registrar manutenção feita</div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Campo rotulo="Técnico" obrigatorio><input className="campo" value={tecnico} onChange={(ev) => setTecnico(ev.target.value)} /></Campo>
        <Campo rotulo="Resultado">
          <select className="campo" value={resultado} onChange={(ev) => setResultado(ev.target.value)}>
            <option value="concluida">Concluída: volta a operar</option>
            <option value="sem_conserto">Sem conserto: desativar</option>
          </select>
        </Campo>
        <Campo rotulo="Plano atendido">
          <select className="campo" value={planoId} onChange={(ev) => setPlanoId(ev.target.value)}>
            <option value="">Todos os vencidos até hoje</option>
            {planos.map((p) => <option key={p.id} value={p.id}>{rotuloEnum(p.tipo)} · {data(p.proxima_data)}</option>)}
          </select>
        </Campo>
        <Campo rotulo="O que foi feito"><input className="campo" value={descricao} onChange={(ev) => setDescricao(ev.target.value)} /></Campo>
      </div>
      <div className="flex items-center gap-3">
        <Botao variante="primario" disabled={tecnico.trim().length < 2} carregando={m.isPending} onClick={() => m.mutate()}>Registrar</Botao>
        {m.isError && <span className="text-[13px] text-critico">{(m.error as ApiError).erro?.mensagem}</span>}
        {m.isSuccess && <span className="text-[13px] text-ok">Manutenção registrada.</span>}
      </div>
    </div>
  );
}

function NovoPlano({ e }: { e: Equipamento }) {
  const invalidar = useInvalidarEquipamento();
  const [tipo, setTipo] = useState("agendada");
  const [dataP, setDataP] = useState("");
  const [periodo, setPeriodo] = useState("");
  const m = useMutation({
    mutationFn: () => api(`/equipamentos/${e.id}/planos-manutencao`, {
      method: "POST", body: { tipo, proxima_data: dataP || null, periodicidade_dias: periodo ? Number(periodo) : null },
    }),
    onSuccess: () => invalidar(e.id),
  });
  if (e.situacao === "desativado") return null;
  return (
    <div className="flex flex-wrap items-end gap-3">
      <Campo rotulo="Novo plano">
        <select className="campo" value={tipo} onChange={(ev) => setTipo(ev.target.value)}>
          <option value="imediata">Imediata</option><option value="agendada">Agendada</option><option value="periodica">Periódica</option>
        </select>
      </Campo>
      {tipo !== "imediata" && <Campo rotulo="Data"><input type="date" className="campo" value={dataP} onChange={(ev) => setDataP(ev.target.value)} /></Campo>}
      {tipo === "periodica" && <Campo rotulo="A cada (dias)"><input type="number" className="campo !w-28" value={periodo} onChange={(ev) => setPeriodo(ev.target.value)} /></Campo>}
      <Botao carregando={m.isPending} onClick={() => m.mutate()}>Adicionar</Botao>
      {m.isError && <span className="text-[13px] text-critico">{(m.error as ApiError).erro?.mensagem}</span>}
    </div>
  );
}

function QrCodeEquip({ codigo }: { codigo: string }) {
  const [src, setSrc] = useState("");
  const url = `${window.location.origin}/campo/${codigo}`;
  useEffect(() => { QRCode.toDataURL(url, { margin: 1, width: 360 }).then(setSrc); }, [url]);
  function imprimir() {
    const w = window.open("", "_blank", "width=420,height=520");
    if (!w) return;
    w.document.write(`<html><head><title>${codigo}</title></head><body style="font-family:Helvetica,Arial;text-align:center;padding:24px">
      <img src="${src}" style="width:280px"/><div style="font-size:36px;font-weight:700;margin-top:8px">${codigo}</div>
      <div style="font-size:12px">Atalaia · leia para abrir no modo campo</div><script>window.onload=()=>window.print()</script></body></html>`);
    w.document.close();
  }
  return (
    <div className="flex items-start gap-4">
      {src && <img src={src} alt={`QR Code de ${codigo}`} className="h-[120px] w-[120px] border border-linha" />}
      <div className="space-y-2 text-[12px] text-cinza">
        <p>Leia com o celular para abrir este equipamento no modo campo.</p>
        <Botao onClick={imprimir}><Printer size={14} /> Imprimir etiqueta</Botao>
      </div>
    </div>
  );
}

export default function FichaEquipamento() {
  const id = Number(useParams().id);
  const location = useLocation() as { state?: { avisos?: { codigo: string; mensagem: string }[]; criado?: boolean } };
  const q = useEquipamento(id);
  const hist = useHistorico(id);
  const planos = usePlanos(id);
  const registros = useRegistros(id);
  const ordens = useOrdens(id);
  const alertas = useAlertas({ equipamento_id: id });
  const tipo = useTipos().data?.find((t) => t.id === q.data?.tipo.id);

  if (q.isLoading) return <Carregando />;
  if (q.isError || !q.data) return <Erro erro={q.error} tentar={() => q.refetch()} />;
  const e = q.data;
  const props = Object.fromEntries(tipo ? camposOrdenados(tipo.schema_atributos) : []);
  const avisos = (location.state?.avisos ?? []).filter((a) => a.codigo !== "bairro_sugerido");

  return (
    <div className="space-y-8">
      {e.situacao === "furtado" && (
        <div className="-mx-4 bg-critico px-4 py-2 font-semibold text-white md:-mx-8 md:px-8">
          Equipamento furtado. Alerta crítico enviado ao órgão responsável ({e.orgao}).
        </div>
      )}
      {location.state?.criado && <div className="border-l-[3px] border-ok bg-neutro px-3 py-2">Equipamento cadastrado.</div>}
      <Avisos avisos={avisos} />

      <div className="grid gap-8 border-b border-tinta pb-6 lg:grid-cols-[1fr_280px]">
        <div>
          <div className="text-[13px] text-cinza">{e.tipo.nome} · {e.orgao}</div>
          <h1 className="cond num mt-1 text-[72px] font-bold leading-[0.9] tracking-[-0.03em] sm:text-[96px]">{e.codigo_interno}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-[15px]">
            <SeloSituacao situacao={e.situacao} />
            <span>{e.marca} {e.modelo}</span>
            <span className="num text-cinza">Série {e.numero_serie}</span>
            {e.status_manutencao !== "em_dia" && (
              <span className="font-semibold" style={{ color: e.status_manutencao === "vencida" ? "var(--color-critico)" : "var(--color-atencao)" }}>
                {MANUTENCAO[e.status_manutencao]}
              </span>
            )}
          </div>
          {e.sem_sinal && (
            <div className="mt-4 inline-flex items-center gap-2 border border-acento px-3 py-2 font-semibold text-acento">
              <WifiOff size={16} /> Possível falha silenciosa: operacional, mas sem sinal {haQuanto(e.ultimo_sinal_em)}
              (esperado a cada {tipo?.intervalo_sinal_esperado_min} min)
            </div>
          )}
          <div className="mt-4"><Link to={`/equipamentos/${e.id}/editar`}><Botao>Editar cadastro</Botao></Link></div>
        </div>
        <div>
          <div className="mb-1 text-[12px] font-semibold">Score de saúde</div>
          <Score valor={e.score_saude} grande />
          <ul className="mt-3 space-y-1 text-[13px]">
            {e.score_motivos.length === 0 && <li className="text-cinza">Nenhum problema encontrado.</li>}
            {e.score_motivos.map((m) => (
              <li key={m.chave} className="flex justify-between gap-3 border-b border-linha pb-1">
                <span>{m.texto}</span><span className="num font-semibold text-critico">{m.pontos}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="grid gap-10 lg:grid-cols-2">
        <div className="space-y-8">
          <Secao titulo="Dados">
            <dl className="grid grid-cols-[160px_1fr] gap-y-2 text-[14px]">
              <dt className="text-cinza">Módulo IoT</dt><dd className="num">{e.dispositivo_iot_id ?? "Não vinculado"}</dd>
              <dt className="text-cinza">Último sinal</dt><dd className="num">{dataHora(e.ultimo_sinal_em)} <span className="text-cinza">({haQuanto(e.ultimo_sinal_em)})</span></dd>
              <dt className="text-cinza">Instalado em</dt><dd className="num">{data(e.data_instalacao)}</dd>
              {Object.entries(props).map(([k, p]) => (
                <div key={k} className="contents">
                  <dt className="text-cinza">{p.title ?? k}</dt>
                  <dd>{formatarAttr(e.atributos[k])}</dd>
                </div>
              ))}
            </dl>
          </Secao>
          <Secao titulo={e.tipo.mobilidade === "movel" ? "Base" : "Localização"}>
            {e.localizacao ? (
              <>
                <p className="mb-3">
                  {e.localizacao.rua}{e.localizacao.referencia && `, ${e.localizacao.referencia}`}
                  <span className="text-cinza"> · {e.localizacao.bairro ?? "bairro não informado"} · {e.localizacao.cidade}/{e.localizacao.uf}{e.localizacao.cep && ` · CEP ${e.localizacao.cep}`}</span>
                </p>
                {e.localizacao.lon != null ? <MapaPonto lon={e.localizacao.lon} lat={e.localizacao.lat} altura={260} /> : <p className="text-cinza">Sem coordenadas.</p>}
              </>
            ) : <p className="text-cinza">Sem localização.</p>}
          </Secao>
          <Secao titulo="QR Code"><QrCodeEquip codigo={e.codigo_interno} /></Secao>
        </div>

        <div className="space-y-8">
          <Secao titulo="Situação"><MudarSituacao e={e} /></Secao>
          {alertas.data && alertas.data.total > 0 && (
            <Secao titulo="Alertas abertos">
              <ul className="space-y-1">
                {alertas.data.itens.map((a) => (
                  <li key={a.id} className="border-l-[3px] px-3 py-1 text-[13px]" style={{ borderColor: a.severidade === "critico" ? "var(--color-critico)" : "var(--color-atencao)" }}>
                    {a.mensagem} <span className="text-cinza">· {dataHora(a.criado_em)}</span>
                  </li>
                ))}
              </ul>
            </Secao>
          )}
          <Secao titulo="Manutenção">
            <div className="space-y-4">
              <table className="w-full text-left text-[13px]">
                <thead><tr className="border-b border-linha text-cinza"><th className="py-1 font-semibold">Plano</th><th className="font-semibold">Próxima</th><th className="font-semibold">Periodicidade</th><th className="font-semibold">Ativo</th></tr></thead>
                <tbody>
                  {(planos.data ?? []).map((p) => (
                    <tr key={p.id} className={`border-b border-linha ${p.ativo ? "" : "text-cinza"}`}>
                      <td className="py-1">{rotuloEnum(p.tipo)}</td><td className="num">{data(p.proxima_data)}</td>
                      <td className="num">{p.periodicidade_dias ? `${p.periodicidade_dias} dias` : "—"}</td><td>{p.ativo ? "Sim" : "Não"}</td>
                    </tr>
                  ))}
                  {planos.data?.length === 0 && <tr><td colSpan={4} className="py-2 text-cinza">Nenhum plano.</td></tr>}
                </tbody>
              </table>
              <NovoPlano e={e} />
              <RegistrarManutencao e={e} />
              {(registros.data ?? []).length > 0 && (
                <ul className="space-y-1 text-[13px]">
                  {registros.data!.map((r) => (
                    <li key={r.id} className="border-b border-linha pb-1">
                      <span className="num">{dataHora(r.executada_em)}</span> · {r.tecnico} · {r.resultado === "concluida" ? "concluída" : "sem conserto"}
                      {r.descricao && <span className="text-cinza"> — {r.descricao}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Secao>
          {(ordens.data ?? []).length > 0 && (
            <Secao titulo="Ordens de serviço">
              <ul className="space-y-1 text-[13px]">
                {ordens.data!.map((o) => (
                  <li key={o.id} className="flex justify-between gap-3 border-b border-linha pb-1">
                    <span>OS {o.id} · {o.motivo}</span>
                    <span className={o.status === "aberta" ? "font-semibold text-acento" : "text-cinza"}>{o.status === "aberta" ? `Aberta · ${o.prioridade}` : `Fechada ${data(o.fechada_em)}`}</span>
                  </li>
                ))}
              </ul>
            </Secao>
          )}
          <Secao titulo="Histórico de situação">
            {hist.isLoading ? <Carregando /> : (
              <ol className="border-l border-tinta">
                {(hist.data ?? []).map((h) => (
                  <li key={h.id} className="relative pb-3 pl-4">
                    <span className="absolute -left-[5px] top-[5px] h-[9px] w-[9px]" style={{ background: SITUACAO[h.situacao_nova].cor }} />
                    <div className="text-[13px]"><span className="font-semibold">{SITUACAO[h.situacao_nova].rotulo}</span>
                      {h.situacao_anterior && <span className="text-cinza"> (antes: {SITUACAO[h.situacao_anterior].rotulo.toLowerCase()})</span>}</div>
                    <div className="text-[13px]">{h.motivo}</div>
                    <div className="num text-[12px] text-cinza">{dataHora(h.em)} · {h.usuario}</div>
                  </li>
                ))}
                {hist.data?.length === 0 && <li className="pl-4 text-cinza">Sem mudanças registradas.</li>}
              </ol>
            )}
          </Secao>
        </div>
      </div>
    </div>
  );
}

function formatarAttr(v: unknown): string {
  if (v === undefined || v === null || v === "") return "—";
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  if (Array.isArray(v)) return v.map(rotuloEnum).join(", ");
  if (typeof v === "string") return /^\d{4}-\d{2}-\d{2}$/.test(v) ? data(v) : rotuloEnum(v);
  return String(v);
}
