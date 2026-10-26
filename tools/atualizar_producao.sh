#!/usr/bin/env bash
# Atualiza a PRODUÇÃO (instalação com ./serve.sh) para o código testado da pasta v2.
#
#   tools/atualizar_producao.sh ~/repo_oficial/<pasta-da-producao>
#
# 1. confere que a produção está parada;  2. faz backup COMPLETO (código + dados + chave);
# 3. copia o código novo (dados, .venv, .env e .git ficam intactos);  4. atualiza dependências;
# 5. confere que o painel importa sem erro;  6. mostra como subir e como voltar (rollback).
set -euo pipefail

PROD="${1:?Informe a pasta da produção, ex.: ~/repo_oficial/capacity-agent}"
PROD="$(cd "$PROD" && pwd)"
SRC="$HOME/repo_oficial/k8s-capacity-agent-v2"
STAMP="$(date +%Y%m%d-%H%M%S)"
BKP="$HOME/backups/capacity-agent-producao-$STAMP"

[ -f "$PROD/serve.sh" ] && [ -f "$PROD/agent.py" ] || { echo "Isto não parece a pasta do Capacity Agent: $PROD"; exit 1; }
[ "$PROD" != "$SRC" ] || { echo "A produção não pode ser a própria pasta v2."; exit 1; }

echo "Produção:  $PROD"
echo "Código de: $SRC ($(sed -n 's/^appVersion: *//p' "$SRC/charts/capacity-agent/Chart.yaml"))"
echo "Dados encontrados:"; ls -d "$PROD"/.capacity-agent* 2>/dev/null | sed 's/^/  /'
ls "$PROD"/.capacity-agent/accounts.sqlite3 >/dev/null 2>&1 && echo "  (contas e chave de criptografia em .capacity-agent/)"

for pid in $(pgrep -f "agent.py serve" || true); do
  if [ "$(readlink "/proc/$pid/cwd" 2>/dev/null)" = "$PROD" ]; then
    echo "A produção está rodando (PID $pid). Pare o ./serve.sh (Ctrl+C no terminal dele) e rode de novo."; exit 1
  fi
done

read -r -p "Fazer backup e atualizar esta pasta? [s/N] " ok
case "$ok" in s|S|sim|SIM) ;; *) echo "Cancelado."; exit 1;; esac

echo; echo "== 1/4 Backup completo em $BKP"
mkdir -p "$BKP"
rsync -a --exclude '.venv*' --exclude __pycache__ "$PROD/" "$BKP/codigo-e-dados/"
cat > "$BKP/VOLTAR.sh" <<ROLL
#!/usr/bin/env bash
# Volta a produção exatamente como estava em $STAMP (código e dados).
set -euo pipefail
read -r -p "Restaurar $PROD a partir de $BKP? [s/N] " ok
case "\$ok" in s|S|sim|SIM) ;; *) echo "Cancelado."; exit 1;; esac
rsync -a --delete --exclude '.venv*' "$BKP/codigo-e-dados/" "$PROD/"
echo "Produção restaurada. Suba de novo com: cd $PROD && ./serve.sh"
ROLL
chmod +x "$BKP/VOLTAR.sh"
du -sh "$BKP" | sed 's/^/  tamanho: /'

echo; echo "== 2/4 Copiando o código novo (dados, .venv, .env e .git não são tocados)"
rsync -a --exclude .git --exclude .github --exclude '.venv*' --exclude __pycache__ \
  --exclude '.capacity-agent*' --exclude '.env*' --exclude entregas --exclude divulgacao --exclude '*.tar' \
  "$SRC/" "$PROD/"

echo; echo "== 3/4 Dependências"
PY="$PROD/.venv/bin/python3"
if [ -x "$PY" ]; then "$PY" -m pip install -q -r "$PROD/requirements.txt" && echo "  ok"
else echo "  .venv não encontrado: o serve.sh vai procurar outro Python (como antes)"; PY="$(command -v python3)"; fi

echo; echo "== 4/4 Conferência"
( cd "$PROD" && "$PY" -c "import web.app; print('  painel carrega sem erro')" )

cat <<FIM

Pronto. A produção foi atualizada e os dados foram preservados.
  Subir:   cd $PROD && ./serve.sh --port 8082     (8080 e 8081 já estão em uso pelo kind e pelo demo)
  Abrir:   http://127.0.0.1:8082   → Ctrl+F5, entre com a sua conta de sempre
  Voltar:  $BKP/VOLTAR.sh        (restaura código e dados de antes)
FIM
