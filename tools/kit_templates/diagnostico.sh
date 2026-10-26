#!/usr/bin/env bash
# Coleta informações para o suporte (sem segredos, sem logs de outras aplicações).
set -uo pipefail
NAMESPACE="${NAMESPACE:-capacity-agent}"
K=(kubectl); [ -n "${KUBE_CONTEXT:-}" ] && K+=(--context "$KUBE_CONTEXT")
OUT="diagnostico-$(date +%Y%m%d-%H%M%S).txt"
{
  echo "== versão";  "${K[@]}" version 2>&1
  echo "== nodes";   "${K[@]}" get nodes -o wide 2>&1
  echo "== top";     "${K[@]}" top nodes 2>&1
  echo "== storageclass"; "${K[@]}" get storageclass 2>&1
  echo "== recursos"; "${K[@]}" -n "$NAMESPACE" get deploy,pods,svc,pvc 2>&1
  echo "== pod";     "${K[@]}" -n "$NAMESPACE" describe pods 2>&1 | grep -v -i -E 'token|password|key='
  echo "== eventos"; "${K[@]}" -n "$NAMESPACE" get events --sort-by=.lastTimestamp 2>&1 | tail -30
  echo "== logs do painel"; "${K[@]}" -n "$NAMESPACE" logs deploy/capacity-agent --tail=80 2>&1
} > "$OUT"
echo "Gerado: $OUT  (envie para o suporte)"
