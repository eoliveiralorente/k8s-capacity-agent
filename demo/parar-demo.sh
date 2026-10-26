#!/usr/bin/env bash
# Para a demonstração. Use "./parar-demo.sh --apagar" para remover também os dados e a imagem.
set -euo pipefail
cd "$(dirname "$0")"
source ./demo.env
export DEMO_VERSION DEMO_PORT DEMO_CONTACT
if [ "${1:-}" = "--apagar" ]; then
  docker compose -p capacity-agent-demo -f compose.yaml down -v
  docker image rm "capacity-agent-demo:${DEMO_VERSION}" >/dev/null 2>&1 || true
  rm -f senha-demo.txt
  echo "Demonstração removida (dados e imagem)."
else
  docker compose -p capacity-agent-demo -f compose.yaml stop
  echo "Demonstração parada. Para voltar: ./iniciar-demo.sh"
fi
