import { NavLink, Outlet } from "react-router-dom";
import { useOrgaos, useResumo } from "../api/hooks";
import { usePerfil } from "../lib/perfil";
import type { Perfil } from "../api/client";

const LINKS = [
  { to: "/central", rotulo: "Central de operações" },
  { to: "/amanha", rotulo: "Amanhã" },
  { to: "/previsao/equipamentos", rotulo: "Equipamentos em risco" },
  { to: "/previsao/equipes", rotulo: "Planejamento de equipes" },
  { to: "/", rotulo: "Inventário", fim: true },
  { to: "/equipamentos/novo", rotulo: "Cadastrar" },
  { to: "/agentes", rotulo: "Agentes" },
  { to: "/alertas", rotulo: "Alertas" },
  { to: "/qualidade", rotulo: "Qualidade" },
  { to: "/tipos", rotulo: "Tipos" },
  { to: "/campo", rotulo: "Modo campo" },
];

export function SeletorPerfil() {
  const { perfil, trocar } = usePerfil();
  const orgaos = useOrgaos().data ?? [];
  const valor = perfil.perfil === "gestor" ? "gestor" : `${perfil.perfil}:${perfil.orgao_id}`;
  const opcoes: { v: string; rotulo: string; p: Perfil }[] = [
    { v: "gestor", rotulo: "Gestor municipal", p: { perfil: "gestor", orgao_id: null, usuario: "Gestor municipal" } },
    ...orgaos.map((o) => ({ v: `operador:${o.id}`, rotulo: `Operador ${o.sigla}`, p: { perfil: "operador" as const, orgao_id: o.id, usuario: `Operador ${o.sigla}` } })),
    ...orgaos.map((o) => ({ v: `tecnico:${o.id}`, rotulo: `Técnico ${o.sigla}`, p: { perfil: "tecnico" as const, orgao_id: o.id, usuario: `Técnico ${o.sigla}` } })),
  ];
  return (
    <label className="flex items-center gap-2 text-[12px]">
      <span className="text-cinza">Perfil</span>
      <select
        className="border border-linha bg-papel px-2 py-1 text-[13px]"
        value={valor}
        onChange={(e) => { const o = opcoes.find((x) => x.v === e.target.value); if (o) trocar(o.p); }}
      >
        {opcoes.map((o) => <option key={o.v} value={o.v}>{o.rotulo}</option>)}
      </select>
    </label>
  );
}

export default function Layout() {
  const resumo = useResumo().data;
  const alertas = resumo ? Object.values(resumo.alertas_abertos).reduce((a, b) => a + b, 0) : null;
  return (
    <div className="min-h-full">
      <header className="border-b border-tinta">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-end justify-between gap-x-8 gap-y-2 px-4 pt-4 md:px-8">
          <div className="flex items-baseline gap-3 pb-3">
            <span className="text-[22px] font-bold tracking-[-0.02em]">Atalaia</span>
            <span className="h-[10px] w-[10px] bg-acento" aria-hidden />
            <span className="text-[12px] text-cinza">Inventário da cidade</span>
          </div>
          <div className="pb-3"><SeletorPerfil /></div>
        </div>
        <nav className="mx-auto flex max-w-[1400px] gap-0 overflow-x-auto px-4 md:px-8">
          {LINKS.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.fim}
              className={({ isActive }) =>
                `-mb-px whitespace-nowrap border-b-[3px] px-3 py-2 text-[13px] font-semibold ${isActive ? "border-acento" : "border-transparent text-cinza hover:text-tinta"}`
              }
            >
              {l.rotulo}
              {l.to === "/alertas" && alertas ? <span className="num ml-2 text-acento">{alertas.toLocaleString("pt-BR")}</span> : null}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-[1400px] px-4 py-6 md:px-8">
        <Outlet />
      </main>
    </div>
  );
}
