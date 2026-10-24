# capacity-agent (self-hosted)

Instala o painel do Capacity Agent **dentro do cluster do cliente**, para uma única
empresa. O painel lê o próprio cluster pela ServiceAccount (sem kubeconfig) e guarda
os dados num PVC. Nada sai do cluster.

## Instalação

```bash
helm upgrade --install capacity-agent ./charts/capacity-agent \
  --namespace capacity-agent --create-namespace \
  --set image.repository=ghcr.io/eoliveiralorente/k8s-capacity-agent \
  --set clusterName="Produção"
kubectl -n capacity-agent port-forward svc/capacity-agent 8080:80
```

Abra `http://localhost:8080` → **Criar conta** (vira o administrador; depois o cadastro fecha).

### Com Ingress e TLS

```bash
--set ingress.enabled=true --set ingress.className=nginx \
--set ingress.host=capacity.cliente.com.br --set ingress.tlsSecretName=capacity-tls
```

### Permitir aplicar rightsizing (após aprovação no painel)

`--set rbac.allowRightsizing=true` — adiciona somente `patch` em deployments,
statefulsets e daemonsets. Sem isso, a instalação é 100% somente leitura.

## ArgoCD

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: capacity-agent
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/eoliveiralorente/k8s-capacity-agent
    targetRevision: v0.1.0
    path: charts/capacity-agent
    helm:
      values: |
        image:
          repository: ghcr.io/eoliveiralorente/k8s-capacity-agent
        clusterName: Produção
  destination:
    server: https://kubernetes.default.svc
    namespace: capacity-agent
  syncPolicy:
    automated: { prune: true, selfHeal: true }
    syncOptions: [CreateNamespace=true]
```

> Com ArgoCD, o `lookup` do Helm não enxerga o cluster: crie o Secret da chave antes
> (`kubectl -n capacity-agent create secret generic capacity-agent-encryption --from-literal=key=$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')`)
> e use `encryption.existingSecret: capacity-agent-encryption`.

## Atualização

`helm upgrade capacity-agent ./charts/capacity-agent -n capacity-agent --reuse-values --set image.tag=X.Y.Z`
(ou altere `targetRevision` no ArgoCD). Banco e chave são preservados.

## Backup e restauração

Salve **juntos** o PVC `capacity-agent-data` e o Secret `capacity-agent-encryption`.
Sem a chave, os dados cifrados não podem ser lidos.

## Requisitos

- metrics-server; StorageClass padrão (ou `persistence.storageClassName`).
