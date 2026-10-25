import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Search, WifiOff, X } from "lucide-react";
import { useBairros, useCidades, useEquipamentos, useOrgaos, useResumo, useTipos, type FiltrosEquip } from "../api/hooks";
import type { Situacao } from "../api/tipos";
import { Botao, Carregando, Erro, Paginacao, Score, SeloSituacao, Vazio } from "../components/ui";
import { BuscaIA } from "../components/BuscaIA";
import { MANUTENCAO, ORDEM_SITUACAO, SITUACAO, haQuanto } from "../lib/rotulos";

const REGIOES = ["Centro", "Norte", "Sul", "Leste", "Oeste"];

function Numero({ rotulo, valor, destaque, onClick }: { rotulo: string; valor: string; destaque?: boolean; onClick?: () => void }) {
  return (
    <button onClick={onClick} disabled={!onClick} className="border-l border-linha py-1 pl-4 text-left first:border-l-0 first:pl-0 enabled:hover:bg-neutro">
      <div className={`cond num text-[40px] font-bold leading-none ${destaque ? "text-acento" : ""}`}>{valor}</div>
      <div className="mt-1 text-[12px] text-cinza">{rotulo}</div>
    </button>
  );
}

export default function Inventario() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const tipos = useTipos().data ?? [];
  const orgaos = useOrgaos().data ?? [];
  const cidades = useCidades().data ?? [];
  const cidadePrincipal = cidades.find((c) => c.tem_lista_bairros)?.id;
  const bairros = useBairros(cidadePrincipal).data ?? [];
  const resumo = useResumo().data;

  const filtros: FiltrosEquip = useMemo(() => {
    const num = (k: string) => (sp.getAll(k).length ? sp.getAll(k).map(Number) : undefined);
    const txt = (k: string) => (sp.getAll(k).length ? sp.getAll(k) : undefined);
    return {
      q: sp.get("q") ?? undefined,
      tipo_id: num("tipo_id"),
      situacao: txt("situacao") as Situacao[] | undefined,
      orgao_id: num("orgao_id"),
      bairro_id: num("bairro_id"),
      regiao: txt("regiao"),
      status_manutencao: txt("status_manutencao"),
      score_max: sp.get("score_max") ? Number(sp.get("score_max")) : undefined,
      sem_sinal: sp.get("sem_sinal") === "1" ? true : undefined,
      atributos: sp.get("atributos") ?? undefined,
      ordenar: sp.get("ordenar") ?? "codigo",
      pagina: Number(sp.get("pagina") ?? 1),
      por_pagina: 25,
    };
  }, [sp]);

  const [texto, setTexto] = useState(filtros.q ?? "");
  useEffect(() => setTexto(filtros.q ?? ""), [filtros.q]);
  useEffect(() => {
    const t = setTimeout(() => { if ((filtros.q ?? "") !== texto) definir({ q: texto || null }); }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [texto]);

  const consulta = useEquipamentos(filtros);

  function definir(mud: Record<string, string | null>, manterPagina = false) {
    const novo = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(mud)) {
      if (v === null || v === "") novo.delete(k);
      else novo.set(k, v);
    }
    if (!manterPagina) novo.delete("pagina");
    setSp(novo);
  }

  const temFiltro = [...sp.keys()].some((k) => !["pagina", "ordenar"].includes(k));
  const disp = resumo?.disponibilidade.disponibilidade;

  const sel = (k: string, rotulo: string, opcoes: { v: string; r: string }[]) => (
    <select className="campo !w-auto min-w-[150px]" value={sp.get(k) ?? ""} onChange={(e) => definir({ [k]: e.target.value || null })} aria-label={rotulo}>
      <option value="">{rotulo}</option>
      {opcoes.map((o) => <option key={o.v} value={o.v}>{o.r}</option>)}
    </select>
  );

  return (
    <div className="space-y-6">
      {resumo && (
        <div className="grid grid-cols-2 gap-y-4 border-b border-linha pb-5 md:grid-cols-5">
          <Numero rotulo="equipamentos cadastrados" valor={resumo.total_equipamentos.toLocaleString("pt-BR")} onClick={() => setSp(new URLSearchParams())} />
          <Numero rotulo="disponibilidade (regra única da API)" valor={disp == null ? "—" : `${(disp * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`} />
          <Numero rotulo="operacionais sem sinal" valor={resumo.sem_sinal.toLocaleString("pt-BR")} destaque={resumo.sem_sinal > 0} onClick={() => setSp(new URLSearchParams({ sem_sinal: "1", ordenar: "sinal" }))} />
          <Numero rotulo="manutenções vencidas" valor={(resumo.manutencao.vencida ?? 0).toLocaleString("pt-BR")} onClick={() => setSp(new URLSearchParams({ status_manutencao: "vencida", ordenar: "score" }))} />
          <Numero rotulo="furtados" valor={(resumo.disponibilidade.por_situacao.furtado ?? 0).toLocaleString("pt-BR")} onClick={() => setSp(new URLSearchParams({ situacao: "furtado" }))} />
        </div>
      )}

      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[260px] flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-cinza" />
            <input
              className="campo !pl-9"
              placeholder="Código, número de série, marca, modelo ou módulo IoT"
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
            />
          </div>
          <BuscaIA onFiltros={(params) => {
            const n = new URLSearchParams();
            for (const [k, v] of Object.entries(params)) (Array.isArray(v) ? v : [v]).forEach((x) => n.append(k, x));
            setSp(n);
          }} />
          <Botao variante="primario" onClick={() => navigate("/equipamentos/novo")}>Cadastrar equipamento</Botao>
        </div>
        <div className="flex flex-wrap gap-2">
          {sel("tipo_id", "Todos os tipos", tipos.map((t) => ({ v: String(t.id), r: t.nome })))}
          {sel("situacao", "Todas as situações", ORDEM_SITUACAO.map((s) => ({ v: s, r: SITUACAO[s].rotulo })))}
          {sel("orgao_id", "Todos os órgãos", orgaos.map((o) => ({ v: String(o.id), r: o.sigla })))}
          {sel("regiao", "Todas as regiões", REGIOES.map((r) => ({ v: r, r })))}
          {sel("bairro_id", "Todos os bairros", bairros.map((b) => ({ v: String(b.id), r: b.nome })))}
          {sel("status_manutencao", "Manutenção", Object.entries(MANUTENCAO).map(([v, r]) => ({ v, r })))}
          {sel("ordenar", "Ordenar por código", [
            { v: "score", r: "Pior score primeiro" }, { v: "-score", r: "Melhor score primeiro" },
            { v: "sinal", r: "Sinal mais antigo" }, { v: "atualizado", r: "Alterados recentemente" },
          ])}
          <label className="flex items-center gap-2 px-2 text-[13px]">
            <input type="checkbox" checked={sp.get("sem_sinal") === "1"} onChange={(e) => definir({ sem_sinal: e.target.checked ? "1" : null })} />
            Só sem sinal
          </label>
          {sp.get("atributos") && (
            <span className="flex items-center gap-2 border border-tinta px-2 text-[12px]">
              Atributos: {sp.get("atributos")}
              <button aria-label="Remover filtro de atributos" onClick={() => definir({ atributos: null })}><X size={12} /></button>
            </span>
          )}
          {temFiltro && <Botao variante="fantasma" onClick={() => setSp(new URLSearchParams())}>Limpar filtros</Botao>}
        </div>
      </div>

      {consulta.isLoading ? (
        <Carregando />
      ) : consulta.isError ? (
        <Erro erro={consulta.error} tentar={() => consulta.refetch()} />
      ) : !consulta.data || consulta.data.total === 0 ? (
        temFiltro ? (
          <Vazio titulo="Nenhum equipamento com esses filtros">
            <Botao className="mt-3" onClick={() => setSp(new URLSearchParams())}>Limpar filtros</Botao>
          </Vazio>
        ) : (
          <Vazio titulo="O inventário está vazio">
            Cadastre o primeiro equipamento ou importe os dados de demonstração com <code>python -m scripts.seed</code>.
            <div className="mt-3"><Link to="/equipamentos/novo"><Botao variante="primario">Cadastrar equipamento</Botao></Link></div>
          </Vazio>
        )
      ) : (
        <div className={consulta.isFetching ? "opacity-60 transition-opacity" : ""}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-left">
              <thead>
                <tr className="border-b border-tinta text-[12px] text-cinza">
                  <th className="py-2 pr-4 font-semibold">Código</th>
                  <th className="py-2 pr-4 font-semibold">Tipo</th>
                  <th className="py-2 pr-4 font-semibold">Marca e modelo</th>
                  <th className="py-2 pr-4 font-semibold">Órgão</th>
                  <th className="py-2 pr-4 font-semibold">Local</th>
                  <th className="py-2 pr-4 font-semibold">Situação</th>
                  <th className="py-2 pr-4 font-semibold">Saúde</th>
                  <th className="py-2 font-semibold">Último sinal</th>
                </tr>
              </thead>
              <tbody>
                {consulta.data.itens.map((e) => (
                  <tr key={e.id} className="cursor-pointer border-b border-linha hover:bg-neutro" onClick={() => navigate(`/equipamentos/${e.id}`)}>
                    <td className="num py-2 pr-4 font-semibold"><Link to={`/equipamentos/${e.id}`} onClick={(ev) => ev.stopPropagation()}>{e.codigo_interno}</Link></td>
                    <td className="py-2 pr-4">{e.tipo.nome}</td>
                    <td className="py-2 pr-4">{e.marca} <span className="text-cinza">{e.modelo}</span></td>
                    <td className="py-2 pr-4">{e.orgao}</td>
                    <td className="py-2 pr-4">{e.bairro ?? e.cidade ?? "—"}{e.regiao && <span className="text-cinza"> · {e.regiao}</span>}</td>
                    <td className="py-2 pr-4">
                      <SeloSituacao situacao={e.situacao} />
                      {e.status_manutencao !== "em_dia" && (
                        <div className="text-[11px]" style={{ color: e.status_manutencao === "vencida" ? "var(--color-critico)" : "var(--color-atencao)" }}>
                          {MANUTENCAO[e.status_manutencao]}
                        </div>
                      )}
                    </td>
                    <td className="py-2 pr-4"><Score valor={e.score_saude} /></td>
                    <td className="num py-2 text-[13px]">
                      {e.sem_sinal ? (
                        <span className="inline-flex items-center gap-1 font-semibold text-acento"><WifiOff size={13} /> {haQuanto(e.ultimo_sinal_em)}</span>
                      ) : (
                        <span className="text-cinza">{haQuanto(e.ultimo_sinal_em)}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Paginacao pagina={consulta.data.pagina} total={consulta.data.total} porPagina={consulta.data.por_pagina}
            onPagina={(p) => definir({ pagina: String(p) }, true)} />
        </div>
      )}
    </div>
  );
}
