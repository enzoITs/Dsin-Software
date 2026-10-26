import { X } from "lucide-react";
import { Carregando, Erro } from "../components/ui";
import CartaoPrevisao from "./CartaoPrevisao";
import { useCartao } from "./api";

/** Gaveta lateral com o Cartão de Previsão completo (ranking de risco, alertas preventivos, camada de risco). */
export default function GavetaCartao({ id, fechar }: { id: number; fechar: () => void }) {
  const c = useCartao(id);
  return (
    <div className="fixed inset-y-0 right-0 z-40 w-full max-w-[460px] overflow-y-auto border-l border-tinta bg-papel p-3 shadow-xl"
         role="dialog" aria-label="Cartão de previsão">
      <button onClick={fechar} className="mb-2 inline-flex items-center gap-1 text-[13px] font-semibold"><X size={14} /> Fechar</button>
      {c.isLoading ? <Carregando /> : c.data ? <CartaoPrevisao c={c.data} /> : <Erro erro={c.error} />}
    </div>
  );
}
