#!/usr/bin/env bash
# Capacity Agent — instalação para __CUSTOMER__ (versão __VERSION__)
#
#   bash instalar.sh                                usa o contexto atual do kubectl
#   bash instalar.sh --storage-class=<nome>         usa uma StorageClass específica
#   bash instalar.sh --pular-teste-storage          não testa a criação de volume antes de instalar
#   bash instalar.sh --storage-local                se o storage do cluster falhar, usa o disco dos nodes sem perguntar
#   KUBE_CONTEXT=meu-ctx bash instalar.sh           escolhe o contexto
#   NAMESPACE=outro bash instalar.sh                muda o namespace (padrão: capacity-agent)
#   RELEASE=outro-nome bash instalar.sh             segunda instalação no mesmo cluster (padrão: capacity-agent)
#
# Instalação somente leitura. Usa o helm se estiver instalado; senão, aplica os manifestos com kubectl.
# Rode com "bash instalar.sh": funciona mesmo se o arquivo perdeu a permissão de execução no download.
set -uo pipefail
cd "$(dirname "$0")" || exit 1

NAMESPACE="${NAMESPACE:-capacity-agent}"
RELEASE="${RELEASE:-capacity-agent}"
STORAGE_CLASS="${STORAGE_CLASS:-}"
PULAR_TESTE_STORAGE="${PULAR_TESTE_STORAGE:-0}"
STORAGE_TEST_TIMEOUT="${STORAGE_TEST_TIMEOUT:-90}"
STORAGE_TEST_IMAGE="${STORAGE_TEST_IMAGE:-registry.k8s.io/pause:3.10}"
STORAGE_TEST_NAME="capacity-agent-storage-test"
STORAGE_LOCAL="${STORAGE_LOCAL:-0}"
LOCAL_PATH_VERSION="${LOCAL_PATH_VERSION:-v0.0.37}"
USOU_STORAGE_LOCAL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --storage-class=*)     STORAGE_CLASS="${1#*=}" ;;
    --storage-class)       shift; STORAGE_CLASS="${1:-}" ;;
    --pular-teste-storage) PULAR_TESTE_STORAGE=1 ;;
    --storage-local)       STORAGE_LOCAL=1 ;;
    -h|--help)             sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opção desconhecida: $1 (use --help)"; exit 1 ;;
  esac
  shift
done

LOG="instalacao-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

K=(kubectl); H=(helm)
if [ -n "${KUBE_CONTEXT:-}" ]; then K+=(--context "$KUBE_CONTEXT"); H+=(--kube-context "$KUBE_CONTEXT"); fi

ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; WARNINGS=$((WARNINGS+1)); }
fail() { printf '  \033[31m✘\033[0m %s\n' "$*"; FAILS=$((FAILS+1)); }
info() { printf '    %s\n' "$*"; }
WARNINGS=0; FAILS=0

# =============================================================================
#  Storage: tradução de erros, StorageClasses e teste real de criação de volume
# =============================================================================

# Categoria de uma mensagem de erro de volume.
storage_classificar() {
  case "$1" in
    *VolumeSizeExceedsAvailableQuota*|*"exceeded quota"*|*ResourceExhausted*|*QuotaExceeded*|*"exceeded your quota"*|*"exceeds allowed gigabytes"*)
      echo cota ;;
    *"no storage class is set"*|*"unbound immediate PersistentVolumeClaims"*|*'storageclass.storage.k8s.io "'*'" not found'*)
      echo sem_storageclass ;;
    *VolumeTypeNotFound*|*"Volume type with name"*|*"volume type"*"could not be found"*|*"Invalid volume type"*|*"invalid volume type"*)
      echo politica_invalida ;;
    *"availability zone"*|*"Availability zone"*|*AvailabilityZone*)
      echo zona ;;
    *Unauthorized*|*AccessDenied*|*UnauthorizedOperation*|*"got 401"*|*"got 403"*)
      echo credenciais ;;
    *"Waiting for a volume to be created"*)
      echo provisionador_parado ;;
    *)
      echo desconhecido ;;
  esac
}

# Erros que não se resolvem sozinhos: não adianta esperar o timeout.
storage_definitivo() {
  case "$1" in cota|sem_storageclass|politica_invalida|credenciais) return 0 ;; *) return 1 ;; esac
}

# Causa e ação, em português, para uma mensagem de erro de volume.
storage_explicar() {
  local msg="$1" detalhe
  case "$(storage_classificar "$msg")" in
    cota)
      info "Causa: a cota de disco do projeto no provedor acabou ou está zerada."
      detalhe="$(printf '%s' "$msg" | grep -oE 'Requested [0-9]+G, quota is [0-9]+G and [0-9]+G has been consumed' | head -n1)"
      [ -n "$detalhe" ] && info "Detalhe: $detalhe"
      info "Ação: peça ao provedor (ou ajuste no painel) mais cota de volumes para a"
      info "      política de storage usada, ou use outra StorageClass com --storage-class=<nome>."
      ;;
    sem_storageclass)
      info "Causa: o volume foi pedido sem StorageClass e o cluster não tem uma padrão."
      info "Ação: crie/marque uma StorageClass padrão (veja o GUIA_RAPIDO.md) ou rode"
      info "      de novo com --storage-class=<nome>."
      ;;
    politica_invalida)
      info "Causa: a política/tipo de storage da StorageClass não existe no provedor."
      info "Ação: confira o parâmetro 'type' da StorageClass com os tipos de volume do provedor."
      ;;
    zona)
      info "Causa: o volume não pôde ser criado na zona de disponibilidade dos nodes."
      info "Ação: confira as zonas permitidas na StorageClass e onde os nodes estão."
      ;;
    credenciais)
      info "Causa: o driver de storage do cluster não tem permissão no provedor."
      info "Ação: verifique as credenciais/role do driver CSI com o time de plataforma."
      ;;
    provisionador_parado)
      info "Causa: nenhum driver de storage respondeu ao pedido de volume."
      info "Ação: confira se o driver CSI está rodando:"
      info "      kubectl get csidrivers; kubectl get pods -A | grep -i csi"
      ;;
    *)
      info "Erro informado pelo cluster:"
      info "  $msg"
      ;;
  esac
}

# Última mensagem de falha de volume registrada para um PVC.
storage_ultimo_erro() {
  "${K[@]}" -n "$1" get events \
    --field-selector "involvedObject.kind=PersistentVolumeClaim,involvedObject.name=$2" \
    --sort-by=.metadata.creationTimestamp \
    -o jsonpath='{range .items[*]}{.reason}{"\t"}{.message}{"\n"}{end}' 2>/dev/null \
    | grep -E '^(ProvisioningFailed|FailedBinding|ExternalProvisioning)'$'\t' \
    | tail -n1 | cut -f2-
}

# Nome da StorageClass padrão (vazio se não houver).
storage_padrao() {
  "${K[@]}" get storageclass -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\t"}{.metadata.annotations.storageclass\.beta\.kubernetes\.io/is-default-class}{"\n"}{end}' 2>/dev/null \
    | awk -F'\t' '$2=="true" || $3=="true" {print $1; exit}'
}

storage_listar() {
  local lista
  lista="$("${K[@]}" get storageclass -o jsonpath='{range .items[*]}{.metadata.name} ({.provisioner}){"\n"}{end}' 2>/dev/null)"
  if [ -z "$lista" ]; then
    info "O cluster não tem nenhuma StorageClass."
    if "${K[@]}" get csidrivers -o name 2>/dev/null | grep -q .; then
      info "Drivers de storage encontrados (crie uma StorageClass para um deles):"
      "${K[@]}" get csidrivers -o jsonpath='{range .items[*]}{"      - "}{.metadata.name}{"\n"}{end}' 2>/dev/null
    else
      info "Também não há driver de storage (CSI). Fale com o time de plataforma/provedor."
    fi
    info "Veja o passo a passo no GUIA_RAPIDO.md."
  else
    info "StorageClasses disponíveis (rode de novo com --storage-class=<nome>):"
    printf '%s\n' "$lista" | sed 's/^/      - /'
  fi
}

# PVs que pertencem (ou pertenceram) ao PVC de teste.
storage_pvs_do_teste() {
  "${K[@]}" get pv -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.claimRef.name}{"\t"}{.spec.claimRef.namespace}{"\n"}{end}' 2>/dev/null \
    | awk -F'\t' -v n="$STORAGE_TEST_NAME" -v ns="$NAMESPACE" '$2==n && $3==ns {print $1}'
}

# Remove pod, PVC e PV de teste. Muda o PV para Delete antes, para o volume
# no provedor também ser apagado mesmo quando a StorageClass usa Retain.
storage_limpar_teste() {
  local pv pvs
  pvs="$(storage_pvs_do_teste)"
  for pv in $pvs; do
    "${K[@]}" patch pv "$pv" --type merge -p '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}' >/dev/null 2>&1
  done
  "${K[@]}" -n "$NAMESPACE" delete pod "$STORAGE_TEST_NAME" --ignore-not-found --wait=true --timeout=60s >/dev/null 2>&1
  "${K[@]}" -n "$NAMESPACE" delete pvc "$STORAGE_TEST_NAME" --ignore-not-found --wait=true --timeout=60s >/dev/null 2>&1
  for pv in $pvs; do
    "${K[@]}" delete pv "$pv" --ignore-not-found --wait=false >/dev/null 2>&1
    if ! "${K[@]}" wait --for=delete "pv/$pv" --timeout=90s >/dev/null 2>&1; then
      warn "o volume de teste $pv ainda está sendo removido pelo provedor"
      info "Confira depois: kubectl get pv $pv (deve sumir sozinho)"
    fi
  done
}

# Cria um PVC de 1Gi + pod mínimo, espera o volume ficar Bound e limpa tudo.
# Retorna 0 se o cluster consegue criar volumes.
storage_testar() {
  local sc="$1" sc_linha="" errf fase msg="" inicio resultado=1
  [ -n "$STORAGE_CLASS" ] && sc_linha="  storageClassName: ${STORAGE_CLASS}"

  trap 'storage_limpar_teste' EXIT
  trap 'storage_limpar_teste; exit 130' INT
  trap 'storage_limpar_teste; exit 143' TERM

  storage_limpar_teste   # restos de uma execução interrompida

  errf="$(mktemp)"
  if ! "${K[@]}" apply -f - >/dev/null 2>"$errf" <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${STORAGE_TEST_NAME}
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: ${STORAGE_TEST_NAME}
    app.kubernetes.io/part-of: capacity-agent
  annotations:
    capacity-agent/descricao: "Teste temporario de storage do instalador. Pode ser apagado."
spec:
  accessModes: ["ReadWriteOnce"]
${sc_linha}
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: ${STORAGE_TEST_NAME}
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: ${STORAGE_TEST_NAME}
    app.kubernetes.io/part-of: capacity-agent
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  terminationGracePeriodSeconds: 0
  securityContext:
    runAsNonRoot: true
    runAsUser: 65535
    runAsGroup: 65535
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: teste
      image: ${STORAGE_TEST_IMAGE}
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      resources:
        requests: { cpu: 10m, memory: 16Mi }
        limits:   { cpu: 50m, memory: 32Mi }
      volumeMounts:
        - name: dados
          mountPath: /teste
  volumes:
    - name: dados
      persistentVolumeClaim:
        claimName: ${STORAGE_TEST_NAME}
EOF
  then
    fail "não foi possível criar o teste de storage"
    sed 's/^/    /' "$errf"
    info "Se o cluster bloqueia esse tipo de recurso, rode com --pular-teste-storage."
    rm -f "$errf"
    storage_limpar_teste
    trap - EXIT INT TERM
    return 1
  fi
  rm -f "$errf"

  # O volume fica Bound quando o provedor o cria; não depende do pod chegar a rodar.
  inicio=$SECONDS
  while [ $((SECONDS - inicio)) -lt "$STORAGE_TEST_TIMEOUT" ]; do
    fase="$("${K[@]}" -n "$NAMESPACE" get pvc "$STORAGE_TEST_NAME" -o jsonpath='{.status.phase}' 2>/dev/null)"
    if [ "$fase" = "Bound" ]; then resultado=0; break; fi
    msg="$(storage_ultimo_erro "$NAMESPACE" "$STORAGE_TEST_NAME")"
    if [ -n "$msg" ] && storage_definitivo "$(storage_classificar "$msg")"; then break; fi
    sleep 3
  done

  storage_limpar_teste
  trap - EXIT INT TERM

  if [ "$resultado" -eq 0 ]; then
    ok "storage funcionando: volume de teste criado e removido (StorageClass: $sc)"
  else
    fail "o cluster não conseguiu criar um volume (StorageClass: $sc)"
    storage_explicar "${msg:-Waiting for a volume to be created}"
  fi
  return "$resultado"
}

# Diagnóstico do passo 5: explica PVCs do namespace que não ficaram Bound.
storage_diagnosticar_pvcs() {
  local linha pvc fase msg encontrou=1
  while IFS=$'\t' read -r pvc fase; do
    [ -z "$pvc" ] && continue
    [ "$pvc" = "$STORAGE_TEST_NAME" ] && continue
    [ "$fase" = "Bound" ] && continue
    msg="$(storage_ultimo_erro "$NAMESPACE" "$pvc")"
    [ -z "$msg" ] && continue
    echo "  → O volume de dados ($pvc) não foi criado."
    storage_explicar "$msg"
    encontrou=0
  done < <("${K[@]}" -n "$NAMESPACE" get pvc -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\n"}{end}' 2>/dev/null)
  return "$encontrou"
}

# Plano B: storage no disco dos nodes (local-path-provisioner).
# Pergunta ao cliente (ou aceita direto com --storage-local), instala se preciso
# e passa a usar a StorageClass local-path SÓ para o Capacity Agent (não vira padrão).
oferecer_storage_local() {
  local resposta errf url
  echo
  echo "  Alternativa: guardar os dados do painel no disco de um dos nodes (local-path)."
  info "Funciona sem depender do storage do provedor, mas os dados ficam presos a um node:"
  info "se ele for recriado (upgrade, autoscaler, troca de VM), o histórico do painel se perde."
  info "Bom para avaliação; em produção, prefira corrigir o storage do provedor."
  if [ "$STORAGE_LOCAL" = "1" ]; then
    resposta=s; info "(--storage-local: aceito automaticamente)"
  else
    read -r -p "  Usar storage local nos nodes? [s/N] " resposta
  fi
  case "$resposta" in s|S|sim|SIM) ;; *) return 1 ;; esac

  if "${K[@]}" get storageclass local-path >/dev/null 2>&1; then
    ok "StorageClass local-path já existe no cluster"
  else
    url="https://raw.githubusercontent.com/rancher/local-path-provisioner/${LOCAL_PATH_VERSION}/deploy/local-path-storage.yaml"
    errf="$(mktemp)"
    if ! "${K[@]}" apply -f "$url" >/dev/null 2>"$errf"; then
      fail "não consegui instalar o storage local"
      sed 's/^/    /' "$errf"; rm -f "$errf"
      info "Esta máquina precisa acessar o GitHub, e os nodes precisam baixar imagens do Docker Hub."
      return 1
    fi
    rm -f "$errf"
    if ! "${K[@]}" -n local-path-storage rollout status deploy/local-path-provisioner --timeout=120s >/dev/null 2>&1; then
      fail "o provisionador de storage local não ficou pronto"
      "${K[@]}" -n local-path-storage get pods 2>/dev/null | sed 's/^/    /'
      return 1
    fi
    ok "storage local instalado (local-path-provisioner $LOCAL_PATH_VERSION)"
  fi
  STORAGE_CLASS="local-path"; SC_USADA="local-path"; USOU_STORAGE_LOCAL=1
  return 0
}

# Chart do helm: aceita o .tgz ou a pasta extraída.
achar_chart() {
  local c
  for c in ./__CHART_FILE__ ./capacity-agent-__VERSION__ ./capacity-agent-__VERSION__/capacity-agent; do
    if [ -f "$c" ] || [ -f "$c/Chart.yaml" ]; then echo "$c"; return 0; fi
  done
  c="$(find . -maxdepth 3 -name Chart.yaml -path '*capacity-agent*' 2>/dev/null | head -n1)"
  [ -n "$c" ] && { dirname "$c"; return 0; }
  return 1
}

# =============================================================================

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

# StorageClass: sem ela o painel nunca sobe, então bloqueia aqui.
if [ -n "$STORAGE_CLASS" ]; then
  if "${K[@]}" get storageclass "$STORAGE_CLASS" >/dev/null 2>&1; then
    SC_USADA="$STORAGE_CLASS"; ok "StorageClass escolhida: $SC_USADA"
  else
    fail "a StorageClass '$STORAGE_CLASS' não existe neste cluster"; storage_listar
  fi
else
  SC_USADA="$(storage_padrao)"
  if [ -n "$SC_USADA" ]; then ok "StorageClass padrão: $SC_USADA"
  elif [ "$PULAR_TESTE_STORAGE" = "1" ]; then
    fail "nenhuma StorageClass padrão: o painel precisa de um volume para guardar os dados"; storage_listar
  else
    warn "nenhuma StorageClass padrão: no passo 3 vou oferecer guardar os dados no disco dos nodes"
  fi
fi

OTHER_NS="$("${K[@]}" get clusterrole "$RELEASE-read" -o jsonpath='{.metadata.annotations.meta\.helm\.sh/release-namespace}' 2>/dev/null || true)"
if [ -n "$OTHER_NS" ] && [ "$OTHER_NS" != "$NAMESPACE" ]; then
  fail "já existe um Capacity Agent neste cluster (namespace $OTHER_NS). Para atualizar, rode com NAMESPACE=$OTHER_NS; para uma segunda instalação, use também RELEASE=outro-nome"
else ok "nenhuma instalação conflitante"; fi

USE_HELM=0
if command -v helm >/dev/null; then
  if CHART="$(achar_chart)"; then USE_HELM=1; ok "helm encontrado (instalação via helm)"
  elif [ -f manifestos-__SLUG__.yaml ]; then warn "helm encontrado, mas o pacote do chart não está na pasta: vou aplicar os manifestos com kubectl"
  else fail "pacote do chart (__CHART_FILE__) não encontrado nesta pasta"; fi
elif [ -f manifestos-__SLUG__.yaml ]; then ok "sem helm: vou aplicar os manifestos com kubectl"
else fail "helm não encontrado. Instale o helm 3.8+: https://helm.sh/docs/intro/install/"; fi

[ "$FAILS" -gt 0 ] && { echo; echo "Corrija os itens com ✘ e rode de novo."; exit 1; }

echo
echo "2/5  Confirmação"
echo "  Ao continuar, você declara que leu e concorda com os Termos de Uso (TERMOS_DE_USO.md)"
echo "  e com a Política de Privacidade (PRIVACIDADE.md), que estão nesta pasta."
CURRENT_IMAGE="$("${K[@]}" -n "$NAMESPACE" get deploy "$RELEASE" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)"
if [ -n "$CURRENT_IMAGE" ]; then
  echo "  Já existe um Capacity Agent neste namespace (versão ${CURRENT_IMAGE##*:}). Os dados e a licença são mantidos."
  read -r -p "  Atualizar para a versão __VERSION__ no cluster '$CTX', namespace '$NAMESPACE'? [s/N] " answer
else
  read -r -p "  Instalar o Capacity Agent __VERSION__ no cluster '$CTX', namespace '$NAMESPACE'? [s/N] " answer
fi
case "$answer" in s|S|sim|SIM) ;; *) echo "  Cancelado."; exit 1;; esac
echo "  Termos de Uso e Política de Privacidade aceitos em $(date '+%d/%m/%Y %H:%M:%S') por $(whoami)@$(hostname) (cluster $CTX)."

echo
echo "3/5  Preparando o namespace, o storage e o acesso à imagem"
"${K[@]}" create namespace "$NAMESPACE" --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null && ok "namespace $NAMESPACE"

PVC_ATUAL="$("${K[@]}" -n "$NAMESPACE" get pvc "$RELEASE-data" -o jsonpath='{.status.phase}' 2>/dev/null)"
if [ "$PVC_ATUAL" = "Bound" ]; then
  ok "volume de dados já existe (atualização): teste de storage não é necessário"
elif [ "$PULAR_TESTE_STORAGE" = "1" ]; then
  warn "teste de storage pulado (--pular-teste-storage)"
else
  STORAGE_OK=0
  if [ -n "$SC_USADA" ]; then
    echo "  Testando se o cluster consegue criar um volume (até ${STORAGE_TEST_TIMEOUT}s)..."
    storage_testar "$SC_USADA" && STORAGE_OK=1
  fi
  if [ "$STORAGE_OK" -eq 0 ] && [ "$SC_USADA" != "local-path" ] && oferecer_storage_local; then
    echo "  Testando o storage local (até ${STORAGE_TEST_TIMEOUT}s)..."
    storage_testar "$SC_USADA" && STORAGE_OK=1
  fi
  if [ "$STORAGE_OK" -eq 0 ]; then
    echo
    echo "  Nada foi instalado. Corrija o storage e rode de novo."
    echo "  Envie o arquivo $LOG para o suporte se precisar de ajuda."
    exit 1
  fi
fi

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

# PVC de uma tentativa anterior que ficou sem volume: recria com a StorageClass atual.
REESCALAR=0
PVC_ANTIGO="$("${K[@]}" -n "$NAMESPACE" get pvc "$RELEASE-data" -o jsonpath='{.status.phase}' 2>/dev/null)"
if [ "$PVC_ANTIGO" = "Pending" ]; then
  REESCALAR=1
  "${K[@]}" -n "$NAMESPACE" delete pvc "$RELEASE-data" --wait=false >/dev/null 2>&1
  "${K[@]}" -n "$NAMESPACE" scale "deploy/$RELEASE" --replicas=0 >/dev/null 2>&1
  "${K[@]}" -n "$NAMESPACE" wait --for=delete "pvc/$RELEASE-data" --timeout=60s >/dev/null 2>&1
  ok "volume pendente de uma tentativa anterior removido (estava vazio)"
fi

echo
echo "4/5  Instalando"
if [ "$USE_HELM" -eq 1 ]; then
  SC_ARGS=()
  [ -n "$STORAGE_CLASS" ] && SC_ARGS=(--set "persistence.storageClassName=$STORAGE_CLASS")
  "${H[@]}" upgrade --install "$RELEASE" "$CHART" --namespace "$NAMESPACE" \
    -f values-__SLUG__.yaml --set encryption.existingSecret=capacity-agent-encryption \
    "${SC_ARGS[@]}" || { fail "helm falhou"; exit 1; }
else
  [ "$RELEASE" = "capacity-agent" ] || { fail "sem helm, só é possível instalar com RELEASE=capacity-agent"; exit 1; }
  sed "s/namespace: capacity-agent$/namespace: $NAMESPACE/" manifestos-__SLUG__.yaml \
    | awk -v sc="$STORAGE_CLASS" '
        /^---/ { pvc=0 }
        /^kind: PersistentVolumeClaim/ { pvc=1 }
        { print }
        pvc && sc != "" && /^spec:/ { print "  storageClassName: " sc }
      ' \
    | "${K[@]}" -n "$NAMESPACE" apply -f - || { fail "kubectl apply falhou"; exit 1; }
fi
if [ "$REESCALAR" -eq 1 ]; then "${K[@]}" -n "$NAMESPACE" scale "deploy/$RELEASE" --replicas=1 >/dev/null 2>&1; fi
ok "recursos aplicados"

echo
echo "5/5  Aguardando o painel ficar pronto (até 4 min)"
if "${K[@]}" -n "$NAMESPACE" rollout status "deploy/$RELEASE" --timeout=240s; then
  ok "Capacity Agent rodando"
else
  fail "o painel não ficou pronto. Diagnóstico:"
  "${K[@]}" -n "$NAMESPACE" get pods -o wide
  if ! storage_diagnosticar_pvcs; then
    REASON="$("${K[@]}" -n "$NAMESPACE" get pods -o jsonpath='{range .items[*]}{.status.containerStatuses[*].state.waiting.reason}{" "}{.status.conditions[?(@.type=="PodScheduled")].reason}{"\n"}{end}')"
    case "$REASON" in
      *ImagePull*|*ErrImage*) echo "  → A imagem não foi baixada: o token pode estar errado ou expirado. Rode:"
                              echo "    kubectl -n $NAMESPACE delete secret __PULL_SECRET__   e depois bash instalar.sh de novo";;
      *Unschedulable*)        echo "  → O pod não coube em nenhum node (CPU/memória ou regras de agendamento). Veja os eventos abaixo.";;
      *CrashLoop*)            echo "  → O contêiner está reiniciando. Logs:"; "${K[@]}" -n "$NAMESPACE" logs "deploy/$RELEASE" --tail=30;;
    esac
  fi
  echo
  "${K[@]}" -n "$NAMESPACE" get events --sort-by=.lastTimestamp | tail -15
  echo
  echo "  Envie o arquivo $LOG para o suporte (ele não contém o token)."
  exit 1
fi

if [ "$USOU_STORAGE_LOCAL" -eq 1 ] || [ "${SC_USADA:-}" = "local-path" ]; then
  NODE_DADOS="$("${K[@]}" get pv -o jsonpath="{range .items[?(@.spec.claimRef.name==\"$RELEASE-data\")]}{.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]}{end}" 2>/dev/null)"
  echo
  warn "os dados do painel estão no disco do node ${NODE_DADOS:-(veja: kubectl get pv)}"
  info "Se esse node for recriado, o histórico se perde. Guarde fora do cluster a chave de criptografia:"
  info "  kubectl -n $NAMESPACE get secret capacity-agent-encryption -o yaml > chave-capacity-agent.yaml"
  info "Quando o storage do provedor estiver disponível, migre para ele (fale com o suporte)."
fi

cat <<NEXT

Pronto! Próximos passos:
  1. Abra o painel:  kubectl -n $NAMESPACE port-forward svc/$RELEASE 8080:80
     e acesse http://localhost:8080
  2. Clique em "Criar conta" (essa conta vira o administrador).
  3. Usuários e custos → Licença: instale o arquivo __LICENSE_FILE__
  4. Usuários e custos → Custos da infraestrutura: cadastre o preço das suas máquinas.
  5. Visão Geral → Nova Avaliação.

Registro desta instalação: $LOG
NEXT
