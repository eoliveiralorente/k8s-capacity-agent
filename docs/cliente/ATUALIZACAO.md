# Atualização, backup e restauração

## Antes de atualizar

1. Leia as notas da versão (changelog) enviadas pelo fornecedor.
2. Faça **backup** (abaixo).

## Atualizar

```bash
helm upgrade capacity-agent ./charts/capacity-agent -n capacity-agent \
  --reuse-values --set image.tag=<nova-versão>
kubectl -n capacity-agent rollout status deploy/capacity-agent
```

Com ArgoCD: altere `targetRevision` e a tag da imagem; o sync aplica.

Confira em **Suporte → Saúde da instalação** que a versão mudou e tudo está `OK`.

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
