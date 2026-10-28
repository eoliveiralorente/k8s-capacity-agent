#!/usr/bin/env bash
# Atualiza os ambientes de TESTE com o código da pasta Documents (uso do fornecedor, no WSL).
#
#   tools/atualizar_lab.sh            laboratório no kind (8080) + demo no Docker (8081)
#   tools/atualizar_lab.sh kind       só o kind
#   tools/atualizar_lab.sh demo       só o demo
#
# NUNCA toca em produção: o kind é acessado por um kubeconfig próprio, gerado pelo kind,
# e o contexto padrão do kubectl não é usado nem alterado.
set -euo pipefail

SRC="/mnt/c/Users/eduardo.lorente/Documents/k8s-capacity-agent/"
REPO="$HOME/repo_oficial/k8s-capacity-agent-v2"
KIND_CLUSTER="capacity-lab"
KCFG="$HOME/.kube/kind-capacity-lab.yaml"
DEMO_EMAIL="demo2@capacity-agent.local"
TARGET="${1:-tudo}"

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# Pede a senha do sudo uma vez só, no começo, e mantém válida até o fim.
sudo -v
( while true; do sudo -n true; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) 2>/dev/null &

step "Copiando o código de Documents"
rsync -a --exclude .git --exclude .github --exclude '.venv*' --exclude __pycache__ \
  --exclude '.capacity-agent*' --exclude '*.tar' --exclude '.env*' --exclude divulgacao --exclude entregas \
  "$SRC" "$REPO/"
cd "$REPO"
APPV="$(sed -n 's/^appVersion: *//p' charts/capacity-agent/Chart.yaml | tr -d '"')"
echo "Versão nos charts: $APPV (laboratório: $APPV-lab · demo: $APPV-demo)"

if [ "$TARGET" = "tudo" ] || [ "$TARGET" = "kind" ]; then
  step "Laboratório no kind"
  TAG="$APPV-lab-$(date +%Y%m%d-%H%M%S)"
  sudo docker build -q -t "capacity-agent:$TAG" --build-arg CAPACITY_AGENT_VERSION="$APPV-lab" . >/dev/null
  kind get kubeconfig --name "$KIND_CLUSTER" > "$KCFG"
  NODE="$(kubectl --kubeconfig "$KCFG" get nodes -o jsonpath='{.items[0].metadata.name}')"
  case "$NODE" in "$KIND_CLUSTER"-*) ;; *) echo "Kubeconfig não é do kind ($NODE). Parando."; exit 1;; esac
  kind load docker-image "capacity-agent:$TAG" --name "$KIND_CLUSTER" >/dev/null
  kubectl --kubeconfig "$KCFG" -n capacity-agent set image deploy/capacity-agent "*=capacity-agent:$TAG" >/dev/null
  kubectl --kubeconfig "$KCFG" -n capacity-agent rollout status deploy/capacity-agent --timeout=180s
  echo "kind atualizado: capacity-agent:$TAG"
  echo "Painel: kubectl --kubeconfig $KCFG -n capacity-agent port-forward --address 127.0.0.1,::1 svc/capacity-agent 8080:80"
fi

if [ "$TARGET" = "tudo" ] || [ "$TARGET" = "demo" ]; then
  step "Demo no Docker (porta 8081)"
  sudo CAPACITY_AGENT_PORT=8081 CAPACITY_AGENT_VERSION="$APPV-demo" docker compose -p capacity-agent-v2 up -d --build --force-recreate
  for _ in $(seq 1 30); do
    sudo -n docker compose -p capacity-agent-v2 exec -T capacity-agent \
      python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)" >/dev/null 2>&1 && break
    sleep 2
  done
  echo "Recriando os dados do demo (1 a 2 minutos)..."
  # Saída num arquivo (sem pipe) e stdin fechado: um "| head" aqui deixava o docker compose exec preso.
  DEMO_LOG="$(mktemp)"
  if timeout 600 sudo docker compose -p capacity-agent-v2 exec -T capacity-agent \
       python agent.py demo --email "$DEMO_EMAIL" </dev/null >"$DEMO_LOG" 2>&1; then
    head -n 2 "$DEMO_LOG"
  else
    echo "A recriação do demo falhou ou passou de 10 minutos. Últimas linhas:"; tail -n 20 "$DEMO_LOG"
  fi
  rm -f "$DEMO_LOG"
  echo "Demo: http://127.0.0.1:8081"
fi

step "Pronto"
echo "Produção não foi alterada."
