import { Carregando, Secao } from "../components/ui";
import CartaoPrevisao from "./CartaoPrevisao";
import { useRiscoEquipamento } from "./api";

/** Ficha do equipamento: probabilidade de falha prevista (P1), nos cartões de 7 e 30 dias. */
export default function RiscoEquipamento({ id }: { id: number }) {
  const r = useRiscoEquipamento(id);
  if (r.isLoading) return <Carregando texto="Carregando a previsão de falha…" />;
  if (r.error || !r.data) return null;
  return (
    <Secao titulo="Risco de falha previsto">
      {r.data.mensagem && <p className="text-[13px] text-cinza">{r.data.mensagem}</p>}
      <div className="grid gap-3 md:grid-cols-2">
        {r.data.cartoes.map((c) => <CartaoPrevisao key={c.previsao_id} c={c} compacto />)}
      </div>
    </Secao>
  );
}
