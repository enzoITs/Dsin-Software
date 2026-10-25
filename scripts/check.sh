#!/usr/bin/env bash
# Roda os testes do backend e do frontend e o build. Precisa do banco do compose em pé.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== backend: pytest"
(cd backend && .venv/bin/pytest -q)
echo "== frontend: vitest + build"
(cd frontend && npx vitest run && npm run build)
echo "Tudo certo."
