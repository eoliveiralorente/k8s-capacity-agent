#!/usr/bin/env bash
# Capacity Agent — instalação para __CUSTOMER__ (versão __VERSION__)
#
#   ./instalar.sh                      usa o contexto atual do kubectl
#   KUBE_CONTEXT=meu-ctx ./instalar.sh  escolhe o contexto
#   NAMESPACE=outro ./instalar.sh       muda o namespace (padrão: capacity-agent)
#
# Instalação somente leitura. Usa o helm se estiver instalado; senão, aplica os manifestos com kubectl.
set -uo pipefail
cd "$(dirname "$0")"

NAMESPACE="${NAMESPACE:-capacity-agent}"
LOG="instalacao-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

K=(kubectl); H=(helm)
if [ -n "${KUBE_CONTEXT:-}" ]; then K+=(--context "$KUBE_CONTEXT"); H+=(--kube-context "$KUBE_CONTEXT"); fi

ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; WARNINGS=$((WARNINGS+1)); }
fail() { printf '  \033[31m✘\033[0m %s\n' "$*"; FAILS=$((FAILS+1)); }
WARNINGS=0; FAILS=0

echo "Capacity Agent __VERSION__ · __CUSTOMER__"
echo
echo "1/5  Verificando o ambiente"
command -v kubectl >/dev/null && ok "kubectl encontrado" || { fail "kubectl não encontrado. Instale: https://kubernetes.io/docs/tasks/tools/"; }
[ "$FAILS" -gt 0 ] && exit 1

CTX="$("${K[@]}" config current-context 2>/dev/null || echo '?')"
if "${K[@]}" get namespaces >/dev/null 2>&1; then ok "cluster acessível (contexto: $CTX)"; else fail "não consegui acessar o cluster (contexto: $CTX). Confira o kubeconfig/VPN."; exit 1; fi

MINOR="$("${K[@]}" version -o json 2>/dev/null | sed -n 's/.*"minor": *"\([0-9]*\).*/\1/p' | tail -1)"
if [ -n "$MINOR" ] && [ "$MINOR" -lt 27 ]; then fail "Kubernetes 1.$MINOR: é preciso 1.27 ou superior"; else ok "versão do Kubernetes: 1.${MINOR:-?}"; fi

for check in "create clusterroles" "create clusterrolebindings" "create namespaces"; do
  "${K[@]}" auth can-i $check >/dev/null 2>&1 || fail "seu usuário não pode '$check' (a instalação precisa de admin só agora)"
done
[ "$FAILS" -eq 0 ] && ok "permissões de administrador para instalar"

if "${K[@]}" top nodes >/dev/null 2>&1; then ok "metrics-server funcionando"
else warn "metrics-server não respondeu: a ferramenta funciona, mas sem o uso real de CPU/memória. Instale: https://github.com/kubernetes-sigs/metrics-server"; fi

if "${K[@]}" get storageclass -o jsonpath='{range .items[*]}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}' 2>/dev/null | grep -q true; then
  ok "StorageClass padrão encontrada"
else warn "nenhuma StorageClass padrão: defina persistence.storageClassName em values-__SLUG__.yaml"; fi

USE_HELM=0
if command -v helm >/dev/null; then USE_HELM=1; ok "helm encontrado (instalação via helm)"
elif [ -f manifestos-__SLUG__.yaml ]; then ok "sem helm: vou aplicar os manifestos com kubectl"
else fail "helm não encontrado. Instale o helm 3.8+: https://helm.sh/docs/intro/install/"; fi

[ "$FAILS" -gt 0 ] && { echo; echo "Corrija os itens com ✘ e rode de novo."; exit 1; }

echo
echo "2/5  Confirmação"
read -r -p "  Instalar o Capacity Agent no cluster '$CTX', namespace '$NAMESPACE'? [s/N] " answer
case "$answer" in s|S|sim|SIM) ;; *) echo "  Cancelado."; exit 1;; esac

echo
echo "3/5  Preparando o namespace e o acesso à imagem"
"${K[@]}" create namespace "$NAMESPACE" --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null && ok "namespace $NAMESPACE"
if "${K[@]}" -n "$NAMESPACE" get secret __PULL_SECRET__ >/dev/null 2>&1; then
  ok "acesso à imagem já configurado"
else
  echo "  Cole o token de acesso à imagem (recebido separadamente; não aparece na tela) e tecle Enter:"
  read -r -s TOKEN; echo
  [ -n "$TOKEN" ] || { fail "token vazio"; exit 1; }
  "${K[@]}" -n "$NAMESPACE" create secret docker-registry __PULL_SECRET__ \
    --docker-server=__REGISTRY__ --docker-username=__REGISTRY_USER__ --docker-password="$TOKEN" >/dev/null && ok "acesso à imagem configurado"
  unset TOKEN
fi
if ! "${K[@]}" -n "$NAMESPACE" get secret capacity-agent-encryption >/dev/null 2>&1; then
  KEY="$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n')"
  "${K[@]}" -n "$NAMESPACE" create secret generic capacity-agent-encryption --from-literal=key="$KEY" >/dev/null
  "${K[@]}" -n "$NAMESPACE" annotate secret capacity-agent-encryption helm.sh/resource-policy=keep >/dev/null
  unset KEY
  ok "chave de criptografia criada (fica no cluster)"
fi

echo
echo "4/5  Instalando"
if [ "$USE_HELM" -eq 1 ]; then
  "${H[@]}" upgrade --install capacity-agent ./__CHART_FILE__ --namespace "$NAMESPACE" \
    -f values-__SLUG__.yaml --set encryption.existingSecret=capacity-agent-encryption || { fail "helm falhou"; exit 1; }
else
  sed "s/namespace: capacity-agent$/namespace: $NAMESPACE/" manifestos-__SLUG__.yaml | "${K[@]}" -n "$NAMESPACE" apply -f - || { fail "kubectl apply falhou"; exit 1; }
fi
ok "recursos aplicados"

echo
echo "5/5  Aguardando o painel ficar pronto (até 4 min)"
if "${K[@]}" -n "$NAMESPACE" rollout status deploy/capacity-agent --timeout=240s; then
  ok "Capacity Agent rodando"
else
  fail "o painel não ficou pronto. Diagnóstico:"
  "${K[@]}" -n "$NAMESPACE" get pods -o wide
  REASON="$("${K[@]}" -n "$NAMESPACE" get pods -o jsonpath='{range .items[*]}{.status.containerStatuses[*].state.waiting.reason}{" "}{.status.conditions[?(@.type=="PodScheduled")].reason}{"\n"}{end}')"
  case "$REASON" in
    *ImagePull*|*ErrImage*) echo "  → A imagem não foi baixada: o token pode estar errado ou expirado. Rode:"
                            echo "    kubectl -n $NAMESPACE delete secret __PULL_SECRET__   e depois ./instalar.sh de novo";;
    *Unschedulable*)        echo "  → O pod não coube em nenhum node ou o volume não foi criado. Veja os eventos abaixo.";;
    *CrashLoop*)            echo "  → O contêiner está reiniciando. Logs:"; "${K[@]}" -n "$NAMESPACE" logs deploy/capacity-agent --tail=30;;
  esac
  "${K[@]}" -n "$NAMESPACE" get events --sort-by=.lastTimestamp | tail -15
  echo
  echo "  Envie o arquivo $LOG para o suporte (ele não contém o token)."
  exit 1
fi

cat <<NEXT

Pronto! Próximos passos:
  1. Abra o painel:  kubectl -n $NAMESPACE port-forward svc/capacity-agent 8080:80
     e acesse http://localhost:8080
  2. Clique em "Criar conta" (essa conta vira o administrador).
  3. Usuários e custos → Licença: instale o arquivo __LICENSE_FILE__
  4. Usuários e custos → Custos da infraestrutura: cadastre o preço das suas máquinas.
  5. Visão Geral → Nova Avaliação.

Registro desta instalação: $LOG
NEXT
