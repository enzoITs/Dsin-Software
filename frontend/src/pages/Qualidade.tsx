import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { api } from "../api/client";
import { Carregando, Erro, Secao } from "../components/ui";

interface Problema {
  codigo: string; titulo: string; correcao: string; quantidade: number;
  exemplos: { equipamento_id: number; codigo_interno: string; detalhe: string }[];
}
interface Ranking {
  orgao_id: number; sigla: string; nome: string; equipamentos: number; completude: number;
  com_problema: number; percentual_com_problema: number; nota: number;
}
interface RespQualidade {
  total_equipamentos: number; completude_geral: number | null; equipamentos_com_problema: number;
  problemas: Problema[]; campos_mais_vazios: { campo: string; vazios: number }[]; ranking: Ranking[];
}

const pct = (v: number | null) => (v == null ? "—" : `${(v * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`);

export default function Qualidade() {
  const q = useQuery({ queryKey: ["qualidade"], queryFn: () => api<RespQualidade>("/qualidade") });
  const [aberto, setAberto] = useState<string | null>(null);
  if (q.isLoading) return <Carregando texto="Avaliando o inventário…" />;
  if (q.isError) return <Erro erro={q.error} tentar={() => q.refetch()} />;
  const d = q.data!;
  const maxNota = Math.max(...d.ranking.map((r) => r.nota), 1);

  return (
    <div className="space-y-10">
      <div className="grid gap-8 border-b border-tinta pb-6 md:grid-cols-[1fr_auto_auto]">
        <div>
          <h1 className="text-[32px] font-bold tracking-[-0.02em]">Qualidade do inventário</h1>
          <p className="max-w-[560px] text-cinza">
            Completude considera módulo IoT, data de instalação, coordenadas, CEP, referência, bairro (quando a cidade tem lista oficial) e os atributos obrigatórios de cada tipo.
          </p>
        </div>
        <div>
          <div className="cond num text-[72px] font-bold leading-[0.9]">{pct(d.completude_geral)}</div>
          <div className="text-[12px] text-cinza">completude geral</div>
        </div>
        <div>
          <div className={`cond num text-[72px] font-bold leading-[0.9] ${d.equipamentos_com_problema ? "text-acento" : ""}`}>
            {d.equipamentos_com_problema.toLocaleString("pt-BR")}
          </div>
          <div className="text-[12px] text-cinza">de {d.total_equipamentos.toLocaleString("pt-BR")} com algo a corrigir</div>
        </div>
      </div>

      <Secao titulo="Ranking por órgão">
        <ol className="space-y-px bg-linha">
          {d.ranking.map((r, i) => (
            <li key={r.orgao_id} className="grid grid-cols-[48px_1fr] items-center gap-4 bg-papel py-3 md:grid-cols-[48px_220px_1fr_120px_160px]">
              <span className="cond num text-[40px] font-bold leading-none text-cinza">{i + 1}</span>
              <div>
                <div className="text-[18px] font-bold">{r.sigla}</div>
                <div className="text-[12px] text-cinza">{r.nome}</div>
              </div>
              <div className="col-span-2 md:col-span-1">
                <div className="h-[10px] bg-neutro"><div className="h-full bg-acento" style={{ width: `${(r.nota / maxNota) * 100}%` }} /></div>
              </div>
              <div className="num"><span className="text-[24px] font-bold">{r.nota.toLocaleString("pt-BR")}</span> <span className="text-[12px] text-cinza">nota</span></div>
              <div className="num text-[13px]">
                {pct(r.completude)} completo<br />
                <span className="text-cinza">{r.com_problema.toLocaleString("pt-BR")} de {r.equipamentos.toLocaleString("pt-BR")} com problema</span>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-2 text-[12px] text-cinza">Nota = 70% completude + 30% cadastros sem problema.</p>
      </Secao>

      <div className="grid gap-10 lg:grid-cols-[1fr_320px]">
        <Secao titulo="Problemas encontrados">
          {d.problemas.length === 0 ? (
            <div className="flex items-center gap-3 border border-ok p-4"><CheckCircle2 className="text-ok" /> Nenhum problema encontrado. Inventário limpo.</div>
          ) : (
            <ul className="space-y-px bg-linha">
              {d.problemas.map((p) => (
                <li key={p.codigo} className="bg-papel">
                  <button className="flex w-full items-baseline justify-between gap-4 py-3 text-left hover:bg-neutro" onClick={() => setAberto(aberto === p.codigo ? null : p.codigo)}>
                    <span>
                      <span className="font-semibold">{p.titulo}</span>
                      <span className="block text-[13px] text-cinza">{p.correcao}</span>
                    </span>
                    <span className="cond num text-[32px] font-bold leading-none">{p.quantidade.toLocaleString("pt-BR")}</span>
                  </button>
                  {aberto === p.codigo && (
                    <ul className="mb-3 border-l-[3px] border-acento pl-3 text-[13px]">
                      {p.exemplos.map((e) => (
                        <li key={e.equipamento_id + e.detalhe} className="py-[2px]">
                          <Link to={`/equipamentos/${e.equipamento_id}/editar`} className="num font-semibold underline">{e.codigo_interno}</Link>
                          {e.detalhe && <span className="text-cinza"> — {e.detalhe}</span>}
                        </li>
                      ))}
                      {p.quantidade > p.exemplos.length && <li className="py-[2px] text-cinza">e mais {(p.quantidade - p.exemplos.length).toLocaleString("pt-BR")}</li>}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Secao>
        <Secao titulo="Campos mais vazios">
          <ul className="space-y-2 text-[13px]">
            {d.campos_mais_vazios.map((c) => (
              <li key={c.campo}>
                <div className="flex justify-between"><span>{c.campo}</span><span className="num">{c.vazios.toLocaleString("pt-BR")}</span></div>
                <div className="mt-1 h-[3px] bg-neutro"><div className="h-full bg-cinza" style={{ width: `${(c.vazios / d.total_equipamentos) * 100}%` }} /></div>
              </li>
            ))}
          </ul>
        </Secao>
      </div>
    </div>
  );
}
