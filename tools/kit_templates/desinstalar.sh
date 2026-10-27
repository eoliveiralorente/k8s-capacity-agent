#!/usr/bin/env bash
# Remove o Capacity Agent do cluster (a chave de criptografia e o volume de dados também são apagados).
set -uo pipefail
NAMESPACE="${NAMESPACE:-capacity-agent}"
RELEASE="${RELEASE:-capacity-agent}"
K=(kubectl); H=(helm)
if [ -n "${KUBE_CONTEXT:-}" ]; then K+=(--context "$KUBE_CONTEXT"); H+=(--kube-context "$KUBE_CONTEXT"); fi
CTX="$("${K[@]}" config current-context 2>/dev/null || echo '?')"
read -r -p "Remover o Capacity Agent e TODOS os dados dele do cluster '$CTX' (namespace $NAMESPACE)? [s/N] " a
case "$a" in s|S|sim|SIM) ;; *) echo "Cancelado."; exit 1;; esac
command -v helm >/dev/null && "${H[@]}" -n "$NAMESPACE" uninstall "$RELEASE" 2>/dev/null
"${K[@]}" delete clusterrolebinding,clusterrole -l "app.kubernetes.io/instance=$RELEASE" --ignore-not-found
"${K[@]}" delete namespace "$NAMESPACE" --ignore-not-found
echo "Removido."
