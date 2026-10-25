"""Confere no banco, com consultas diretas, que os padrões plantados aparecem no histórico.

Uso: python -m scripts.verificar_padroes
"""

import sys

from app.db import SessionLocal
from app.preditivo.verificacao import verificar


def main() -> None:
    with SessionLocal() as db:
        itens = verificar(db)
    for x in itens:
        marca = "ok " if x["ok"] else "FALHOU"
        extra = f"  ({x['detalhe']})" if x["detalhe"] else ""
        print(f"[{marca}] padrão {x['padrao']:>2}: {x['descricao']}: {x['obtido']} (mínimo {x['minimo']}){extra}")
    sys.exit(0 if all(x["ok"] for x in itens) else 1)


if __name__ == "__main__":
    main()
