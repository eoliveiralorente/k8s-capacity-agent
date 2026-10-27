import os
from pathlib import Path

# Imagem: definida no build (ARG CAPACITY_AGENT_VERSION) a partir da tag de release, ou "1.3.0-lab"/"1.3.0-demo"
# nos ambientes de teste. Instalação com ./serve.sh: lida do arquivo VERSION, gravado por tools/atualizar_producao.sh.
_FILE = Path(__file__).with_name("VERSION")
VERSION = os.getenv("CAPACITY_AGENT_VERSION") or (
    _FILE.read_text(encoding="utf-8").strip() if _FILE.is_file() else ""
) or "dev"
