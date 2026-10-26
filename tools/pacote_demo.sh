#!/usr/bin/env bash
# Gera o pacote de demonstração para enviar a um interessado (uso do FORNECEDOR).
#
#   tools/pacote_demo.sh <versão> ["contato exibido no painel"]
#   ex.: tools/pacote_demo.sh 1.1.0 "Eduardo · WhatsApp (11) 94722-9481"
#
# Usa a imagem ghcr.io/eoliveiralorente/k8s-capacity-agent:<versão> (faça docker login ghcr.io antes)
# ou, se ela não estiver acessível, a imagem local capacity-agent:<versão>.
# Resultado: entregas/capacity-agent-demo-<versão>.zip (a imagem vai dentro; o interessado não precisa de token).
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:?Informe a versão, ex.: 1.1.0}"
CONTACT="${2:-}"
REMOTE="ghcr.io/eoliveiralorente/k8s-capacity-agent:${VERSION}"
DEMO_IMAGE="capacity-agent-demo:${VERSION}"
OUT="entregas/capacity-agent-demo-${VERSION}"

if docker pull --platform linux/amd64 "$REMOTE" >/dev/null 2>&1; then
  docker tag "$REMOTE" "$DEMO_IMAGE"
elif docker image inspect "capacity-agent:${VERSION}" >/dev/null 2>&1; then
  docker tag "capacity-agent:${VERSION}" "$DEMO_IMAGE"
else
  echo "Imagem não encontrada: faça 'docker login ghcr.io' ou build local como capacity-agent:${VERSION}."; exit 1
fi

rm -rf "$OUT" && mkdir -p "$OUT"
echo "Exportando a imagem (alguns minutos)..."
docker save "$DEMO_IMAGE" | gzip -6 > "$OUT/capacity-agent-demo-image.tar.gz"
cp demo/compose.yaml demo/iniciar-demo.sh demo/parar-demo.sh demo/iniciar-demo.ps1 demo/parar-demo.ps1 demo/LEIA-ME.md "$OUT/"
chmod +x "$OUT"/*.sh
cat > "$OUT/demo.env" <<ENV
DEMO_VERSION="${VERSION}"
DEMO_PORT="8090"
DEMO_CONTACT="${CONTACT}"
ENV

(cd entregas && rm -f "capacity-agent-demo-${VERSION}.zip" && python3 -m zipfile -c "capacity-agent-demo-${VERSION}.zip" "capacity-agent-demo-${VERSION}")
ls -lh "entregas/capacity-agent-demo-${VERSION}.zip"
echo "Pronto. Envie o .zip (ou um link do Google Drive/WeTransfer para ele)."
