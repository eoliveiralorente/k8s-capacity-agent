"""Licenciamento offline (Ed25519).

Formato do arquivo de licença (JSON):
  {"payload": "<base64 do JSON>", "signature": "<base64 da assinatura Ed25519>"}

O payload contém: license_id, customer, plan, max_clusters, max_users,
features, issued_at, expires_at. A assinatura é verificada com a chave pública
embutida em licensing/public_key.pem — não há chamada externa.
"""
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

GRACE_DAYS = 14
PUBLIC_KEY_PATH = Path(__file__).with_name("public_key.pem")

COMMUNITY = {
    "plan": "community",
    "customer": None,
    "max_clusters": 1,
    "max_users": 2,
    "features": [],
}
ALL_FEATURES = ("execution", "agent_mode", "alerts", "ai_assistant")
FEATURE_LABELS = {
    "execution": "Aprovação e execução de recomendações",
    "agent_mode": "Clusters conectados via agente",
    "alerts": "Alertas (Slack, Teams, e-mail)",
    "ai_assistant": "Assistente de IA",
}


class LicenseError(ValueError):
    pass


def _license_file():
    env = os.getenv("CAPACITY_AGENT_LICENSE_FILE")
    if env:
        return Path(env)
    from accounts import store
    return Path(store.DB_PATH).parent / "license.json"


def _public_key():
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    if not PUBLIC_KEY_PATH.is_file():
        return None
    return load_pem_public_key(PUBLIC_KEY_PATH.read_bytes())


def verify_license_text(text, public_key=None):
    """Valida assinatura e estrutura. Retorna o payload (dict) ou levanta LicenseError."""
    from cryptography.exceptions import InvalidSignature

    public_key = public_key or _public_key()
    if public_key is None:
        raise LicenseError("Chave pública de licença ausente nesta versão")
    try:
        envelope = json.loads(text)
        payload_bytes = base64.b64decode(envelope["payload"], validate=True)
        signature = base64.b64decode(envelope["signature"], validate=True)
    except (ValueError, KeyError, TypeError) as exc:
        raise LicenseError("Arquivo de licença mal formado") from exc
    try:
        public_key.verify(signature, payload_bytes)
    except InvalidSignature as exc:
        raise LicenseError("Assinatura da licença inválida") from exc
    payload = json.loads(payload_bytes)
    for field in ("license_id", "customer", "plan", "expires_at", "max_clusters", "max_users"):
        if field not in payload:
            raise LicenseError(f"Licença sem o campo {field}")
    datetime.fromisoformat(payload["expires_at"])
    return payload


def save_license_text(text):
    payload = verify_license_text(text)
    path = _license_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return payload


def license_status(now=None):
    """Situação efetiva da licença: limites e recursos que valem agora."""
    now = now or datetime.now(timezone.utc)
    path = _license_file()
    base = {**COMMUNITY, "state": "community", "license_id": None, "expires_at": None,
            "days_left": None, "message": "Sem licença: edição Community (1 cluster, 2 usuários)."}
    if not path.is_file():
        return base
    try:
        payload = verify_license_text(path.read_text(encoding="utf-8"))
    except (LicenseError, OSError, ValueError) as exc:
        return {**base, "state": "invalid", "message": f"Licença inválida ({exc}). Usando Community."}

    expires = datetime.fromisoformat(payload["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    days_left = (expires - now).days
    effective = {
        "plan": payload["plan"],
        "customer": payload["customer"],
        "max_clusters": int(payload["max_clusters"]),
        "max_users": int(payload["max_users"]),
        "features": [f for f in payload.get("features", []) if f in ALL_FEATURES],
        "license_id": payload["license_id"],
        "expires_at": payload["expires_at"],
        "days_left": days_left,
    }
    if now <= expires:
        message = f"Licença {payload['plan']} para {payload['customer']}, válida até {expires.date().isoformat()}."
        if days_left <= 30:
            message += f" Renove em até {days_left} dia(s)."
        return {**effective, "state": "valid", "message": message}
    if now <= expires + timedelta(days=GRACE_DAYS):
        grace_left = (expires + timedelta(days=GRACE_DAYS) - now).days
        return {**effective, "state": "grace",
                "message": f"Licença vencida em {expires.date().isoformat()}. "
                           f"Período de carência: {grace_left} dia(s) para renovar."}
    return {**base, "state": "expired", "license_id": payload["license_id"],
            "customer": payload["customer"], "expires_at": payload["expires_at"],
            "message": f"Licença vencida em {expires.date().isoformat()}. Usando Community; os dados continuam disponíveis."}


def has_feature(feature):
    return feature in license_status()["features"]


def require_feature(feature):
    if not has_feature(feature):
        raise LicenseError(
            f"Recurso '{FEATURE_LABELS.get(feature, feature)}' não incluído na licença atual"
        )


def check_limit(kind, current_count):
    status = license_status()
    limit = status["max_clusters"] if kind == "clusters" else status["max_users"]
    if current_count >= limit:
        label = "clusters" if kind == "clusters" else "usuários"
        raise LicenseError(f"Limite de {limit} {label} da licença {status['plan']} atingido")
