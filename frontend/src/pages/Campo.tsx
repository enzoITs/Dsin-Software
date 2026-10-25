import { useEffect, useRef, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Html5Qrcode } from "html5-qrcode";
import { Camera, ImageUp, MapPin, ScanLine } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useInvalidarEquipamento } from "../api/hooks";
import type { Equipamento, Situacao } from "../api/tipos";
import { Botao, Carregando, Erro, Score, SeloSituacao } from "../components/ui";
import { usePerfil } from "../lib/perfil";
import { MANUTENCAO, SITUACAO, haQuanto } from "../lib/rotulos";

/** Extrai o código de um QR do Atalaia (URL .../campo/RAD-0042) ou de um código digitado. */
export function codigoDoQr(texto: string): string | null {
  const t = texto.trim();
  const m = t.match(/\/campo\/([A-Za-z]{2,5}-\d{1,6})\/?$/) ?? t.match(/^([A-Za-z]{2,5}-\d{1,6})$/);
  return m ? m[1].toUpperCase() : null;
}

function Leitor() {
  const navigate = useNavigate();
  const [erro, setErro] = useState<string | null>(null);
  const [lendo, setLendo] = useState(false);
  const [manual, setManual] = useState("");
  const leitor = useRef<Html5Qrcode | null>(null);

  useEffect(() => () => { leitor.current?.stop().catch(() => {}); }, []);

  function abrir(texto: string) {
    const c = codigoDoQr(texto);
    if (!c) { setErro("Este QR Code não é de um equipamento do Atalaia."); return; }
    leitor.current?.stop().catch(() => {});
    navigate(`/campo/${c}`);
  }

  async function camera() {
    setErro(null);
    if (!window.isSecureContext) {
      setErro("A câmera do navegador exige HTTPS. Use o upload de foto do QR Code ou digite o código.");
      return;
    }
    try {
      leitor.current = new Html5Qrcode("leitor-qr");
      setLendo(true);
      await leitor.current.start({ facingMode: "environment" }, { fps: 10, qrbox: 240 }, abrir, () => {});
    } catch {
      setLendo(false);
      setErro("Não foi possível abrir a câmera. Use o upload de foto ou digite o código.");
    }
  }

  async function arquivo(f: File | undefined) {
    if (!f) return;
    setErro(null);
    try {
      const l = leitor.current ?? new Html5Qrcode("leitor-qr");
      leitor.current = l;
      abrir(await l.scanFile(f, false));
    } catch {
      setErro("Nenhum QR Code encontrado na foto. Tente uma foto mais próxima e nítida.");
    }
  }

  return (
    <div className="space-y-5">
      <h1 className="text-[28px] font-bold leading-tight tracking-[-0.02em]">Ler equipamento</h1>
      <div id="leitor-qr" className={lendo ? "w-full border border-tinta" : "hidden"} />
      <div className="grid gap-2">
        <Botao variante="primario" className="justify-center py-3 text-[15px]" onClick={camera}><Camera size={18} /> Ler QR Code com a câmera</Botao>
        <label className="inline-flex cursor-pointer items-center justify-center gap-2 border border-tinta px-3 py-3 text-[15px] font-semibold">
          <ImageUp size={18} /> Enviar foto do QR Code
          <input type="file" accept="image/*" className="hidden" onChange={(e) => arquivo(e.target.files?.[0])} />
        </label>
      </div>
      {erro && <p className="border-l-[3px] border-critico bg-neutro px-3 py-2 text-[14px]">{erro}</p>}
      <div className="border-t border-linha pt-4">
        <label className="rotulo" htmlFor="codigo-manual">Ou digite o código</label>
        <div className="flex gap-2">
          <input id="codigo-manual" className="campo uppercase" placeholder="RAD-0042" value={manual} onChange={(e) => setManual(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && abrir(manual)} />
          <Botao onClick={() => abrir(manual)}><ScanLine size={16} /> Abrir</Botao>
        </div>
      </div>
    </div>
  );
}

function posicaoAtual(): Promise<{ lon: number; lat: number } | null> {
  return new Promise((res) => {
    if (!navigator.geolocation) return res(null);
    navigator.geolocation.getCurrentPosition(
      (p) => res({ lon: p.coords.longitude, lat: p.coords.latitude }),
      () => res(null),
      { enableHighAccuracy: true, timeout: 8000 },
    );
  });
}

function EquipamentoCampo() {
  const codigo = useParams().codigo!;
  const { perfil } = usePerfil();
  const invalidar = useInvalidarEquipamento();
  const q = useQuery({ queryKey: ["campo", codigo], queryFn: () => api<Equipamento>(`/equipamentos/codigo/${codigo}`) });
  const [motivo, setMotivo] = useState("");
  const [descricao, setDescricao] = useState("");
  const [foto, setFoto] = useState<File | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const mudar = useMutation({
    mutationFn: (s: Situacao) => api<{ equipamento: Equipamento }>(`/equipamentos/${q.data!.id}/situacao`, { method: "PATCH", body: { situacao: s, motivo } }),
    onSuccess: (r) => { setMsg(`Situação: ${SITUACAO[r.equipamento.situacao].rotulo}.`); setMotivo(""); q.refetch(); invalidar(q.data!.id); },
  });

  const manutencao = useMutation({
    mutationFn: async () => {
      const gps = await posicaoAtual();
      const r = await api<{ registro: { id: number } }>(`/equipamentos/${q.data!.id}/registros-manutencao`, {
        method: "POST", body: { tecnico: perfil.usuario, descricao: descricao || null, lon: gps?.lon ?? null, lat: gps?.lat ?? null },
      });
      if (foto) {
        const form = new FormData();
        form.append("foto", foto);
        form.append("tipo", "campo");
        form.append("registro_id", String(r.registro.id));
        await api(`/equipamentos/${q.data!.id}/anexos`, { method: "POST", form });
      }
      return gps;
    },
    onSuccess: (gps) => {
      setMsg(`Manutenção registrada${foto ? " com foto" : ""}${gps ? " e posição GPS" : " (GPS indisponível)"}.`);
      setDescricao(""); setFoto(null); q.refetch(); invalidar(q.data!.id);
    },
  });

  if (q.isLoading) return <Carregando />;
  if (q.isError) return <Erro erro={q.error} tentar={() => q.refetch()} />;
  const e = q.data!;
  const erroMut = (mudar.error ?? manutencao.error) as ApiError | null;

  return (
    <div className="space-y-6">
      {e.situacao === "furtado" && <div className="-mx-4 bg-critico px-4 py-2 font-semibold text-white">Equipamento furtado</div>}
      <div>
        <div className="text-[13px] text-cinza">{e.tipo.nome} · {e.orgao}</div>
        <div className="cond num text-[56px] font-bold leading-[0.95]">{e.codigo_interno}</div>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1"><SeloSituacao situacao={e.situacao} /><Score valor={e.score_saude} /></div>
        <div className="mt-2 text-[13px] text-cinza">
          {e.localizacao ? `${e.localizacao.rua}${e.localizacao.referencia ? `, ${e.localizacao.referencia}` : ""}` : "Sem localização"}
          {e.status_manutencao !== "em_dia" && <span className="ml-2 font-semibold text-critico">{MANUTENCAO[e.status_manutencao]}</span>}
        </div>
        <div className="text-[13px] text-cinza">Último sinal {haQuanto(e.ultimo_sinal_em)}</div>
      </div>

      {msg && <p className="border-l-[3px] border-ok bg-neutro px-3 py-2">{msg}</p>}
      {erroMut && <p className="border-l-[3px] border-critico bg-neutro px-3 py-2">{erroMut.erro?.mensagem}</p>}

      {e.transicoes_permitidas.length > 0 && (
        <section className="space-y-2 border-t border-tinta pt-3">
          <h2 className="text-[13px] font-bold uppercase tracking-[0.06em]">Atualizar situação</h2>
          <input className="campo" placeholder="Motivo (obrigatório)" value={motivo} onChange={(ev) => setMotivo(ev.target.value)} />
          <div className="grid grid-cols-2 gap-2">
            {e.transicoes_permitidas.map((s) => (
              <Botao key={s} variante={s === "furtado" ? "perigo" : "secundario"} className="justify-center py-3"
                disabled={motivo.trim().length < 3} carregando={mudar.isPending && mudar.variables === s} onClick={() => mudar.mutate(s)}>
                {SITUACAO[s].rotulo}
              </Botao>
            ))}
          </div>
        </section>
      )}

      {!["nao_instalado", "desativado", "furtado"].includes(e.situacao) && (
        <section className="space-y-2 border-t border-tinta pt-3">
          <h2 className="text-[13px] font-bold uppercase tracking-[0.06em]">Registrar manutenção</h2>
          <textarea className="campo" rows={2} placeholder="O que foi feito" value={descricao} onChange={(ev) => setDescricao(ev.target.value)} />
          <label className="flex cursor-pointer items-center justify-center gap-2 border border-tinta py-3 font-semibold">
            <Camera size={18} /> {foto ? foto.name.slice(0, 28) : "Foto do serviço"}
            <input type="file" accept="image/*" capture="environment" className="hidden" onChange={(ev) => setFoto(ev.target.files?.[0] ?? null)} />
          </label>
          <Botao variante="primario" className="w-full justify-center py-3 text-[15px]" carregando={manutencao.isPending} onClick={() => manutencao.mutate()}>
            <MapPin size={16} /> Concluir manutenção
          </Botao>
          <p className="text-[12px] text-cinza">A posição GPS é registrada junto, quando o navegador permitir. Concluir devolve o equipamento a operacional.</p>
        </section>
      )}

      <div className="flex gap-3 border-t border-linha pt-4 text-[14px]">
        <Link to="/campo" className="underline">Ler outro</Link>
        <Link to={`/equipamentos/${e.id}`} className="underline">Ficha completa</Link>
      </div>
    </div>
  );
}

export default function Campo() {
  const { perfil } = usePerfil();
  return (
    <div className="min-h-full bg-papel">
      <header className="flex items-center justify-between border-b border-tinta px-4 py-3">
        <Link to="/campo" className="flex items-baseline gap-2">
          <span className="text-[18px] font-bold">Atalaia</span><span className="h-[8px] w-[8px] bg-acento" /><span className="text-[12px] text-cinza">campo</span>
        </Link>
        <span className="text-[12px] text-cinza">{perfil.usuario}</span>
      </header>
      <main className="mx-auto max-w-[520px] px-4 py-5">
        <Routes>
          <Route index element={<Leitor />} />
          <Route path=":codigo" element={<EquipamentoCampo />} />
        </Routes>
      </main>
    </div>
  );
}
