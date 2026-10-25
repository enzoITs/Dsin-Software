import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { definirPerfil, type Perfil } from "../api/client";

const CHAVE = "atalaia.perfil";
const PADRAO: Perfil = { perfil: "gestor", orgao_id: null, usuario: "Gestor municipal" };

function ler(): Perfil {
  try {
    const s = localStorage.getItem(CHAVE);
    return s ? { ...PADRAO, ...JSON.parse(s) } : PADRAO;
  } catch {
    return PADRAO;
  }
}

const Ctx = createContext<{ perfil: Perfil; trocar: (p: Perfil) => void }>({ perfil: PADRAO, trocar: () => {} });

export function PerfilProvider({ children }: { children: ReactNode }) {
  const [perfil, setPerfil] = useState<Perfil>(() => {
    const p = ler();
    definirPerfil(p);
    return p;
  });
  const qc = useQueryClient();
  useEffect(() => { definirPerfil(perfil); }, [perfil]);
  const trocar = (p: Perfil) => {
    definirPerfil(p);
    setPerfil(p);
    try { localStorage.setItem(CHAVE, JSON.stringify(p)); } catch { /* sem storage */ }
    qc.invalidateQueries();
  };
  return <Ctx.Provider value={{ perfil, trocar }}>{children}</Ctx.Provider>;
}

export const usePerfil = () => useContext(Ctx);
