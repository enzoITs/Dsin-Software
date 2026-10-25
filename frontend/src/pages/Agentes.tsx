import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAgentes, useBases, useEquipamentos, useOrgaos, useTipos } from "../api/hooks";
import type { Agente } from "../api/tipos";
import { Botao, Campo, Carregando, Erro, Paginacao, Secao, Vazio } from "../components/ui";
import { usePerfil } from "../lib/perfil";
import { CATEGORIA_AGENTE, SITUACAO_AGENTE } from "../lib/rotulos";

const CATEGORIA_POR_SIGLA: Record<string, keyof typeof CATEGORIA_AGENTE> = {
  CET: "agente_transito", GCM: "guarda_municipal", PM: "policial_militar",
};

function NovoAgente({ onFechar }: { onFechar: () => void }) {
  const qc = useQueryClient();
  const { perfil } = usePerfil();
  const orgaos = useOrgaos().data ?? [];
  const tipos = useTipos().data ?? [];
  const [f, setF] = useState({
    nome: "", matricula: "", categoria: "agente_transito" as keyof typeof CATEGORIA_AGENTE,
    orgao_id: perfil.orgao_id ?? (null as number | null), equipe: "", contato: "",
    situacao: "em_atividade" as keyof typeof SITUACAO_AGENTE, base_id: null as number | null,
  });
  const [buscaVeiculo, setBuscaVeiculo] = useState("");
  const [veiculo, setVeiculo] = useState<{ id: number; codigo: string } | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);
  const bases = useBases(f.orgao_id).data ?? [];
  const moveis = tipos.filter((t) => t.mobilidade === "movel" && ["MOT", "VIA"].includes(t.prefixo)).map((t) => t.id);
  const candidatos = useEquipamentos({
    q: buscaVeiculo || undefined, orgao_id: f.orgao_id ? [f.orgao_id] : undefined, tipo_id: moveis, por_pagina: 6,
  });
  const orgaosPermitidos = perfil.perfil === "gestor" ? orgaos : orgaos.filter((o) => o.id === perfil.orgao_id);

  async function salvar() {
    setErro(null);
    if (f.nome.trim().length < 3 || !f.matricula.trim() || !f.orgao_id) { setErro("Preencha nome, matrícula e órgão."); return; }
    setSalvando(true);
    try {
      await api<Agente>("/agentes", { method: "POST", body: { ...f, equipe: f.equipe || null, contato: f.contato || null, veiculo_id: veiculo?.id ?? null } });
      qc.invalidateQueries({ queryKey: ["agentes"] });
      onFechar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.erro.mensagem : "Erro ao salvar.");
    } finally { setSalvando(false); }
  }

  return (
    <Secao titulo="Novo agente">
      <div className="grid gap-4 md:grid-cols-3">
        <Campo rotulo="Nome" obrigatorio><input className="campo" value={f.nome} onChange={(e) => setF({ ...f, nome: e.target.value })} /></Campo>
        <Campo rotulo="Matrícula" obrigatorio><input className="campo" value={f.matricula} onChange={(e) => setF({ ...f, matricula: e.target.value })} /></Campo>
        <Campo rotulo="Órgão" obrigatorio>
          <select className="campo" value={f.orgao_id ?? ""} onChange={(e) => {
            const id = Number(e.target.value) || null;
            const sigla = orgaos.find((o) => o.id === id)?.sigla ?? "";
            setF({ ...f, orgao_id: id, base_id: null, categoria: CATEGORIA_POR_SIGLA[sigla] ?? f.categoria });
            setVeiculo(null);
          }}>
            <option value="">Escolha</option>
            {orgaosPermitidos.map((o) => <option key={o.id} value={o.id}>{o.sigla}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Categoria">
          <select className="campo" value={f.categoria} onChange={(e) => setF({ ...f, categoria: e.target.value as typeof f.categoria })}>
            {Object.entries(CATEGORIA_AGENTE).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Equipe"><input className="campo" value={f.equipe} onChange={(e) => setF({ ...f, equipe: e.target.value })} /></Campo>
        <Campo rotulo="Situação">
          <select className="campo" value={f.situacao} onChange={(e) => setF({ ...f, situacao: e.target.value as typeof f.situacao })}>
            {Object.entries(SITUACAO_AGENTE).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Contato"><input className="campo" value={f.contato} onChange={(e) => setF({ ...f, contato: e.target.value })} /></Campo>
        <Campo rotulo="Base">
          <select className="campo" disabled={!f.orgao_id} value={f.base_id ?? ""} onChange={(e) => setF({ ...f, base_id: Number(e.target.value) || null })}>
            <option value="">Sem base</option>
            {bases.map((b) => <option key={b.id} value={b.id}>{b.nome}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Veículo (moto ou viatura)" dica="Opcional. Só veículos do mesmo órgão.">
          {veiculo ? (
            <div className="flex items-center justify-between border border-tinta px-3 py-[7px]">
              <span className="num font-semibold">{veiculo.codigo}</span>
              <button className="text-[12px] underline" onClick={() => setVeiculo(null)}>trocar</button>
            </div>
          ) : (
            <>
              <input className="campo" disabled={!f.orgao_id} placeholder="Busque por código, ex.: MOT-0012" value={buscaVeiculo} onChange={(e) => setBuscaVeiculo(e.target.value)} />
              {f.orgao_id && buscaVeiculo && (
                <ul className="border border-t-0 border-linha">
                  {(candidatos.data?.itens ?? []).map((v) => (
                    <li key={v.id}>
                      <button className="w-full px-3 py-1 text-left text-[13px] hover:bg-neutro" onClick={() => { setVeiculo({ id: v.id, codigo: v.codigo_interno }); setBuscaVeiculo(""); }}>
                        <span className="num font-semibold">{v.codigo_interno}</span> <span className="text-cinza">{v.marca} {v.modelo}</span>
                      </button>
                    </li>
                  ))}
                  {candidatos.data?.total === 0 && <li className="px-3 py-1 text-[13px] text-cinza">Nenhum veículo encontrado.</li>}
                </ul>
              )}
            </>
          )}
        </Campo>
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Botao variante="primario" carregando={salvando} onClick={salvar}>Cadastrar agente</Botao>
        <Botao variante="fantasma" onClick={onFechar}>Cancelar</Botao>
        {erro && <span className="text-[13px] text-critico">{erro}</span>}
      </div>
    </Secao>
  );
}

export default function Agentes() {
  const [q, setQ] = useState("");
  const [categoria, setCategoria] = useState("");
  const [situacao, setSituacao] = useState("");
  const [pagina, setPagina] = useState(1);
  const [novo, setNovo] = useState(false);
  const consulta = useAgentes({ q: q || undefined, categoria: categoria || undefined, situacao: situacao || undefined, pagina, por_pagina: 25 });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-[32px] font-bold tracking-[-0.02em]">Agentes de campo</h1>
        {!novo && <Botao variante="primario" onClick={() => setNovo(true)}><Plus size={14} /> Novo agente</Botao>}
      </div>
      {novo && <NovoAgente onFechar={() => setNovo(false)} />}
      <div className="flex flex-wrap gap-2">
        <input className="campo !w-auto min-w-[260px] flex-1" placeholder="Nome, matrícula ou equipe" value={q} onChange={(e) => { setQ(e.target.value); setPagina(1); }} />
        <select className="campo !w-auto" value={categoria} onChange={(e) => { setCategoria(e.target.value); setPagina(1); }}>
          <option value="">Todas as categorias</option>
          {Object.entries(CATEGORIA_AGENTE).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <select className="campo !w-auto" value={situacao} onChange={(e) => { setSituacao(e.target.value); setPagina(1); }}>
          <option value="">Todas as situações</option>
          {Object.entries(SITUACAO_AGENTE).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
      </div>
      {consulta.isLoading ? <Carregando /> : consulta.isError ? <Erro erro={consulta.error} tentar={() => consulta.refetch()} /> :
        consulta.data!.total === 0 ? <Vazio titulo={q || categoria || situacao ? "Nenhum agente com esses filtros" : "Nenhum agente cadastrado"} /> : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-tinta text-[12px] text-cinza">
                    <th className="py-2 pr-4 font-semibold">Nome</th><th className="pr-4 font-semibold">Matrícula</th><th className="pr-4 font-semibold">Categoria</th>
                    <th className="pr-4 font-semibold">Órgão e equipe</th><th className="pr-4 font-semibold">Situação</th><th className="pr-4 font-semibold">Veículo</th><th className="font-semibold">Base</th>
                  </tr>
                </thead>
                <tbody>
                  {consulta.data!.itens.map((a) => (
                    <tr key={a.id} className="border-b border-linha">
                      <td className="py-2 pr-4 font-semibold">{a.nome}</td>
                      <td className="num pr-4">{a.matricula}</td>
                      <td className="pr-4">{CATEGORIA_AGENTE[a.categoria]}</td>
                      <td className="pr-4">{a.orgao} <span className="text-cinza">{a.equipe}</span></td>
                      <td className="pr-4">{SITUACAO_AGENTE[a.situacao]}</td>
                      <td className="num pr-4">{a.veiculo ? <a className="underline" href={`/equipamentos/${a.veiculo.id}`}>{a.veiculo.codigo_interno}</a> : "—"} {a.veiculo?.placa && <span className="text-cinza">{a.veiculo.placa}</span>}</td>
                      <td>{a.base ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Paginacao pagina={pagina} total={consulta.data!.total} porPagina={25} onPagina={setPagina} />
          </>
        )}
    </div>
  );
}
