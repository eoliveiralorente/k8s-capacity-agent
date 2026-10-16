#!/usr/bin/env bash
set -euo pipefail

IMAGE_REPOSITORY="${CAPACITY_AGENT_IMAGE_REPOSITORY:-ghcr.io/eoliveiralorente/k8s-capacity-agent}"
PROJECT="${CAPACITY_AGENT_COMPOSE_PROJECT:-cliente-capacity-agent}"
COMPOSE_FILE="${CAPACITY_AGENT_COMPOSE_FILE:-compose.customer.yaml}"
ENV_FILE="${CAPACITY_AGENT_ENV_FILE:-.env}"
VERSION="${1:-}"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Uso: bash update-customer.sh <versão>, por exemplo: bash update-customer.sh 1.2.3" >&2
  exit 2
fi

if [[ ! -f "$COMPOSE_FILE" || ! -f "$ENV_FILE" ]]; then
  echo "Execute este script na pasta da instalação, com $COMPOSE_FILE e $ENV_FILE presentes." >&2
  exit 2
fi

IMAGE="${IMAGE_REPOSITORY}:${VERSION}"
ENV_BACKUP="$(mktemp)"
cp "$ENV_FILE" "$ENV_BACKUP"
trap 'rm -f "$ENV_BACKUP"' EXIT

restore_previous_image() {
  echo "A nova versão falhou. Logs antes do rollback:" >&2
  sudo docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f "$COMPOSE_FILE" logs --tail=100 >&2 || true
  cp "$ENV_BACKUP" "$ENV_FILE"
  echo "Atualização não saudável; restaurando a versão anterior." >&2
  sudo docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f "$COMPOSE_FILE" up -d >&2 || true
}

update_env_image() {
  local temp_env
  temp_env="$(mktemp "${ENV_FILE}.XXXXXX")"
  if grep -q '^CAPACITY_AGENT_IMAGE=' "$ENV_FILE"; then
    sed "s|^CAPACITY_AGENT_IMAGE=.*|CAPACITY_AGENT_IMAGE=${IMAGE}|" "$ENV_FILE" > "$temp_env"
  else
    cat "$ENV_FILE" > "$temp_env"
    printf '\nCAPACITY_AGENT_IMAGE=%s\n' "$IMAGE" >> "$temp_env"
  fi
  chmod --reference="$ENV_FILE" "$temp_env"
  mv "$temp_env" "$ENV_FILE"
}

update_env_image
if ! sudo docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f "$COMPOSE_FILE" pull; then
  cp "$ENV_BACKUP" "$ENV_FILE"
  echo "Falha ao baixar $IMAGE. Confirme a versão e o acesso ao GHCR." >&2
  exit 1
fi

if ! sudo docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f "$COMPOSE_FILE" up -d; then
  restore_previous_image
  exit 1
fi

if ! container_id="$(sudo docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f "$COMPOSE_FILE" ps -q capacity-agent)"; then
  restore_previous_image
  exit 1
fi
if [[ -z "$container_id" ]]; then
  restore_previous_image
  exit 1
fi

for attempt in {1..30}; do
  if ! health="$(sudo docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"; then
    restore_previous_image
    exit 1
  fi
  if [[ "$health" == "healthy" ]]; then
    echo "Atualização concluída: $IMAGE"
    exit 0
  fi
  if [[ "$health" == "unhealthy" || "$health" == "exited" || "$health" == "dead" ]]; then
    restore_previous_image
    exit 1
  fi
  sleep 3
done

restore_previous_image
echo "Healthcheck não ficou saudável dentro de 90 segundos." >&2
exit 1
