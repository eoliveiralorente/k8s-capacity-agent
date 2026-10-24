import os

# Definida no build da imagem (ARG CAPACITY_AGENT_VERSION) a partir da tag de release.
VERSION = os.getenv("CAPACITY_AGENT_VERSION", "dev")
