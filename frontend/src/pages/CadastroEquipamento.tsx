import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useBairros, useCidades, useEquipamento, useOrgaos, useTipos } from "../api/hooks";
import type { Aviso, Equipamento, Tipo } from "../api/tipos";
import FormDinamico, { validarAtributos } from "../components/FormDinamico";
import MapaPonto from "../components/MapaPonto";
import PreenchimentoIA, { type Sugestao } from "../components/PreenchimentoIA";
import { Avisos, Botao, Campo, Carregando, Erro, Secao } from "../components/ui";
import { usePerfil } from "../lib/perfil";

interface Estado {
  tipo_id: number | null;
  numero_serie: string; marca: string; modelo: string; orgao_id: number | null; dispositivo_iot_id: string;
  situacao_inicial: "nao_instalado" | "operacional"; data_instalacao: string;
  atributos: Record<string, unknown>;
  cidade_id: number | null; cep: string; rua: string; bairro_id: number | null; referencia: string;
  lon: number | null; lat: number | null;
}

const VAZIO: Estado = {
  tipo_id: null, numero_serie: "", marca: "", modelo: "", orgao_id: null, dispositivo_iot_id: "",
  situacao_inicial: "operacional", data_instalacao: "", atributos: {},
  cidade_id: null, cep: "", rua: "", bairro_id: null, referencia: "", lon: null, lat: null,
};

function deEquipamento(e: Equipamento): Estado {
  const l = e.localizacao;
  return {
    tipo_id: e.tipo.id, numero_serie: e.numero_serie, marca: e.marca, modelo: e.modelo, orgao_id: e.orgao_id,
    dispositivo_iot_id: e.dispositivo_iot_id ?? "", situacao_inicial: "operacional", data_instalacao: e.data_instalacao ?? "",
    atributos: e.atributos, cidade_id: l?.cidade_id ?? null, cep: l?.cep ?? "", rua: l?.rua ?? "",
    bairro_id: l?.bairro_id ?? null, referencia: l?.referencia ?? "", lon: l?.lon ?? null, lat: l?.lat ?? null,
  };
}

export default function CadastroEquipamentoPagina() {
  const { id } = useParams();
  if (id) return <EditarWrapper id={Number(id)} />;
  return <CadastroEquipamento />;
}

function EditarWrapper({ id }: { id: number }) {
  const q = useEquipamento(id);
  if (q.isLoading) return <Carregando />;
  if (q.isError || !q.data) return <Erro erro={q.error} tentar={() => q.refetch()} />;
  return <CadastroEquipamento existente={q.data} />;
}

function CadastroEquipamento({ existente }: { existente?: Equipamento }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { perfil } = usePerfil();
  const [sp] = useSearchParams();
  const tipos = useTipos();
  const orgaos = useOrgaos().data ?? [];
  const cidades = useCidades().data ?? [];
  const [s, setS] = useState<Estado>(() => (existente ? deEquipamento(existente) : { ...VAZIO, orgao_id: perfil.orgao_id, tipo_id: sp.get("tipo") ? Number(sp.get("tipo")) : null }));
  const bairros = useBairros(s.cidade_id).data ?? [];
  const [erros, setErros] = useState<Record<string, string>>({});
  const [errosAttr, setErrosAttr] = useState<Record<string, string>>({});
  const [erroGeral, setErroGeral] = useState<string | null>(null);
  const [avisosLocal, setAvisosLocal] = useState<Aviso[]>([]);
  const [salvando, setSalvando] = useState(false);
  const [cepStatus, setCepStatus] = useState<string | null>(null);
  const [preenchidoIA, setPreenchidoIA] = useState<string[]>([]);

  const tipo: Tipo | undefined = useMemo(() => tipos.data?.find((t) => t.id === s.tipo_id), [tipos.data, s.tipo_id]);
  const cidade = cidades.find((c) => c.id === s.cidade_id);
  const set = (p: Partial<Estado>) => setS((a) => ({ ...a, ...p }));

  useEffect(() => {
    if (!s.cidade_id && cidades.length) set({ cidade_id: (cidades.find((c) => c.tem_lista_bairros) ?? cidades[0]).id });
  }, [cidades, s.cidade_id]);

  // Bairro sugerido e avisos ao mover o ponto.
  useEffect(() => {
    if (!s.cidade_id || s.lon == null || s.lat == null) { setAvisosLocal([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await api<{ bairro_id: number | null; avisos: Aviso[] }>("/localizacao/sugerir", {
          params: { cidade_id: s.cidade_id, lon: s.lon, lat: s.lat, bairro_id: s.bairro_id },
        });
        setAvisosLocal(r.avisos.filter((a) => a.codigo !== "bairro_sugerido"));
        if (s.bairro_id == null && r.bairro_id) set({ bairro_id: r.bairro_id });
      } catch { /* sem aviso */ }
    }, 350);
    return () => clearTimeout(t);
  }, [s.cidade_id, s.lon, s.lat, s.bairro_id]);

  async function buscarCep() {
    if (!s.cep.trim()) return;
    setCepStatus("Consultando…");
    try {
      const r = await api<{ rua: string; bairro: string; cidade_id: number | null; bairro_id?: number | null }>(`/cep/${s.cep}`);
      set({ rua: r.rua || s.rua, cidade_id: r.cidade_id ?? s.cidade_id, bairro_id: r.bairro_id ?? s.bairro_id });
      setCepStatus(r.cidade_id ? null : "CEP de cidade ainda não cadastrada no inventário.");
    } catch (e) {
      setCepStatus(e instanceof ApiError ? e.erro.mensagem : "Não foi possível consultar o CEP.");
    }
  }

  function aplicarIA(sug: Sugestao) {
    const campos: string[] = [];
    const novo: Partial<Estado> = {};
    if (sug.tipo_id) { novo.tipo_id = sug.tipo_id; campos.push("tipo"); }
    for (const k of ["marca", "modelo", "numero_serie", "dispositivo_iot_id"] as const) {
      if (sug[k]) { novo[k] = sug[k]!; campos.push(k); }
    }
    if (sug.atributos && Object.keys(sug.atributos).length) { novo.atributos = sug.atributos; campos.push("atributos"); }
    const l = sug.localizacao;
    if (l) {
      if (l.rua) { novo.rua = l.rua; campos.push("rua"); }
      if (l.referencia) { novo.referencia = l.referencia; campos.push("referencia"); }
      if (l.cep) { novo.cep = l.cep; campos.push("cep"); }
      if (l.bairro_id) { novo.bairro_id = l.bairro_id; campos.push("bairro"); }
      if (l.lon != null && l.lat != null) { novo.lon = l.lon; novo.lat = l.lat; campos.push("ponto no mapa"); }
    }
    set(novo);
    setPreenchidoIA(campos);
  }

  async function salvar() {
    setErroGeral(null);
    const e: Record<string, string> = {};
    if (!s.tipo_id) e.tipo_id = "Escolha o tipo";
    if (!s.numero_serie.trim()) e.numero_serie = tipo?.mobilidade === "movel" ? "Informe o chassi" : "Informe o número de série";
    if (!s.marca.trim()) e.marca = "Informe a marca";
    if (!s.modelo.trim()) e.modelo = "Informe o modelo";
    if (!s.orgao_id) e.orgao_id = "Escolha o órgão";
    if (!s.cidade_id) e.cidade_id = "Escolha a cidade";
    if (!s.rua.trim()) e.rua = "Informe a rua ou rodovia";
    if (s.cep && !/^\d{5}-?\d{3}$/.test(s.cep)) e.cep = "CEP no formato 00000-000";
    const ea = tipo ? validarAtributos(tipo.schema_atributos, s.atributos) : {};
    setErros(e); setErrosAttr(ea);
    if (Object.keys(e).length || Object.keys(ea).length) { setErroGeral("Confira os campos destacados."); return; }

    const localizacao = {
      cidade_id: s.cidade_id, rua: s.rua, cep: s.cep || null, bairro_id: s.bairro_id, referencia: s.referencia || null,
      lon: s.lon, lat: s.lat,
    };
    setSalvando(true);
    try {
      const corpo = {
        numero_serie: s.numero_serie, marca: s.marca, modelo: s.modelo, orgao_id: s.orgao_id,
        dispositivo_iot_id: s.dispositivo_iot_id || null, data_instalacao: s.data_instalacao || null,
        atributos: s.atributos, localizacao,
      };
      const r = existente
        ? await api<Equipamento>(`/equipamentos/${existente.id}`, { method: "PATCH", body: corpo })
        : await api<Equipamento>("/equipamentos", { method: "POST", body: { ...corpo, tipo_id: s.tipo_id, situacao_inicial: s.situacao_inicial } });
      qc.invalidateQueries();
      navigate(`/equipamentos/${r.id}`, { state: { avisos: r.avisos, criado: !existente } });
    } catch (err) {
      if (err instanceof ApiError) {
        setErroGeral(err.erro.mensagem);
        if (err.erro.codigo === "atributos_invalidos") {
          const m: Record<string, string> = {};
          err.erro.detalhes?.forEach((d) => { if (d.campo) m[d.campo] = d.mensagem; });
          setErrosAttr(m);
        }
        if (err.erro.codigo === "serie_duplicada") setErros({ numero_serie: err.erro.mensagem });
        if (err.erro.codigo === "iot_duplicado") setErros({ dispositivo_iot_id: err.erro.mensagem });
        if (err.erro.codigo === "dados_invalidos") {
          const m: Record<string, string> = {};
          err.erro.detalhes?.forEach((d) => { if (d.campo) m[d.campo.split(".").pop()!] = d.mensagem; });
          setErros(m);
        }
      } else setErroGeral("Erro inesperado ao salvar.");
    } finally {
      setSalvando(false);
    }
  }

  if (tipos.isLoading) return <Carregando />;
  if (tipos.isError) return <Erro erro={tipos.error} tentar={() => tipos.refetch()} />;
  const orgaosPermitidos = perfil.perfil === "gestor" ? orgaos : orgaos.filter((o) => o.id === perfil.orgao_id);

  return (
    <div className="max-w-[1100px] space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-[32px] font-bold tracking-[-0.02em]">{existente ? `Editar ${existente.codigo_interno}` : "Cadastrar equipamento"}</h1>
        {!existente && <span className="text-cinza">O código interno é gerado ao salvar.</span>}
      </div>

      {!existente && <PreenchimentoIA onSugestao={aplicarIA} />}
      {preenchidoIA.length > 0 && (
        <div className="border-l-[3px] border-acento bg-neutro px-3 py-2 text-[13px]">
          Preenchido pela IA para sua revisão: {preenchidoIA.join(", ")}. Nada foi salvo ainda.
        </div>
      )}

      <Secao titulo="Tipo">
        {existente ? (
          <div className="text-[16px] font-semibold">{tipo?.nome}</div>
        ) : (
          <div className="grid grid-cols-2 gap-px border border-linha bg-linha sm:grid-cols-3 lg:grid-cols-5">
            {tipos.data!.map((t) => (
              <button
                key={t.id}
                onClick={() => set({ tipo_id: t.id, atributos: s.tipo_id === t.id ? s.atributos : {} })}
                className={`bg-papel p-3 text-left hover:bg-neutro ${s.tipo_id === t.id ? "outline outline-2 -outline-offset-2 outline-acento" : ""}`}
              >
                <div className="cond text-[22px] font-bold leading-none text-cinza">{t.prefixo}</div>
                <div className="mt-2 text-[13px] font-semibold leading-tight">{t.nome}</div>
                <div className="mt-1 text-[11px] text-cinza">{t.mobilidade === "fixo" ? "Fixo" : "Móvel"}</div>
              </button>
            ))}
          </div>
        )}
        {erros.tipo_id && <div className="mt-2 text-[12px] text-critico">{erros.tipo_id}</div>}
      </Secao>

      {tipo && (
        <>
          <Secao titulo="Identificação">
            <div className="grid gap-4 md:grid-cols-3">
              <Campo rotulo={tipo.mobilidade === "movel" ? "Número de série (chassi)" : "Número de série"} obrigatorio erro={erros.numero_serie}>
                <input className="campo" aria-invalid={!!erros.numero_serie} value={s.numero_serie} onChange={(e) => set({ numero_serie: e.target.value })} />
              </Campo>
              <Campo rotulo="Marca" obrigatorio erro={erros.marca}>
                <input className="campo" aria-invalid={!!erros.marca} value={s.marca} onChange={(e) => set({ marca: e.target.value })} />
              </Campo>
              <Campo rotulo="Modelo" obrigatorio erro={erros.modelo}>
                <input className="campo" aria-invalid={!!erros.modelo} value={s.modelo} onChange={(e) => set({ modelo: e.target.value })} />
              </Campo>
              <Campo rotulo="Órgão responsável" obrigatorio erro={erros.orgao_id}>
                <select className="campo" value={s.orgao_id ?? ""} onChange={(e) => set({ orgao_id: Number(e.target.value) || null })}>
                  <option value="">Escolha</option>
                  {orgaosPermitidos.map((o) => <option key={o.id} value={o.id}>{o.sigla} — {o.nome}</option>)}
                </select>
              </Campo>
              <Campo rotulo="Módulo IoT (ID, MAC ou IMEI)" erro={erros.dispositivo_iot_id} dica="Liga os sinais de telemetria a este equipamento.">
                <input className="campo" value={s.dispositivo_iot_id} onChange={(e) => set({ dispositivo_iot_id: e.target.value })} />
              </Campo>
              <Campo rotulo="Data de instalação">
                <input type="date" className="campo" value={s.data_instalacao} onChange={(e) => set({ data_instalacao: e.target.value })} />
              </Campo>
              {!existente && (
                <Campo rotulo="Situação inicial">
                  <select className="campo" value={s.situacao_inicial} onChange={(e) => set({ situacao_inicial: e.target.value as Estado["situacao_inicial"] })}>
                    <option value="operacional">Já instalado e operacional</option>
                    <option value="nao_instalado">Ainda não instalado</option>
                  </select>
                </Campo>
              )}
            </div>
          </Secao>

          <Secao titulo={`Atributos de ${tipo.nome.toLowerCase()}`}>
            <FormDinamico schema={tipo.schema_atributos} dados={s.atributos} onChange={(a) => set({ atributos: a })} erros={errosAttr} />
          </Secao>

          <Secao titulo={tipo.mobilidade === "movel" ? "Base do equipamento" : "Local de instalação"}>
            {tipo.mobilidade === "movel" && <p className="mb-3 text-cinza">Equipamento móvel: informe a base. A posição atual vem da telemetria.</p>}
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="grid content-start gap-4 sm:grid-cols-2">
                <Campo rotulo="Cidade" obrigatorio erro={erros.cidade_id}>
                  <select className="campo" value={s.cidade_id ?? ""} onChange={(e) => set({ cidade_id: Number(e.target.value) || null, bairro_id: null })}>
                    {cidades.map((c) => <option key={c.id} value={c.id}>{c.nome}/{c.uf}</option>)}
                  </select>
                </Campo>
                <Campo rotulo="CEP" erro={erros.cep ?? cepStatus ?? undefined} dica="Opcional. Rodovias muitas vezes não têm.">
                  <div className="flex gap-2">
                    <input className="campo" value={s.cep} onChange={(e) => set({ cep: e.target.value })} onBlur={buscarCep} placeholder="00000-000" />
                  </div>
                </Campo>
                <div className="sm:col-span-2">
                  <Campo rotulo="Rua, avenida ou rodovia" obrigatorio erro={erros.rua}>
                    <input className="campo" aria-invalid={!!erros.rua} value={s.rua} onChange={(e) => set({ rua: e.target.value })} />
                  </Campo>
                </div>
                <Campo rotulo="Referência" dica="Ex.: número 181, oposto ao 181, KM 203, S/N">
                  <input className="campo" value={s.referencia} onChange={(e) => set({ referencia: e.target.value })} />
                </Campo>
                <Campo rotulo="Bairro" dica={cidade?.tem_lista_bairros ? "Opcional. Sugerido pelo ponto no mapa." : "Esta cidade não tem lista oficial de bairros."}>
                  <select className="campo" disabled={!cidade?.tem_lista_bairros} value={s.bairro_id ?? ""} onChange={(e) => set({ bairro_id: Number(e.target.value) || null })}>
                    <option value="">Não informado</option>
                    {bairros.map((b) => <option key={b.id} value={b.id}>{b.nome}</option>)}
                  </select>
                </Campo>
                <div className="num text-[12px] text-cinza sm:col-span-2">
                  {s.lon != null && s.lat != null ? `Ponto: ${s.lat.toFixed(6)}, ${s.lon.toFixed(6)}` : "Clique no mapa para marcar o ponto."}
                  {s.lon != null && <button className="ml-3 underline" onClick={() => set({ lon: null, lat: null })}>remover ponto</button>}
                </div>
                <div className="sm:col-span-2"><Avisos avisos={avisosLocal} /></div>
              </div>
              <MapaPonto
                lon={s.lon} lat={s.lat} editavel altura={360}
                centro={cidade?.lon != null && cidade.lat != null ? [cidade.lon, cidade.lat] : undefined}
                onMover={(lon, lat) => set({ lon: +lon.toFixed(6), lat: +lat.toFixed(6) })}
              />
            </div>
          </Secao>

          <div className="sticky bottom-0 flex flex-wrap items-center gap-3 border-t border-tinta bg-papel py-4">
            <Botao variante="primario" carregando={salvando} onClick={salvar}>{existente ? "Salvar alterações" : "Cadastrar"}</Botao>
            <Botao variante="fantasma" onClick={() => navigate(-1)}>Cancelar</Botao>
            {erroGeral && <span className="text-[13px] text-critico">{erroGeral}</span>}
          </div>
        </>
      )}
    </div>
  );
}
