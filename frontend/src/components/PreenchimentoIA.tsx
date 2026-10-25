import { useState } from "react";
import { Camera, Sparkles } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useStatusApi } from "../api/hooks";
import { Botao } from "./ui";

export interface Sugestao {
  tipo_id?: number | null;
  marca?: string | null; modelo?: string | null; numero_serie?: string | null; dispositivo_iot_id?: string | null;
  atributos?: Record<string, unknown>;
  localizacao?: { rua?: string | null; referencia?: string | null; cep?: string | null; bairro_id?: number | null; lon?: number | null; lat?: number | null } | null;
  observacoes?: string[];
}

/** Foto da etiqueta ou frase livre: a IA sugere os campos, a pessoa revisa e salva. */
export default function PreenchimentoIA({ onSugestao }: { onSugestao: (s: Sugestao) => void }) {
  const ia = useStatusApi().data?.ia_disponivel;
  const [texto, setTexto] = useState("");
  const [foto, setFoto] = useState<File | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [obs, setObs] = useState<string[]>([]);

  async function enviar() {
    if (!texto.trim() && !foto) return;
    setCarregando(true); setErro(null); setObs([]);
    const form = new FormData();
    if (texto.trim()) form.append("texto", texto);
    if (foto) form.append("foto", foto);
    try {
      const s = await api<Sugestao>("/ia/extrair-cadastro", { method: "POST", form });
      setObs(s.observacoes ?? []);
      onSugestao(s);
    } catch (e) {
      setErro(e instanceof ApiError ? e.erro.mensagem : "Falha ao consultar a IA.");
    } finally {
      setCarregando(false);
    }
  }

  return (
    <section className="border border-tinta p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="flex items-center gap-2 text-[15px] font-bold"><Sparkles size={16} className="text-acento" /> Preencher com IA</h2>
        <span className="text-[12px] text-cinza">Foto da etiqueta ou descrição livre. Você revisa antes de salvar.</span>
      </div>
      {ia === false ? (
        <p className="mt-3 text-[13px] text-cinza">
          IA indisponível: defina <code>ANTHROPIC_API_KEY</code> no arquivo <code>.env</code>. O cadastro manual abaixo funciona normalmente.
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap items-start gap-3">
          <textarea
            className="campo min-h-[42px] flex-1"
            rows={2}
            placeholder="Ex.: radar de 60 km/h na Av. Paulista, oposto ao 181, duas faixas, marca Perkons"
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
          />
          <label className="inline-flex cursor-pointer items-center gap-2 border border-tinta px-3 py-[7px] text-[13px] font-semibold hover:bg-neutro">
            <Camera size={14} /> {foto ? foto.name.slice(0, 24) : "Foto da etiqueta"}
            <input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => setFoto(e.target.files?.[0] ?? null)} />
          </label>
          <Botao variante="primario" carregando={carregando} onClick={enviar} disabled={!texto.trim() && !foto}>Preencher</Botao>
        </div>
      )}
      {erro && <p className="mt-2 text-[13px] text-critico">{erro}</p>}
      {obs.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-[13px] text-cinza">{obs.map((o) => <li key={o}>{o}</li>)}</ul>
      )}
    </section>
  );
}
