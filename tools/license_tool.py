#!/usr/bin/env python3
"""Ferramenta do FORNECEDOR para emitir licenças do Capacity Agent.

NÃO vai na imagem entregue ao cliente. A chave privada fica só com você,
fora do repositório (padrão: ~/.capacity-license/private.pem).

Uso:
  python3 tools/license_tool.py keygen
  python3 tools/license_tool.py issue --customer "Cliente X" --plan pro \
      --clusters 3 --users 10 --days 365 --features execution,agent_mode,alerts -o cliente-x.license.json
  python3 tools/license_tool.py verify cliente-x.license.json
"""
import argparse
import base64
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

DEFAULT_DIR = Path(os.getenv("CAPACITY_LICENSE_DIR", Path.home() / ".capacity-license"))
REPO_PUBLIC_KEY = Path(__file__).resolve().parent.parent / "licensing" / "public_key.pem"
PLANS = {
    "pro": ["execution", "alerts"],
    "enterprise": ["execution", "agent_mode", "alerts", "ai_assistant"],
}


def cmd_keygen(args):
    DEFAULT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path = DEFAULT_DIR / "private.pem"
    if private_path.exists() and not args.force:
        sys.exit(f"Já existe {private_path}. Use --force só se tiver certeza (licenças antigas deixam de valer).")
    key = Ed25519PrivateKey.generate()
    private_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private_path.chmod(0o600)
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    REPO_PUBLIC_KEY.write_bytes(public_pem)
    print(f"Chave privada: {private_path}  (guarde backup em local seguro; NUNCA commite)")
    print(f"Chave pública: {REPO_PUBLIC_KEY}  (vai na imagem; commite este arquivo)")


def _load_private():
    path = DEFAULT_DIR / "private.pem"
    if not path.is_file():
        sys.exit(f"Chave privada não encontrada em {path}. Rode: keygen")
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def issue_license(customer, plan, clusters, users, days=365, features=None):
    """Retorna (envelope assinado, payload). Usado pelo `issue` e pelo kit de entrega."""
    key = _load_private()
    features = list(features) if features else PLANS.get(plan, [])
    now = datetime.now(timezone.utc)
    payload = {
        "license_id": uuid.uuid4().hex[:12],
        "customer": customer,
        "plan": plan,
        "max_clusters": clusters,
        "max_users": users,
        "features": features,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(days=days)).replace(microsecond=0).isoformat(),
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    envelope = {
        "payload": base64.b64encode(payload_bytes).decode(),
        "signature": base64.b64encode(key.sign(payload_bytes)).decode(),
    }
    return envelope, payload


def cmd_issue(args):
    features = [f.strip() for f in args.features.split(",") if f.strip()] if args.features else None
    envelope, payload = issue_license(args.customer, args.plan, args.clusters, args.users, args.days, features)
    Path(args.output).write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nLicença gravada em {args.output}")


def cmd_verify(args):
    from licensing.core import verify_license_text

    payload = verify_license_text(Path(args.file).read_text(encoding="utf-8"))
    print("Assinatura válida.")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Emissão de licenças do Capacity Agent (uso do fornecedor)")
    sub = parser.add_subparsers(dest="command", required=True)
    k = sub.add_parser("keygen", help="Gera o par de chaves (uma única vez)")
    k.add_argument("--force", action="store_true")
    i = sub.add_parser("issue", help="Emite uma licença assinada")
    i.add_argument("--customer", required=True)
    i.add_argument("--plan", choices=["pro", "enterprise"], required=True)
    i.add_argument("--clusters", type=int, required=True)
    i.add_argument("--users", type=int, required=True)
    i.add_argument("--days", type=int, default=365)
    i.add_argument("--features", help="Lista separada por vírgula (padrão: do plano)")
    i.add_argument("-o", "--output", required=True)
    v = sub.add_parser("verify", help="Confere uma licença com a chave pública do repositório")
    v.add_argument("file")
    args = parser.parse_args()
    {"keygen": cmd_keygen, "issue": cmd_issue, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    main()
