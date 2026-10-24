# capacity-collector

Coletor somente leitura do Capacity Agent. Roda dentro do cluster do cliente e
envia, a cada 15 minutos, um snapshot (nodes, pods, events e métricas do
metrics-server) ao painel por HTTPS. Não abre portas, não altera o cluster e não
exige kubeconfig.

## Instalação

1. No painel: **Cluster → Ou conectar via agente → Gerar instalação do agente**.
2. Rode o comando exibido (exemplo):

```bash
helm upgrade --install capacity-collector ./charts/capacity-collector \
  --namespace capacity-agent --create-namespace \
  --set panelUrl=https://painel.exemplo.com.br \
  --set image.repository=ghcr.io/OWNER/k8s-capacity-agent \
  --set ingestToken=cag_...
```

Em produção, prefira criar o Secret antes e usar `--set existingSecret=nome`:

```bash
kubectl -n capacity-agent create secret generic capacity-collector-token --from-literal=token=cag_...
```

## Requisitos
- metrics-server instalado (para `kubectl top`).
- Saída HTTPS do cluster para o painel.

## Permissões (ClusterRole somente leitura)
`get/list/watch` em nodes, pods, events, namespaces, deployments, statefulsets,
daemonsets, replicasets; `get/list` em metrics.k8s.io.

## Remoção
`helm uninstall capacity-collector -n capacity-agent`
