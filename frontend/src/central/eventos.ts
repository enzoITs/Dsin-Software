import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_URL } from "../api/client";
import { avisar, tocarAlarme } from "./som";
import { useTela } from "./store";
import type { Evento } from "./tipos";

/** Canal de eventos em tempo real (WebSocket /ws/eventos).
 * A tela carrega o estado inicial pela API e, daí em diante, só aplica mudanças. */

type Ouvinte = (eventos: Evento[]) => void;
const ouvintes = new Set<Ouvinte>();

export function ouvirEventos(fn: Ouvinte) {
  ouvintes.add(fn);
  return () => { ouvintes.delete(fn); };
}

export function urlEventos() {
  return API_URL.replace(/^http/, "ws") + "/ws/eventos";
}

export function useConexaoEventos() {
  const qc = useQueryClient();
  useEffect(() => {
    let ws: WebSocket | null = null;
    let fechado = false;
    let tentativa = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let pendente: ReturnType<typeof setTimeout> | undefined;
    const { setConexao, marcarEvento } = useTela.getState();

    const recarregarListas = () => {
      clearTimeout(pendente);
      pendente = setTimeout(() => {
        for (const k of ["alertas", "alerta", "alertas-equip", "proximos", "indicadores", "regioes"]) {
          qc.invalidateQueries({ queryKey: ["central", k] });
        }
      }, 400);
    };

    const conectar = () => {
      setConexao("conectando");
      ws = new WebSocket(urlEventos());
      ws.onopen = () => {
        if (tentativa > 0) qc.invalidateQueries({ queryKey: ["central"] }); // voltou: ressincroniza tudo
        tentativa = 0;
        setConexao("ao_vivo");
      };
      ws.onmessage = (m) => {
        let eventos: Evento[];
        try { eventos = JSON.parse(m.data); } catch { return; }
        marcarEvento();
        let mudouAlerta = false;
        for (const ev of eventos) {
          if (ev.tipo === "alerta") {
            mudouAlerta = true;
            const a = ev.alerta;
            const silenciado = a.silenciado_ate && new Date(a.silenciado_ate).getTime() > Date.now();
            if (a.nivel === "critica" && !silenciado && (ev.acao === "tocar" || (ev.acao === "novo" && a.estado === "aberto"))) {
              if (useTela.getState().som) tocarAlarme();
              avisar(`Alerta crítico ${a.regiao ? `— ${a.regiao}` : ""}`, a.mensagem);
            }
          } else if (ev.tipo === "agentes") {
            mudouAlerta = true;
          } else if (ev.tipo === "recarregar") {
            qc.invalidateQueries({ queryKey: ["central"] });
          }
        }
        if (mudouAlerta) recarregarListas();
        ouvintes.forEach((fn) => fn(eventos));
      };
      ws.onclose = () => {
        setConexao("caiu");
        if (fechado) return;
        tentativa += 1;
        timer = setTimeout(conectar, Math.min(10_000, 500 * 2 ** Math.min(tentativa, 5)));
      };
      ws.onerror = () => ws?.close();
    };
    conectar();
    return () => {
      fechado = true;
      clearTimeout(timer);
      clearTimeout(pendente);
      ws?.close();
    };
  }, [qc]);
}
