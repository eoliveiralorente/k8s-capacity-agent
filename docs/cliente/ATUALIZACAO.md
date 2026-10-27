# Atualização, backup e restauração

A atualização leva cerca de 5 minutos e mantém tudo: contas, licença, histórico, preços cadastrados e
decisões de recomendações. O painel fica fora do ar por menos de 1 minuto, enquanto o pod novo sobe.

## Antes de atualizar

1. Leia as novidades da versão (`NOVIDADES.md`, que vem no kit).
2. Faça **backup** (abaixo). É rápido e permite voltar atrás com segurança.
3. Confira a versão instalada hoje:

```bash
kubectl -n capacity-agent get deploy capacity-agent -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
```

O número depois de `:` é a versão, por exemplo `...k8s-capacity-agent:1.1.0`.

## Atualizar com o kit novo (recomendado)

Descompacte o kit novo enviado pelo fornecedor e rode o mesmo instalador, com o `kubectl` apontando
para o cluster certo:

```bash
cd capacity-agent-<sua-empresa>
bash instalar.sh
```

O instalador percebe que já existe uma instalação e pergunta *"Atualizar para a versão X?"*. Digite `s`.

- **O token não é pedido de novo**: ele já está guardado no cluster.
- **A licença não precisa ser reinstalada**: ela continua valendo até a data dela.
- Se você instalou com outro namespace ou nome, rode como da primeira vez, por exemplo
  `NAMESPACE=meu-namespace bash instalar.sh`.

## Atualizar direto com Helm ou ArgoCD

```bash
helm upgrade capacity-agent ./capacity-agent-<versão>.tgz -n capacity-agent \
  --reuse-values --set image.tag=<nova-versão>
kubectl -n capacity-agent rollout status deploy/capacity-agent
```

Com ArgoCD: altere `targetRevision` e a tag da imagem; o sync aplica.

## Conferir

```bash
kubectl -n capacity-agent port-forward svc/capacity-agent 8080:80
```

Abra `http://localhost:8080` e use **Ctrl+F5** para carregar a tela nova. Em **Suporte → Saúde da
instalação**, confira que a versão mudou e que tudo está `OK`.

## Se algo der errado

| O que aparece | O que fazer |
|---|---|
| A imagem não foi baixada (`ImagePullBackOff`) | O token pode ter vencido. Peça um novo ao fornecedor, rode `kubectl -n capacity-agent delete secret capacity-agent-pull` e depois `bash instalar.sh` de novo |
| O pod não sobe e você quer voltar | Use o rollback abaixo |
| Qualquer outro problema | Rode `./diagnostico.sh` e envie o arquivo gerado ao suporte |

## Voltar à versão anterior

```bash
helm history capacity-agent -n capacity-agent
helm rollback capacity-agent <revisão> -n capacity-agent
```

## Backup

Salve **juntos** o banco (PVC) e a chave de criptografia (Secret). Um sem o outro não serve.

```bash
# chave
kubectl -n capacity-agent get secret capacity-agent-encryption -o yaml > capacity-chave-backup.yaml
# banco (cópia a quente do SQLite)
kubectl -n capacity-agent exec deploy/capacity-agent -- \
  python -c "import sqlite3;s=sqlite3.connect('/data/accounts.sqlite3');d=sqlite3.connect('/tmp/bkp.sqlite3');s.backup(d);d.close()"
kubectl -n capacity-agent cp $(kubectl -n capacity-agent get pod -l app.kubernetes.io/name=capacity-agent -o name | head -1 | cut -d/ -f2):/tmp/bkp.sqlite3 ./capacity-banco-backup.sqlite3
```

Guarde os dois arquivos em local seguro (contêm dados cifrados e a chave que os abre).

## Restauração

1. Instale a mesma versão com `encryption.existingSecret` apontando para o Secret restaurado
   (`kubectl apply -f capacity-chave-backup.yaml`).
2. Copie o banco para `/data/accounts.sqlite3` no pod e reinicie:
   `kubectl -n capacity-agent rollout restart deploy/capacity-agent`.
