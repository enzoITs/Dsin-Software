import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useTreino } from "./api";

/** Faixa de progresso do treino dos modelos (primeiro start ou retreino). Some quando não há treino. */
export default function AvisoTreino() {
  const t = useTreino();
  const qc = useQueryClient();
  const antes = useRef<string | undefined>(undefined);
  const situacao = t.data?.situacao;
  // Quando o treino termina, as telas recarregam as previsões novas
  useEffect(() => {
    if (antes.current === "rodando" && situacao === "pronto") qc.invalidateQueries({ queryKey: ["prev"] });
    antes.current = situacao;
  }, [situacao, qc]);
  if (!t.data) return null;
  if (situacao === "rodando") {
    return (
      <div className="flex items-center gap-2 border border-previsao bg-previsao-fundo px-3 py-2 text-[13px]" role="status">
        <Loader2 size={15} className="animate-spin text-previsao" />
        <span><b>Treinando os modelos de previsão</b> (cerca de 3 minutos). Etapa: {t.data.etapa ?? "começando"}.
          As telas se atualizam sozinhas quando terminar.</span>
      </div>
    );
  }
  if (!t.data.tem_modelo) {
    return (
      <div className="border border-linha bg-neutro px-3 py-2 text-[13px]" role="status">
        {situacao === "erro"
          ? <>O treino falhou: {t.data.mensagem}. Um gestor pode tentar de novo na tela Confiança dos modelos.</>
          : <>Ainda não há modelos treinados. O treino começa sozinho na subida da API, ou um gestor pode iniciá-lo na tela Confiança dos modelos.</>}
      </div>
    );
  }
  return null;
}
