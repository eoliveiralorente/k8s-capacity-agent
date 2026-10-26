# Instalação

## Requisitos

- Kubernetes 1.27 ou superior, em qualquer cloud (AWS, Azure, GCP, OCI, SaveInCloud/OpenStack) ou on-premises.
- `helm` 3.8+ e `kubectl` com acesso de administrador **somente durante a instalação**.
- **metrics-server** instalado (`kubectl top nodes` precisa funcionar).
- StorageClass padrão (ou informe `persistence.storageClassName`).
- Token de acesso à imagem (enviado pelo fornecedor, separado do kit).

> Recebeu o kit `.zip`? O jeito mais rápido é o `instalar.sh` do kit: veja o [GUIA_RAPIDO.md](GUIA_RAPIDO.md).

## Instalação com Helm (manual)

```bash
kubectl create namespace capacity-agent
kubectl -n capacity-agent create secret docker-registry capacity-agent-pull \
  --docker-server=ghcr.io --docker-username=capacity-agent-bot --docker-password='<token>'

helm upgrade --install capacity-agent ./capacity-agent-<versão>.tgz \
  --namespace capacity-agent \
  --set image.tag=<versão> \
  --set "imagePullSecrets[0].name=capacity-agent-pull" \
  --set clusterName="Produção"
```

Acompanhe até o pod ficar `Running 1/1`:

```bash
kubectl -n capacity-agent get pods -w
```

## Primeiro acesso

```bash
kubectl -n capacity-agent port-forward svc/capacity-agent 8080:80
```

Abra `http://localhost:8080` → **Criar conta**. Essa conta é o administrador; depois disso o
cadastro fecha e novos usuários entram por **convite** (aba Usuários).

Depois:
1. **Usuários → Licença**: instale o arquivo `.license.json` recebido.
2. **Usuários → Custos da infraestrutura**: cadastre o preço de cada tipo de máquina (R$/hora ou R$/mês)
   e os custos fixos. O R$/vCPU e R$/GB servem de referência para nodes sem preço.
3. **Usuários → Alertas**: configure Slack, Teams, webhook ou e-mail.
4. **Assistente IA** (opcional): configure o provedor com a **sua** chave de API (Claude, OpenAI, Azure,
   Gemini, Tess, OpenRouter ou qualquer API compatível com OpenAI) ou um Ollama interno.
5. **Visão Geral → Nova Avaliação**.

## Opções frequentes

| Opção | Exemplo | Efeito |
|---|---|---|
| Ingress com TLS | `--set ingress.enabled=true --set ingress.host=capacity.empresa.com.br --set ingress.tlsSecretName=capacity-tls` | Acesso por HTTPS sem port-forward |
| URL pública | `--set publicUrl=https://capacity.empresa.com.br` | Links nos alertas |
| Aplicar mudanças | `--set rbac.allowRightsizing=true` | Permite executar requests/réplicas/HPA **após aprovação** |
| E-mail | `--set smtp.host=smtp.empresa.com --set smtp.from=capacity@empresa.com --set smtp.passwordSecret=capacity-smtp` | Alertas por e-mail |
| Intervalos | `--set sampleMinutes=15 --set evaluateMinutes=60` | Coleta e avaliação automáticas |

Sem `rbac.allowRightsizing`, a instalação é **100% somente leitura**.

## Instalação com ArgoCD

Veja o exemplo de `Application` em `charts/capacity-agent/README.md`. Com ArgoCD, crie antes o
Secret da chave de criptografia e use `encryption.existingSecret` (o ArgoCD não executa o `lookup` do Helm).
