#!/usr/bin/env bash
# Inicia o dashboard usando o Python com dependências instaladas.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${CAPACITY_AGENT_PYTHON:-}"

if [[ -z "$PYTHON" ]]; then
  for candidate in \
    "$(pwd)/.venv/bin/python3" \
    "$HOME/.oci/bin/python3" \
    "/root/.oci/bin/python3" \
    "$(command -v python3)"
  do
    if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" -c "import uvicorn" 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  done
fi

if [[ -z "$PYTHON" ]]; then
  echo "ERRO: nenhum Python com uvicorn encontrado."
  echo "Crie o ambiente virtual e instale as dependências:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python3 -m pip install -r requirements.txt"
  echo "  ./serve.sh"
  exit 1
fi

exec "$PYTHON" agent.py serve "$@"
