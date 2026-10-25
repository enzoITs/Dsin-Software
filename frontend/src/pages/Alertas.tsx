import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAlertas, useInvalidarEquipamento } from "../api/hooks";
import { Botao, Carregando, Erro, Paginacao, Vazio } from "../components/ui";
import { dataHora } from "../lib/rotulos";

const TIPOS = { furto: "Furto", falha_silenciosa: "Possível falha silenciosa", manutencao_vencida: "Manutenção vencida" } as const;

export default function Alertas() {
  const [tipo, setTipo] = useState("");
  const [abertos, setAbertos] = useState(true);
  const [pagina, setPagina] = useState(1);
  const q = useAlertas({ tipo: tipo || undefined, abertos, pagina, por_pagina: 50 });
  const invalidar = useInvalidarEquipamento();
  const resolver = useMutation({ mutationFn: (id: number) => api(`/alertas/${id}/resolver`, { method: "POST" }), onSuccess: () => invalidar() });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[32px] font-bold tracking-[-0.02em]">Alertas</h1>
        <p className="text-cinza">Gerados automaticamente: furto (crítico), equipamento operacional sem sinal e manutenção vencida. Atualiza a cada 20 segundos.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <select className="campo !w-auto" value={tipo} onChange={(e) => { setTipo(e.target.value); setPagina(1); }}>
          <option value="">Todos os tipos</option>
          {Object.entries(TIPOS).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <label className="flex items-center gap-2 px-2 text-[13px]"><input type="checkbox" checked={abertos} onChange={(e) => setAbertos(e.target.checked)} /> Só abertos</label>
      </div>
      {q.isLoading ? <Carregando /> : q.isError ? <Erro erro={q.error} tentar={() => q.refetch()} /> :
        q.data!.total === 0 ? <Vazio titulo="Nenhum alerta aberto">Todos os equipamentos estão sem pendências deste tipo.</Vazio> : (
          <>
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-tinta text-[12px] text-cinza">
                  <th className="py-2 pr-4 font-semibold">Equipamento</th><th className="pr-4 font-semibold">Tipo</th><th className="pr-4 font-semibold">Mensagem</th><th className="pr-4 font-semibold">Desde</th><th />
                </tr>
              </thead>
              <tbody>
                {q.data!.itens.map((a) => (
                  <tr key={a.id} className="border-b border-linha">
                    <td className="num py-2 pr-4 font-semibold"><Link to={`/equipamentos/${a.equipamento_id}`}>{a.codigo_interno}</Link></td>
                    <td className="pr-4">
                      <span className="inline-flex items-center gap-2">
                        <span className="h-[9px] w-[9px]" style={{ background: a.severidade === "critico" ? "var(--color-critico)" : "var(--color-atencao)" }} />
                        {TIPOS[a.tipo]}
                      </span>
                    </td>
                    <td className="pr-4 text-[13px]">{a.mensagem}</td>
                    <td className="num pr-4 text-[13px]">{dataHora(a.criado_em)}</td>
                    <td className="text-right">{!a.resolvido_em && <Botao variante="fantasma" onClick={() => resolver.mutate(a.id)}>Resolver</Botao>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Paginacao pagina={pagina} total={q.data!.total} porPagina={50} onPagina={setPagina} />
          </>
        )}
    </div>
  );
}
