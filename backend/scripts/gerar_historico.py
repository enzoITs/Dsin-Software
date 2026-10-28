"""Histórico sintético da Parte 3 com padrões plantados.

Uso:
  python -m scripts.gerar_historico              gera clima, eventos, escala, ocorrências e séries (se ainda não houver)
  python -m scripts.gerar_historico --forcar     apaga o que foi gerado e gera de novo (mesmos dados)
  python -m scripts.gerar_historico --continuo   só avança o modo contínuo até a hora atual

A vida dos equipamentos (falhas, furtos, manutenções) é gerada pelo seed da Parte 1, que usa
app/preditivo/gerador_equipamentos.py. Para recomeçar tudo do zero, recrie o banco.
Os padrões plantados estão em app/preditivo/padroes.py.
"""

import argparse

from app.db import SessionLocal
from app.preditivo import historico


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forcar", action="store_true", help="refaz o histórico da cidade")
    ap.add_argument("--continuo", action="store_true", help="só avança até a hora atual")
    args = ap.parse_args()
    with SessionLocal() as db:
        if args.continuo:
            historico.avancar(db)
        else:
            historico.gerar(db, forcar=args.forcar)
            historico.avancar(db)


if __name__ == "__main__":
    main()
