FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CAPACITY_AGENT_PROVIDER=kubernetes \
    CAPACITY_AGENT_STATE_DIR=/data/state \
    CAPACITY_AGENT_ACCOUNT_DB=/data/accounts.sqlite3

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

ARG TARGETARCH
RUN set -eux; \
    version="$(curl --fail --silent --show-error --location https://dl.k8s.io/release/stable.txt)"; \
    case "${TARGETARCH:-amd64}" in \
      amd64|arm64) arch="${TARGETARCH:-amd64}" ;; \
      *) echo "Unsupported kubectl architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl --fail --silent --show-error --location \
      "https://dl.k8s.io/release/${version}/bin/linux/${arch}/kubectl" \
      --output /usr/local/bin/kubectl; \
    curl --fail --silent --show-error --location \
      "https://dl.k8s.io/release/${version}/bin/linux/${arch}/kubectl.sha256" \
      --output /tmp/kubectl.sha256; \
    echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum --check; \
    chmod 0755 /usr/local/bin/kubectl; \
    rm /tmp/kubectl.sha256

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY agent.py config.py tenant_context.py ./
COPY accounts/ ./accounts/
COPY analyzers/ ./analyzers/
COPY approval/ ./approval/
COPY collectors/ ./collectors/
COPY engine/ ./engine/
COPY executors/ ./executors/
COPY reporters/ ./reporters/
COPY web/ ./web/
COPY licensing/ ./licensing/
COPY assistant/ ./assistant/
COPY alerts/ ./alerts/

RUN chmod -R a+rX /app \
    && mkdir -p /data \
    && chown 10001:10001 /data
USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/', timeout=3)"]

CMD ["python", "agent.py", "serve", "--host", "0.0.0.0", "--port", "8080"]
