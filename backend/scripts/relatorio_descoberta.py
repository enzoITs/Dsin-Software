"""Relatório em Markdown: o que os modelos aprenderam × os padrões plantados (Q2).

Uso: python -m scripts.relatorio_descoberta [--saida caminho]
"""

import argparse
from pathlib import Path

from app.db import SessionLocal
from app.preditivo import descoberta

ROTULO = {"encontrado": "Encontrado", "fraco": "Sinal fraco", "nao_encontrado": "Não encontrado", "sem_dados": "Sem dados"}


def markdown(r: dict) -> str:
    linhas = [
        "# Relatório de descoberta dos padrões plantados",
        "",
        f"Gerado em {r['gerado_em'][:16].replace('T', ' ')} (UTC) com os modelos `{r['versoes']}`.",
        "",
        f"> {r['aviso']}",
        "",
        "Como foi feito: depois do treino, cada modelo é interrogado sem acesso à descrição dos padrões. Em P1, os mesmos "
        "equipamentos reais passam por contrafactuais (uma variável muda por vez: idade, temperatura da semana, atraso da "
        "preventiva), o que equivale à dependência parcial do modelo. Em P2, comparamos o que o modelo previu nas últimas 4 semanas "
        "por hora e dia com o que aconteceu, e aplicamos contrafactuais de chuva, evento e véspera. Padrões sem modelo próprio "
        "ainda são conferidos por consulta direta, e isso está dito na linha. Só no fim cada resultado é posto ao lado da regra "
        "plantada (`app/preditivo/padroes.py`).",
        "",
        f"Resultado: **{r['resumo'].get('encontrado', 0)} encontrados**, {r['resumo'].get('fraco', 0)} com sinal fraco, "
        f"{r['resumo'].get('nao_encontrado', 0)} não encontrados.",
        "",
        "| # | Padrão | Veredito | O que o sistema achou | O que foi plantado | Como |",
        "|---|---|---|---|---|---|",
    ]
    for p in r["padroes"]:
        achou = p["descoberto"] + (f". {p['detalhe']}" if p.get("detalhe") else "")
        linhas.append(f"| {p['padrao']} | {p['titulo']} | {ROTULO[p['veredito']]} | {achou} | {p['plantado']} | "
                      f"{p['modulo']}: {p['metodo']} |")
    linhas += ["", "Critério: efeito aprendido de 1,3× ou mais = encontrado; entre 1,1× e 1,3× = sinal fraco.", "",
               "Os padrões 9 e 10 (rotativo e patinetes) ficaram fora do plano enxuto. A mesma análise aparece na tela "
               "Confiança dos modelos, com os gráficos de dependência parcial.", ""]
    return "\n".join(linhas)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=None, help="arquivo .md; sem ele, imprime na tela")
    args = ap.parse_args()
    with SessionLocal() as db:
        r = descoberta.obter(db, refazer=True)
    if args.saida:
        Path(args.saida).write_text(markdown(r), encoding="utf-8")
        print(f"[descoberta] {r['resumo']} → {args.saida}")
    else:
        print(markdown(r))


if __name__ == "__main__":
    main()
