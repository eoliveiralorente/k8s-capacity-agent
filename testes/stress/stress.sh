#!/usr/bin/env bash
# Stress test de um cluster com autoscaling + validação do Capacity Agent.
#
#   export KUBECONFIG=~/.kube/k8s-auto.yaml        (obrigatório: o kubeconfig baixado do painel)
#   bash stress.sh checar                 confere cluster, metrics-server e autoscaler (não cria nada)
#   bash stress.sh monitorar              linha do tempo a cada 15 s em CSV (deixe num terminal separado)
#   bash stress.sh cpu        [carga]     HPA + gerador de carga (padrão: 4 geradores)
#   bash stress.sh nodes      [extras]    pods com requests altos que forçam o autoscaler a criar nodes (padrão: 2)
#   bash stress.sh memoria                OOMKill + pod usando muito mais memória do que reservou
#   bash stress.sh vizinho                pod sem limit consumindo CPU muito acima do request
#   bash stress.sh desperdicio            pods ociosos com requests altos (sobra reservada)
#   bash stress.sh status                 situação agora
#   bash stress.sh parar                  zera a carga de todos os cenários (para observar o scale-down)
#   bash stress.sh scaledown              explica por que o autoscaler não removeu os workers ociosos
#   bash stress.sh relatorio              resumo do CSV + eventos do autoscaler em relatorio-*.md
#   bash stress.sh limpar                 apaga o namespace do teste
#
# Segurança: só roda se KUBECONFIG apontar para um arquivo e TODOS os nodes tiverem o prefixo
# esperado (CLUSTER_PREFIX, padrão k8s-auto). Tudo fica no namespace "stress-test".
set -uo pipefail

NS="${NS:-stress-test}"
CLUSTER_PREFIX="${CLUSTER_PREFIX:-k8s-auto}"
INTERVALO="${INTERVALO:-15}"
DIR="$(cd "$(dirname "$0")" && pwd)"
CSV="$DIR/linha-do-tempo.csv"
STRESS_IMAGE="${STRESS_IMAGE:-polinux/stress:1.0.4}"
HPA_IMAGE="${HPA_IMAGE:-registry.k8s.io/hpa-example}"
POD_CPU_M="${POD_CPU_M:-500}"     # request de CPU dos pods do cenário nodes
POD_MEM_MI="${POD_MEM_MI:-512}"

ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✘\033[0m %s\n' "$*"; exit 1; }
k()    { kubectl "$@"; }

guarda() {
  [ -n "${KUBECONFIG:-}" ] || die "defina o KUBECONFIG do cluster de teste: export KUBECONFIG=~/.kube/k8s-auto.yaml"
  case "$KUBECONFIG" in *:*) die "KUBECONFIG com vários arquivos não é aceito aqui; use só o do cluster de teste";; esac
  [ -f "$KUBECONFIG" ] || die "arquivo não encontrado: $KUBECONFIG"
  local nodes outros
  nodes="$(k get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)" \
    || die "não consegui acessar o cluster com $KUBECONFIG"
  [ -n "$nodes" ] || die "o cluster não retornou nodes"
  outros="$(printf '%s\n' "$nodes" | grep -v "^$CLUSTER_PREFIX" || true)"
  [ -z "$outros" ] || die "há nodes sem o prefixo '$CLUSTER_PREFIX' (cluster errado?): $(echo $outros)"
}

workers() {  # nodes sem a label/taint de control plane
  k get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.labels.node-role\.kubernetes\.io/control-plane}{.metadata.labels.node-role\.kubernetes\.io/master}{"\t"}{.spec.taints[*].effect}{"\n"}{end}' \
    | awk -F'\t' '$2=="" && $3 !~ /NoSchedule/ {print $1}'
}

cpu_m() {  # "3920m" ou "4" -> milicores
  case "$1" in *m) echo "${1%m}";; *) awk -v c="$1" 'BEGIN{printf "%d", c*1000}';; esac
}

ns() { k create namespace "$NS" --dry-run=client -o yaml | k apply -f - >/dev/null; }

# -----------------------------------------------------------------------------
checar() {
  echo "== Cluster"
  ok "kubeconfig: $KUBECONFIG (contexto $(k config current-context))"
  ok "versão: $(k version -o json 2>/dev/null | sed -n 's/.*"gitVersion": *"\([^"]*\)".*/\1/p' | tail -1)"
  k get nodes -o wide | sed 's/^/    /'
  local w; w="$(workers)"
  [ -n "$w" ] && ok "workers: $(echo $w)" || warn "nenhum worker sem taint encontrado"

  echo "== metrics-server"
  if k top nodes >/dev/null 2>&1; then ok "kubectl top nodes responde (HPA e Capacity Agent vão ter métricas)"
  else warn "metrics-server não respondeu: o HPA não escala e o Capacity Agent fica sem uso real"; fi

  echo "== Autoscaler de nodes"
  local ca
  ca="$(k get deploy -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' | grep -i autoscaler || true)"
  [ -n "$ca" ] && ok "deployment: $(echo $ca)" || warn "nenhum deployment *autoscaler* visível (pode ser gerenciado pelo provedor, fora do cluster)"
  if k -n kube-system get configmap cluster-autoscaler-status >/dev/null 2>&1; then
    ok "cluster-autoscaler-status encontrado:"
    k -n kube-system get configmap cluster-autoscaler-status -o jsonpath='{.data.status}' | grep -iE 'Health|ScaleUp|ScaleDown|Nodes|minSize|maxSize' | head -12 | sed 's/^/      /'
  else
    warn "sem o configmap cluster-autoscaler-status: confira no painel do provedor o mínimo e o máximo de nodes do grupo"
  fi

  echo "== Storage (para instalar o Capacity Agent)"
  k get storageclass 2>/dev/null | sed 's/^/    /' || warn "sem StorageClass"
  echo
  echo "Antes de seguir, anote no painel do provedor o MÍNIMO e o MÁXIMO de workers do grupo: o"
  echo "cenário 'nodes' cria até ${EXTRAS:-2} workers a mais, e cada worker extra é custo enquanto existir."
}

# -----------------------------------------------------------------------------
monitorar() {
  [ -f "$CSV" ] || echo "hora,segundos,nodes,nodes_ready,workers,pods_pending,pods_running,oomkilled,hpa_atual,hpa_desejado,cpu_media_pct,mem_media_pct" > "$CSV"
  echo "Gravando em $CSV a cada ${INTERVALO}s. Ctrl+C para parar (pode deixar rodando o teste inteiro)."
  local t0=$SECONDS
  while true; do
    local hora nodes ready wk pend run oom hpa_a hpa_d top cpu mem
    hora="$(date +%H:%M:%S)"
    nodes="$(k get nodes --no-headers 2>/dev/null | wc -l)"
    ready="$(k get nodes --no-headers 2>/dev/null | awk '$2=="Ready"' | wc -l)"
    wk="$(workers 2>/dev/null | wc -l)"
    pend="$(k -n "$NS" get pods --field-selector=status.phase=Pending --no-headers 2>/dev/null | wc -l)"
    run="$(k -n "$NS" get pods --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)"
    oom="$(k -n "$NS" get pods -o jsonpath='{range .items[*]}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}' 2>/dev/null | grep -c OOMKilled)"
    hpa_a="$(k -n "$NS" get hpa php-apache -o jsonpath='{.status.currentReplicas}' 2>/dev/null)"
    hpa_d="$(k -n "$NS" get hpa php-apache -o jsonpath='{.status.desiredReplicas}' 2>/dev/null)"
    top="$(k top nodes --no-headers 2>/dev/null | awk '{gsub("%","",$3); gsub("%","",$5); c+=$3; m+=$5; n++} END{if(n) printf "%.0f,%.0f", c/n, m/n; else printf ","}')"
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$hora" $((SECONDS-t0)) "$nodes" "$ready" "$wk" "$pend" "$run" "$oom" "${hpa_a:-}" "${hpa_d:-}" "$top" >> "$CSV"
    printf '\r%s  nodes %s (ready %s, workers %s) · pending %s · running %s · OOM %s · HPA %s/%s · CPU/mem média %s%%   ' \
      "$hora" "$nodes" "$ready" "$wk" "$pend" "$run" "$oom" "${hpa_a:--}" "${hpa_d:--}" "${top/,/%\/}"
    sleep "$INTERVALO"
  done
}

# -----------------------------------------------------------------------------
cenario_cpu() {
  local carga="${1:-4}"
  ns
  k apply -f - >/dev/null <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: {name: php-apache, namespace: $NS, labels: {stress: cpu}}
spec:
  selector: {matchLabels: {app: php-apache}}
  template:
    metadata: {labels: {app: php-apache, stress: cpu}}
    spec:
      containers:
        - name: php-apache
          image: $HPA_IMAGE
          ports: [{containerPort: 80}]
          resources: {requests: {cpu: 200m, memory: 64Mi}, limits: {cpu: 500m, memory: 128Mi}}
---
apiVersion: v1
kind: Service
metadata: {name: php-apache, namespace: $NS}
spec: {selector: {app: php-apache}, ports: [{port: 80}]}
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: php-apache, namespace: $NS}
spec:
  scaleTargetRef: {apiVersion: apps/v1, kind: Deployment, name: php-apache}
  minReplicas: 1
  maxReplicas: ${HPA_MAX:-20}
  metrics:
    - type: Resource
      resource: {name: cpu, target: {type: Utilization, averageUtilization: 50}}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: gerador-carga, namespace: $NS, labels: {stress: cpu}}
spec:
  replicas: $carga
  selector: {matchLabels: {app: gerador-carga}}
  template:
    metadata: {labels: {app: gerador-carga, stress: cpu}}
    spec:
      containers:
        - name: carga
          image: busybox:1.36
          command: ["/bin/sh", "-c", "while true; do wget -q -O- http://php-apache >/dev/null 2>&1; done"]
          resources: {requests: {cpu: 50m, memory: 16Mi}, limits: {cpu: 200m, memory: 32Mi}}
EOF
  ok "cenário CPU iniciado: HPA de 1 a ${HPA_MAX:-20} réplicas (alvo 50%) e $carga gerador(es) de carga"
  echo "  Observe: HPA subindo → pods Pending → autoscaler criando node → pods Running."
  echo "  Aumentar a carga:  bash stress.sh cpu 10        Parar:  bash stress.sh parar"
}

cenario_nodes() {
  local extras="${1:-${EXTRAS:-2}}" total=0 n alloc reps
  for n in $(workers); do
    alloc="$(k get node "$n" -o jsonpath='{.status.allocatable.cpu}')"
    total=$(( total + $(cpu_m "$alloc") ))
  done
  [ "$total" -gt 0 ] || die "não consegui ler a CPU dos workers"
  local por_node=$(( total / $(workers | wc -l) ))
  # ocupa ~70% do que existe hoje + o equivalente a $extras workers novos
  reps=$(( (total * 70 / 100 + por_node * extras) / POD_CPU_M ))
  ns
  k apply -f - >/dev/null <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: {name: forca-nodes, namespace: $NS, labels: {stress: nodes}}
spec:
  replicas: $reps
  selector: {matchLabels: {app: forca-nodes}}
  template:
    metadata: {labels: {app: forca-nodes, stress: nodes}}
    spec:
      terminationGracePeriodSeconds: 0
      containers:
        - name: pause
          image: registry.k8s.io/pause:3.10
          resources: {requests: {cpu: ${POD_CPU_M}m, memory: ${POD_MEM_MI}Mi}, limits: {cpu: ${POD_CPU_M}m, memory: ${POD_MEM_MI}Mi}}
EOF
  ok "cenário nodes iniciado: $reps pods de ${POD_CPU_M}m/${POD_MEM_MI}Mi (workers hoje: ${total}m de CPU; pede ~$extras worker(s) a mais)"
  echo "  Mede: quanto tempo do primeiro Pending até o node novo ficar Ready e os pods rodarem."
  echo "  Se o máximo do grupo for menor, parte dos pods fica Pending: isso também é resultado (limite atingido)."
}

cenario_memoria() {
  ns
  k apply -f - >/dev/null <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: {name: oom-loop, namespace: $NS, labels: {stress: memoria}}
spec:
  replicas: 1
  selector: {matchLabels: {app: oom-loop}}
  template:
    metadata: {labels: {app: oom-loop, stress: memoria}}
    spec:
      containers:
        - name: stress
          image: $STRESS_IMAGE
          command: ["stress", "--vm", "1", "--vm-bytes", "300M", "--vm-hang", "0"]
          resources: {requests: {cpu: 50m, memory: 128Mi}, limits: {cpu: 200m, memory: 200Mi}}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: memoria-subdimensionada, namespace: $NS, labels: {stress: memoria}}
spec:
  replicas: 2
  selector: {matchLabels: {app: memoria-subdimensionada}}
  template:
    metadata: {labels: {app: memoria-subdimensionada, stress: memoria}}
    spec:
      containers:
        - name: stress
          image: $STRESS_IMAGE
          command: ["stress", "--vm", "1", "--vm-bytes", "450M", "--vm-hang", "0"]
          resources: {requests: {cpu: 50m, memory: 64Mi}, limits: {cpu: 200m, memory: 1Gi}}
EOF
  ok "cenário memória iniciado:"
  echo "    oom-loop: limit 200Mi e usa 300M → OOMKilled e CrashLoopBackOff (risco crítico esperado no Capacity Agent)"
  echo "    memoria-subdimensionada: request 64Mi e usa ~450M → recomendação 'aumentar requests' esperada"
}

cenario_vizinho() {
  ns
  k apply -f - >/dev/null <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: {name: vizinho-barulhento, namespace: $NS, labels: {stress: vizinho}}
spec:
  replicas: 1
  selector: {matchLabels: {app: vizinho-barulhento}}
  template:
    metadata: {labels: {app: vizinho-barulhento, stress: vizinho}}
    spec:
      containers:
        - name: stress
          image: $STRESS_IMAGE
          command: ["stress", "--cpu", "2"]
          resources: {requests: {cpu: 100m, memory: 32Mi}}
EOF
  ok "cenário vizinho iniciado: request 100m, sem limit, consome ~2 CPUs"
  echo "    Esperado: 'Uso da CPU reservada' acima de 100% e recomendação de aumentar o request de CPU."
}

cenario_desperdicio() {
  ns
  k apply -f - >/dev/null <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: {name: ocioso-superdimensionado, namespace: $NS, labels: {stress: desperdicio}}
spec:
  replicas: 3
  selector: {matchLabels: {app: ocioso-superdimensionado}}
  template:
    metadata: {labels: {app: ocioso-superdimensionado, stress: desperdicio}}
    spec:
      terminationGracePeriodSeconds: 0
      containers:
        - name: pause
          image: registry.k8s.io/pause:3.10
          resources: {requests: {cpu: 700m, memory: 1Gi}}
EOF
  ok "cenário desperdício iniciado: 3 pods ociosos reservando 700m e 1Gi cada"
  echo "    Esperado: recomendação de reduzir requests e capacidade ociosa em Custos (com preços cadastrados)."
  echo "    As recomendações precisam de histórico: deixe rodando pelo menos 1 h (com sampleMinutes 5)."
}

# -----------------------------------------------------------------------------
status() {
  k get nodes
  echo; k -n "$NS" get deploy,hpa 2>/dev/null
  echo; k -n "$NS" get pods -o wide 2>/dev/null | head -40
  echo; k top nodes 2>/dev/null
}

parar() {
  local d
  for d in $(k -n "$NS" get deploy -o name 2>/dev/null); do k -n "$NS" scale "$d" --replicas=0 >/dev/null; done
  k -n "$NS" delete hpa php-apache --ignore-not-found >/dev/null 2>&1
  ok "carga zerada (deployments com 0 réplicas, HPA removido)"
  echo "  Agora observe o scale-down: o autoscaler costuma remover nodes ociosos depois de ~10 a 20 min."
}

# Por que o autoscaler não remove os workers ociosos.
scaledown() {
  echo "== Configuração do cluster-autoscaler (flags que afetam o scale-down)"
  k -n kube-system get deploy cluster-autoscaler -o jsonpath='{range .spec.template.spec.containers[*]}{range .command[*]}{@}{"\n"}{end}{range .args[*]}{@}{"\n"}{end}{end}' 2>/dev/null \
    | grep -E 'scale-down|skip-nodes|utilization|max-node|nodes=|balance|expander' | sed 's/^/    /'
  echo "    (padrões quando não aparecem: scale-down-enabled=true, unneeded-time=10m, delay-after-add=10m,"
  echo "     utilization-threshold=0.5, skip-nodes-with-system-pods=true, skip-nodes-with-local-storage=true)"

  echo; echo "== Status do autoscaler (scaleDown)"
  k -n kube-system get configmap cluster-autoscaler-status -o jsonpath='{.data.status}' 2>/dev/null \
    | grep -iE -A3 'scaleDown' | sed 's/^/    /'

  echo; echo "== O que o autoscaler disse nos logs (últimos 30 min)"
  k -n kube-system logs deploy/cluster-autoscaler --since=30m 2>/dev/null \
    | grep -iE 'unremovable|cannot be removed|not suitable for removal|scale.?down|unneeded|no candidates|pod .* blocks|local storage|kube-system|pdb|not replicated' \
    | sed -E 's/^[IWE][0-9]{4} [0-9:.]+ +[0-9]+ //' | sort | uniq -c | sort -rn | head -25 | sed 's/^/    /'

  echo; echo "== Pods que costumam travar a remoção, por worker"
  local n linha
  for n in $(workers); do
    echo "  $n"
    k get pods -A --field-selector "spec.nodeName=$n,status.phase!=Succeeded,status.phase!=Failed" \
      -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{.metadata.ownerReferences[0].kind}{"\t"}{.spec.volumes[*].emptyDir}{"\t"}{.metadata.annotations.cluster-autoscaler\.kubernetes\.io/safe-to-evict}{"\n"}{end}' 2>/dev/null \
      | while IFS=$'\t' read -r pns pname owner empty safe; do
          [ "$owner" = "DaemonSet" ] && continue
          [ "$owner" = "Node" ] && continue          # static/mirror pod
          [ "$safe" = "true" ] && continue
          motivos=""
          [ -z "$owner" ] && motivos="$motivos sem controller (pod solto);"
          [ "$pns" = "kube-system" ] && ! k -n kube-system get pdb -o jsonpath='{range .items[*]}{.spec.selector.matchLabels}{"\n"}{end}' 2>/dev/null | grep -q . \
            && motivos="$motivos kube-system sem PodDisruptionBudget;"
          [ -n "$empty" ] && motivos="$motivos usa emptyDir (local storage);"
          [ "$safe" = "false" ] && motivos="$motivos anotado safe-to-evict=false;"
          [ -n "$motivos" ] && printf '    ✘ %s/%s →%s\n' "$pns" "$pname" "$motivos"
        done
    linha="$(k describe node "$n" 2>/dev/null | sed -n '/Allocated resources/,/Events/p' | grep -E '^\s+(cpu|memory)' | awk '{print $1" "$2" "$3}' | tr '\n' ' ')"
    echo "    requests no node: ${linha:-?}"
  done
  echo
  echo "Leitura: um worker só sai se os pods dele puderem ir para outro node e a soma dos requests"
  echo "estiver abaixo do utilization-threshold (padrão 50%). DaemonSets não contam."
}

limpar() {
  read -r -p "  Apagar o namespace $NS e tudo do teste? [s/N] " r
  case "$r" in s|S|sim) k delete namespace "$NS" --wait=false && ok "namespace $NS sendo apagado";; *) echo "  Cancelado.";; esac
}

relatorio() {
  [ -f "$CSV" ] || die "sem $CSV: rode 'bash stress.sh monitorar' durante o teste"
  local out="$DIR/relatorio-$(date +%Y%m%d-%H%M).md"
  {
    echo "# Stress test — $(date '+%d/%m/%Y %H:%M')"
    echo
    echo "Cluster: nodes com prefixo \`$CLUSTER_PREFIX\` · namespace \`$NS\`"
    echo
    echo "## Linha do tempo (de $CSV)"
    echo
    awk -F, 'NR==2{w0=$5; t0=$2; h0=$1}
      NR>1{
        if($5>wmax){wmax=$5; hmax=$1}
        if(!pend1 && $6>0){pend1=$2; hpend=$1}
        if(pend1 && !up && $5>w0){up=$2; hup=$1}
        if(up && !back && $5<=w0 && $2>up){back=$2; hback=$1}
        if($6>pmax)pmax=$6; if($8>omax)omax=$8; if($9>hpamax)hpamax=$9
        if($11>cmax)cmax=$11; if($12>mmax)mmax=$12; last=$1
      }
      END{
        printf "| Medida | Resultado |\n|---|---|\n"
        printf "| Início / fim do registro | %s / %s |\n", h0, last
        printf "| Workers no início | %d |\n", w0
        printf "| Máximo de workers | %d (às %s) |\n", wmax, hmax
        printf "| Máximo de pods Pending | %d |\n", pmax
        printf "| Máximo de réplicas do HPA | %s |\n", (hpamax==""?"—":hpamax)
        printf "| CPU / memória média dos nodes (pico) | %s%% / %s%% |\n", cmax, mmax
        printf "| OOMKilled (máximo simultâneo) | %d |\n", omax
        if(pend1 && up) printf "| Tempo do 1º Pending (%s) até o 1º worker novo (%s) | %d min %d s |\n", hpend, hup, (up-pend1)/60, (up-pend1)%60
        else if(pend1) printf "| Scale-up | houve Pending (%s), mas nenhum worker novo |\n", hpend
        if(up && back) printf "| Tempo até voltar ao número inicial de workers | %d min (às %s) |\n", (back-up)/60, hback
        else if(up) printf "| Scale-down | ainda não voltou ao número inicial no fim do registro |\n"
      }' "$CSV"
    echo
    echo "## Eventos do autoscaler e de agendamento"
    echo
    echo '```'
    k get events -A --sort-by=.lastTimestamp 2>/dev/null \
      | grep -E 'TriggeredScaleUp|ScaleDown|NotTriggerScaleUp|FailedScheduling|ScaleUp|OOMKilling|Evicted|NodeNotReady' | tail -40
    echo '```'
    echo
    echo "## Análise (preencha)"
    echo
    echo "| | Pontos bons | Pontos ruins |"
    echo "|---|---|---|"
    echo "| Scale-up de nodes | | |"
    echo "| Scale-down | | |"
    echo "| HPA | | |"
    echo "| Estabilidade (OOM, restarts, NotReady) | | |"
    echo "| Capacity Agent: detectou o quê | | |"
    echo "| Capacity Agent: o que faltou | | |"
  } > "$out"
  ok "relatório: $out"
}

# -----------------------------------------------------------------------------
cmd="${1:-}"; shift || true
case "$cmd" in
  checar)      guarda; checar ;;
  monitorar)   guarda; monitorar ;;
  cpu)         guarda; cenario_cpu "$@" ;;
  nodes)       guarda; cenario_nodes "$@" ;;
  memoria)     guarda; cenario_memoria ;;
  vizinho)     guarda; cenario_vizinho ;;
  desperdicio) guarda; cenario_desperdicio ;;
  status)      guarda; status ;;
  scaledown)   guarda; scaledown ;;
  parar)       guarda; parar ;;
  relatorio)   guarda; relatorio ;;
  limpar)      guarda; limpar ;;
  *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
