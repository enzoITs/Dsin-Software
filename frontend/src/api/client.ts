import type { ErroApi } from "./tipos";

export const API_URL: string =
  import.meta.env.VITE_API_URL ?? `${window.location.protocol}//${window.location.hostname}:8000`;

export interface Perfil { perfil: "gestor" | "operador" | "tecnico"; orgao_id: number | null; usuario: string }

let perfilAtual: Perfil = { perfil: "gestor", orgao_id: null, usuario: "Gestor municipal" };
export function definirPerfil(p: Perfil) { perfilAtual = p; }

export class ApiError extends Error {
  constructor(public status: number, public erro: ErroApi) { super(erro.mensagem); }
}

type Params = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function montarQuery(params?: Params): string {
  if (!params) return "";
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => q.append(k, String(x)));
    else q.append(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export async function api<T>(caminho: string, opts: { method?: string; body?: unknown; params?: Params; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {
    "X-Perfil": perfilAtual.perfil,
    "X-Usuario": encodeURIComponent(perfilAtual.usuario),
  };
  if (perfilAtual.orgao_id) headers["X-Orgao-Id"] = String(perfilAtual.orgao_id);
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let r: Response;
  try {
    r = await fetch(`${API_URL}${caminho}${montarQuery(opts.params)}`, { method: opts.method ?? "GET", headers, body });
  } catch {
    throw new ApiError(0, { codigo: "sem_conexao", mensagem: "Não foi possível falar com a API. Ela está rodando?" });
  }
  if (!r.ok) {
    let erro: ErroApi = { codigo: "erro", mensagem: `Erro ${r.status}` };
    try {
      const j = await r.json();
      if (j?.detail?.mensagem) erro = j.detail;
      else if (typeof j?.detail === "string") erro = { codigo: "erro", mensagem: j.detail };
    } catch { /* corpo vazio */ }
    throw new ApiError(r.status, erro);
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}
