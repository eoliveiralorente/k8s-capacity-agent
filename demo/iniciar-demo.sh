#!/usr/bin/env bash
# Capacity Agent — inicia a demonstração local (Linux, macOS ou WSL). Requer Docker.
set -euo pipefail
cd "$(dirname "$0")"
source ./demo.env

command -v docker >/dev/null || { echo "Instale o Docker (Docker Desktop no Windows/macOS) e rode de novo."; exit 1; }
docker info >/dev/null 2>&1 || { echo "O Docker não está rodando. Abra o Docker Desktop e rode de novo."; exit 1; }

if ! docker image inspect "capacity-agent-demo:${DEMO_VERSION}" >/dev/null 2>&1; then
  echo "Carregando a imagem (só na primeira vez, cerca de 1 minuto)..."
  docker load -i capacity-agent-demo-image.tar.gz
fi

export DEMO_VERSION DEMO_PORT DEMO_CONTACT
docker compose -p capacity-agent-demo -f compose.yaml up -d

echo "Aguardando o painel subir..."
for _ in $(seq 1 60); do
  if docker compose -p capacity-agent-demo exec -T capacity-agent-demo \
       python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if [ ! -f senha-demo.txt ]; then
  PASS="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 14)"
  echo "$PASS" > senha-demo.txt
fi
PASS="$(cat senha-demo.txt)"
docker compose -p capacity-agent-demo exec -T capacity-agent-demo \
  python agent.py demo --email demo@capacity-agent.local --password "$PASS" >/dev/null

echo
echo "Demonstração pronta:"
echo "  Endereço: http://localhost:${DEMO_PORT}"
echo "  Login:    demo@capacity-agent.local"
echo "  Senha:    ${PASS}   (também em senha-demo.txt)"
echo
echo "Para renovar os dados: rode este script de novo. Para parar: ./parar-demo.sh"
