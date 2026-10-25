import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useTipos } from "../api/hooks";
import type { Mobilidade, Tipo } from "../api/tipos";
import FormDinamico from "../components/FormDinamico";
import { Botao, Campo, Carregando, Erro, Secao, Vazio } from "../components/ui";
import {
  ROTULO_TIPO_CAMPO, camposParaSchema, chaveDe, problemas, schemaParaCampos, type CampoEditor, type TipoCampo,
} from "../lib/editorSchema";
import { usePerfil } from "../lib/perfil";

export function ListaTipos() {
  const q = useTipos();
  const { perfil } = usePerfil();
  if (q.isLoading) return <Carregando />;
  if (q.isError) return <Erro erro={q.error} tentar={() => q.refetch()} />;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[32px] font-bold tracking-[-0.02em]">Tipos de equipamento</h1>
          <p className="text-cinza">Cada tipo define os campos do seu formulário. Um tipo novo passa a existir na hora, sem mudar código.</p>
        </div>
        {perfil.perfil === "gestor" && <Link to="/tipos/novo"><Botao variante="primario"><Plus size={14} /> Novo tipo</Botao></Link>}
      </div>
      {q.data!.length === 0 ? <Vazio titulo="Nenhum tipo cadastrado" /> : (
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-tinta text-[12px] text-cinza">
              <th className="py-2 pr-4 font-semibold">Prefixo</th><th className="pr-4 font-semibold">Nome</th><th className="pr-4 font-semibold">Categoria</th>
              <th className="pr-4 font-semibold">Fixo/móvel</th><th className="pr-4 font-semibold">Campos</th><th className="pr-4 font-semibold">Sinal esperado</th><th className="font-semibold">Equipamentos</th>
            </tr>
          </thead>
          <tbody>
            {q.data!.map((t) => (
              <tr key={t.id} className="border-b border-linha hover:bg-neutro">
                <td className="cond py-2 pr-4 text-[20px] font-bold">{t.prefixo}</td>
                <td className="pr-4 font-semibold"><Link to={`/tipos/${t.id}`}>{t.nome}</Link></td>
                <td className="pr-4">{t.categoria}</td>
                <td className="pr-4">{t.mobilidade === "fixo" ? "Fixo" : "Móvel"}</td>
                <td className="num pr-4">{Object.keys(t.schema_atributos.properties ?? {}).length}</td>
                <td className="num pr-4">a cada {t.intervalo_sinal_esperado_min} min</td>
                <td className="num"><Link to={`/?tipo_id=${t.id}`} className="underline">{t.total_equipamentos.toLocaleString("pt-BR")}</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function EditorTipoPagina() {
  const { id } = useParams();
  const q = useTipos();
  if (q.isLoading) return <Carregando />;
  if (q.isError) return <Erro erro={q.error} tentar={() => q.refetch()} />;
  const tipo = id ? q.data!.find((t) => t.id === Number(id)) : undefined;
  if (id && !tipo) return <Erro erro={new Error("Tipo não encontrado.")} />;
  return <EditorTipo key={id ?? "novo"} tipo={tipo} />;
}

const NOVO_CAMPO: CampoEditor = { chave: "", titulo: "", tipo: "texto", obrigatorio: false, opcoes: "", minimo: "", maximo: "" };

function EditorTipo({ tipo }: { tipo?: Tipo }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { perfil } = usePerfil();
  const [meta, setMeta] = useState({
    nome: tipo?.nome ?? "", prefixo: tipo?.prefixo ?? "", categoria: tipo?.categoria ?? "",
    mobilidade: (tipo?.mobilidade ?? "fixo") as Mobilidade, icone: tipo?.icone ?? "box",
    intervalo_sinal_esperado_min: String(tipo?.intervalo_sinal_esperado_min ?? 60),
    periodicidade_padrao_dias: tipo?.periodicidade_padrao_dias ? String(tipo.periodicidade_padrao_dias) : "",
  });
  const [campos, setCampos] = useState<CampoEditor[]>(() => (tipo ? schemaParaCampos(tipo.schema_atributos) : [{ ...NOVO_CAMPO }]));
  const [previa, setPrevia] = useState<Record<string, unknown>>({});
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);
  const schema = useMemo(() => camposParaSchema(campos), [campos]);
  const probs = problemas(campos);
  const editavel = perfil.perfil === "gestor";

  function mudarCampo(i: number, p: Partial<CampoEditor>) {
    setCampos((cs) => cs.map((c, j) => {
      if (j !== i) return c;
      const novo = { ...c, ...p };
      // A chave acompanha o nome enquanto o campo é novo.
      if (p.titulo !== undefined && (!tipo || !Object.keys(tipo.schema_atributos.properties ?? {}).includes(c.chave))) novo.chave = chaveDe(p.titulo);
      return novo;
    }));
  }
  function mover(i: number, d: -1 | 1) {
    setCampos((cs) => { const n = [...cs]; const j = i + d; if (j < 0 || j >= n.length) return cs; [n[i], n[j]] = [n[j], n[i]]; return n; });
  }

  async function salvar() {
    setErro(null);
    if (!meta.nome.trim() || !meta.prefixo.trim() || !meta.categoria.trim()) { setErro("Preencha nome, prefixo e categoria."); return; }
    if (probs.length) { setErro("Corrija os campos antes de salvar."); return; }
    setSalvando(true);
    try {
      const corpo = {
        ...meta,
        intervalo_sinal_esperado_min: Number(meta.intervalo_sinal_esperado_min) || 60,
        periodicidade_padrao_dias: meta.periodicidade_padrao_dias ? Number(meta.periodicidade_padrao_dias) : null,
        schema_atributos: schema,
      };
      const r = tipo
        ? await api<Tipo>(`/tipos-equipamento/${tipo.id}`, { method: "PUT", body: corpo })
        : await api<Tipo>("/tipos-equipamento", { method: "POST", body: corpo });
      await qc.invalidateQueries({ queryKey: ["tipos"] });
      navigate(tipo ? "/tipos" : `/equipamentos/novo?tipo=${r.id}`);
    } catch (e) {
      setErro(e instanceof ApiError ? e.erro.mensagem : "Erro ao salvar.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="space-y-8">
      <h1 className="text-[32px] font-bold tracking-[-0.02em]">{tipo ? tipo.nome : "Novo tipo de equipamento"}</h1>
      {!editavel && <p className="border-l-[3px] border-atencao bg-neutro px-3 py-2 text-[13px]">Apenas o gestor municipal pode criar ou editar tipos.</p>}
      <div className="grid gap-10 xl:grid-cols-[1fr_420px]">
        <div className="space-y-8">
          <Secao titulo="Tipo">
            <div className="grid gap-4 md:grid-cols-3">
              <Campo rotulo="Nome" obrigatorio><input className="campo" value={meta.nome} placeholder="Semáforo inteligente" onChange={(e) => setMeta({ ...meta, nome: e.target.value })} /></Campo>
              <Campo rotulo="Prefixo do código" obrigatorio dica="2 a 5 letras. Ex.: SEM gera SEM-0001">
                <input className="campo uppercase" maxLength={5} value={meta.prefixo} onChange={(e) => setMeta({ ...meta, prefixo: e.target.value.toUpperCase().replace(/[^A-Z]/g, "") })} />
              </Campo>
              <Campo rotulo="Categoria" obrigatorio><input className="campo" value={meta.categoria} placeholder="Sinalização" onChange={(e) => setMeta({ ...meta, categoria: e.target.value })} /></Campo>
              <Campo rotulo="Fixo ou móvel" dica={tipo && tipo.total_equipamentos ? "Travado: já há equipamentos deste tipo." : undefined}>
                <select className="campo" disabled={!!tipo?.total_equipamentos} value={meta.mobilidade} onChange={(e) => setMeta({ ...meta, mobilidade: e.target.value as Mobilidade })}>
                  <option value="fixo">Fixo (tem local de instalação)</option><option value="movel">Móvel (tem base)</option>
                </select>
              </Campo>
              <Campo rotulo="Sinal esperado a cada (min)" dica="Silêncio maior que isso vira alerta de falha silenciosa.">
                <input type="number" min={1} className="campo" value={meta.intervalo_sinal_esperado_min} onChange={(e) => setMeta({ ...meta, intervalo_sinal_esperado_min: e.target.value })} />
              </Campo>
              <Campo rotulo="Manutenção preventiva a cada (dias)" dica="Opcional. Cria o plano periódico ao instalar.">
                <input type="number" min={1} className="campo" value={meta.periodicidade_padrao_dias} onChange={(e) => setMeta({ ...meta, periodicidade_padrao_dias: e.target.value })} />
              </Campo>
            </div>
          </Secao>

          <Secao titulo="Campos do formulário" acao={<Botao variante="fantasma" onClick={() => setCampos([...campos, { ...NOVO_CAMPO }])}><Plus size={14} /> Adicionar campo</Botao>}>
            <div className="space-y-px bg-linha">
              {campos.map((c, i) => (
                <div key={i} className="grid gap-3 bg-papel py-3 md:grid-cols-[1.4fr_1fr_auto]">
                  <Campo rotulo={`Campo ${i + 1}`}>
                    <input className="campo" value={c.titulo} placeholder="Ex.: Número de fases" onChange={(e) => mudarCampo(i, { titulo: e.target.value })} />
                    <span className="num mt-1 block text-[11px] text-cinza">chave: {c.chave || "—"}</span>
                  </Campo>
                  <Campo rotulo="Tipo de resposta">
                    <select className="campo" value={c.tipo} onChange={(e) => mudarCampo(i, { tipo: e.target.value as TipoCampo })}>
                      {Object.entries(ROTULO_TIPO_CAMPO).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
                    </select>
                  </Campo>
                  <div className="flex items-end gap-1 pb-[2px]">
                    <label className="mr-2 flex items-center gap-1 text-[12px]"><input type="checkbox" checked={c.obrigatorio} onChange={(e) => mudarCampo(i, { obrigatorio: e.target.checked })} /> Obrigatório</label>
                    <button className="p-2 hover:bg-neutro" aria-label="Subir campo" onClick={() => mover(i, -1)}><ArrowUp size={14} /></button>
                    <button className="p-2 hover:bg-neutro" aria-label="Descer campo" onClick={() => mover(i, 1)}><ArrowDown size={14} /></button>
                    <button className="p-2 text-critico hover:bg-neutro" aria-label="Remover campo" onClick={() => setCampos(campos.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
                  </div>
                  {(c.tipo === "opcoes" || c.tipo === "multipla") && (
                    <div className="md:col-span-3">
                      <Campo rotulo="Opções, separadas por vírgula"><input className="campo" value={c.opcoes} placeholder="veicular, pedestre, misto" onChange={(e) => mudarCampo(i, { opcoes: e.target.value })} /></Campo>
                    </div>
                  )}
                  {(c.tipo === "numero" || c.tipo === "inteiro") && (
                    <div className="flex gap-3 md:col-span-3">
                      <Campo rotulo="Mínimo"><input type="number" className="campo !w-32" value={c.minimo} onChange={(e) => mudarCampo(i, { minimo: e.target.value })} /></Campo>
                      <Campo rotulo="Máximo"><input type="number" className="campo !w-32" value={c.maximo} onChange={(e) => mudarCampo(i, { maximo: e.target.value })} /></Campo>
                    </div>
                  )}
                </div>
              ))}
            </div>
            {probs.length > 0 && <ul className="mt-3 space-y-1 text-[13px] text-critico">{probs.map((p) => <li key={p}>{p}</li>)}</ul>}
          </Secao>

          <div className="flex flex-wrap items-center gap-3 border-t border-tinta pt-4">
            <Botao variante="primario" disabled={!editavel} carregando={salvando} onClick={salvar}>{tipo ? "Salvar tipo" : "Criar tipo e cadastrar equipamento"}</Botao>
            <Botao variante="fantasma" onClick={() => navigate("/tipos")}>Cancelar</Botao>
            {erro && <span className="text-[13px] text-critico">{erro}</span>}
          </div>
        </div>

        <aside className="xl:sticky xl:top-4 xl:self-start">
          <Secao titulo="Prévia do formulário">
            <div className="border border-linha p-4">
              <div className="cond mb-3 text-[28px] font-bold leading-none text-cinza">{meta.prefixo || "—"}-0001</div>
              <FormDinamico schema={schema} dados={previa} onChange={setPrevia} />
            </div>
            <details className="mt-3 text-[12px]">
              <summary className="cursor-pointer text-cinza">JSON Schema gerado</summary>
              <pre className="num mt-2 overflow-x-auto bg-neutro p-3">{JSON.stringify(schema, null, 2)}</pre>
            </details>
          </Secao>
        </aside>
      </div>
    </div>
  );
}
