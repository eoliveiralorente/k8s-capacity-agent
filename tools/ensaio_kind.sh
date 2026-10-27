#!/usr/bin/env bash
# Cluster kind LIMPO para ensaiar a instalação como se fosse um cliente (uso do fornecedor, no WSL).
#
#   tools/ensaio_kind.sh criar     cria o cluster "capacity-ensaio" com metrics-server
#   tools/ensaio_kind.sh status    mostra nodes e pods do ensaio
#   tools/ensaio_kind.sh apagar    apaga o cluster de ensaio
#
# Usa um kubeconfig próprio (~/.kube/kind-ensaio.yaml): não toca no laboratório (capacity-lab),
# na produção nem no contexto padrão do kubectl. Roteiro completo: docs/ENSAIO_INSTALACAO.md
set -euo pipefail

CLUSTER="capacity-ensaio"
KCFG="$HOME/.kube/kind-ensaio.yaml"
ACTION="${1:-}"
K=(kubectl --kubeconfig "$KCFG")

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

case "$ACTION" in
  criar)
    command -v kind >/dev/null || { echo "kind não encontrado"; exit 1; }
    if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
      echo "O cluster $CLUSTER já existe. Para começar do zero: tools/ensaio_kind.sh apagar"
    else
      step "Criando o cluster $CLUSTER (1 a 2 minutos)"
      kind create cluster --name "$CLUSTER" --kubeconfig "$KCFG" --wait 120s
    fi
    kind get kubeconfig --name "$CLUSTER" > "$KCFG"
    NODE="$("${K[@]}" get nodes -o jsonpath='{.items[0].metadata.name}')"
    case "$NODE" in "$CLUSTER"-*) ;; *) echo "Kubeconfig não é do ensaio ($NODE). Parando."; exit 1;; esac

    step "metrics-server (o cliente precisa ter; no kind, com --kubelet-insecure-tls)"
    "${K[@]}" apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml >/dev/null
    "${K[@]}" -n kube-system patch deploy metrics-server --type=json \
      -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' >/dev/null 2>&1 || true
    "${K[@]}" -n kube-system rollout status deploy/metrics-server --timeout=180s

    step "Pronto"
    echo "Cluster de ensaio: $CLUSTER"
    echo "Use SEMPRE assim no ensaio:  export KUBECONFIG=$KCFG"
    echo "Depois siga o roteiro: docs/ENSAIO_INSTALACAO.md"
    ;;
  status)
    "${K[@]}" get nodes -o wide
    "${K[@]}" get pods -A
    ;;
  apagar)
    kind delete cluster --name "$CLUSTER"
    rm -f "$KCFG"
    echo "Cluster de ensaio apagado."
    ;;
  *)
    sed -n '2,9p' "$0"
    exit 1
    ;;
esac
