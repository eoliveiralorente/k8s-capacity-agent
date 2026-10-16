import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("CAPACITY_AGENT_ACCOUNT_DB", ".capacity-agent/accounts.sqlite3"))
SESSION_TTL_DAYS = 14
MAX_KUBECONFIG_BYTES = 2_000_000


class DuplicateAccountError(ValueError):
    pass


class DuplicateClusterError(ValueError):
    pass


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 20000")
    return connection


def initialize_database():
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS clusters (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                context_name TEXT NOT NULL,
                node_count INTEGER NOT NULL,
                kubeconfig_ciphertext BLOB NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(tenant_id, name)
            );
            CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS clusters_tenant_idx ON clusters(tenant_id);
            """
        )
    try:
        DB_PATH.chmod(0o600)
        DB_PATH.parent.chmod(0o700)
    except OSError:
        pass


def _hash_password(password):
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "$scrypt$16384$8$1${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )


def _verify_password(password, encoded):
    try:
        _, algorithm, n, r, p, salt_text, digest_text = encoded.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(digest_text)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def register_account(company_name, full_name, email, password):
    initialize_database()
    now = datetime.now(timezone.utc).isoformat()
    tenant_id = uuid.uuid4().hex
    user_id = uuid.uuid4().hex
    email = email.strip().lower()
    try:
        with _connect() as connection:
            connection.execute(
                "INSERT INTO tenants(id, company_name, created_at) VALUES (?, ?, ?)",
                (tenant_id, company_name.strip(), now),
            )
            connection.execute(
                "INSERT INTO users(id, tenant_id, full_name, email, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, tenant_id, full_name.strip(), email, _hash_password(password), now),
            )
    except sqlite3.IntegrityError as exc:
        raise DuplicateAccountError("Já existe uma conta com esse e-mail") from exc
    return {"id": user_id, "tenant_id": tenant_id, "full_name": full_name.strip(), "email": email,
            "company_name": company_name.strip()}


def authenticate(email, password):
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT users.id, users.tenant_id, users.full_name, users.email, users.password_hash, "
            "tenants.company_name FROM users JOIN tenants ON tenants.id = users.tenant_id "
            "WHERE users.email = ?",
            (email.strip().lower(),),
        ).fetchone()
    if row is None or not _verify_password(password, row["password_hash"]):
        return None
    return {key: row[key] for key in ("id", "tenant_id", "full_name", "email", "company_name")}


def create_session(user_id):
    initialize_database()
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, user_id, expires_at),
        )
    return token, expires_at


def get_session(token):
    if not token:
        return None
    initialize_database()
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    with _connect() as connection:
        row = connection.execute(
            "SELECT users.id, users.tenant_id, users.full_name, users.email, tenants.company_name, "
            "sessions.expires_at FROM sessions JOIN users ON users.id = sessions.user_id "
            "JOIN tenants ON tenants.id = users.tenant_id WHERE sessions.token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row and row["expires_at"] <= datetime.now(timezone.utc).isoformat():
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            return None
    return dict(row) if row else None


def delete_session(token):
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    with _connect() as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def _fernet():
    key = os.getenv("CAPACITY_AGENT_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("CAPACITY_AGENT_ENCRYPTION_KEY não configurada no servidor")
    from cryptography.fernet import Fernet, InvalidToken

    try:
        return Fernet(key.encode("ascii")), InvalidToken
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("CAPACITY_AGENT_ENCRYPTION_KEY inválida") from exc


def _run_kubectl_for_kubeconfig(kubeconfig, args):
    if len(kubeconfig) > MAX_KUBECONFIG_BYTES:
        raise ValueError("Arquivo kubeconfig excede o limite de 2 MB")
    if not os.getenv("CAPACITY_AGENT_ENCRYPTION_KEY"):
        raise RuntimeError("CAPACITY_AGENT_ENCRYPTION_KEY não configurada no servidor")
    with tempfile.TemporaryDirectory(prefix="capacity-kubeconfig-") as temp_dir:
        path = Path(temp_dir) / "config"
        path.write_bytes(kubeconfig)
        path.chmod(0o600)
        env = os.environ.copy()
        env["KUBECONFIG"] = str(path)
        try:
            return subprocess.run(
                ["kubectl", *args], capture_output=True, text=True, env=env, timeout=20,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Tempo esgotado ao validar o cluster") from exc


def inspect_kubeconfig(kubeconfig):
    view = _run_kubectl_for_kubeconfig(
        kubeconfig,
        ["config", "view", "--raw", "-o", "json"],
    )
    if view.returncode != 0:
        raise ValueError("Kubeconfig inválido ou incompatível com kubectl")
    try:
        config_data = json.loads(view.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Não foi possível interpretar o kubeconfig") from exc
    users = [entry.get("user", {}) for entry in config_data.get("users", [])]
    if any("exec" in user for user in users):
        raise ValueError("Autenticação por plugin exec não é permitida para arquivos enviados")
    if any(
        "client-certificate" in user or "client-key" in user or "auth-provider" in user
        for user in users
    ):
        raise ValueError("Use token ou certificado embutido no kubeconfig; referências externas não são aceitas")
    clusters = [entry.get("cluster", {}) for entry in config_data.get("clusters", [])]
    if any("certificate-authority" in cluster for cluster in clusters):
        raise ValueError("A CA deve estar embutida no kubeconfig como certificate-authority-data")
    context = config_data.get("current-context")
    if not context:
        raise ValueError("Selecione um contexto padrão no kubeconfig antes de enviar")

    nodes = _run_kubectl_for_kubeconfig(
        kubeconfig,
        ["get", "nodes", "-o", "json"],
    )
    if nodes.returncode != 0:
        raise ValueError("Kubeconfig válido, mas o acesso aos nodes falhou")
    try:
        node_count = len(json.loads(nodes.stdout).get("items", []))
    except (json.JSONDecodeError, AttributeError) as exc:
        raise ValueError("Resposta inesperada ao consultar os nodes") from exc
    return {"context_name": context, "node_count": node_count}


def create_cluster(tenant_id, name, kubeconfig, context_name, node_count):
    if len(kubeconfig) > MAX_KUBECONFIG_BYTES:
        raise ValueError("Arquivo kubeconfig excede o limite de 2 MB")
    fernet, _ = _fernet()
    encrypted = fernet.encrypt(kubeconfig)
    cluster_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as connection:
            connection.execute(
                "INSERT INTO clusters(id, tenant_id, name, context_name, node_count, "
                "kubeconfig_ciphertext, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cluster_id, tenant_id, name.strip(), context_name, node_count, encrypted, now),
            )
    except sqlite3.IntegrityError as exc:
        raise DuplicateClusterError("Já existe um cluster com esse nome nesta empresa") from exc
    return {"id": cluster_id, "name": name.strip(), "context_name": context_name,
            "node_count": node_count, "created_at": now}


def list_clusters(tenant_id):
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, name, context_name, node_count, created_at FROM clusters "
            "WHERE tenant_id = ? ORDER BY created_at",
            (tenant_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_cluster(tenant_id, cluster_id):
    if not cluster_id:
        return None
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, tenant_id, name, context_name, node_count, kubeconfig_ciphertext, created_at "
            "FROM clusters WHERE id = ? AND tenant_id = ?",
            (cluster_id, tenant_id),
        ).fetchone()
    return dict(row) if row else None


def decrypt_cluster_kubeconfig(tenant_id, cluster_id):
    row = get_cluster(tenant_id, cluster_id)
    if not row:
        return None
    fernet, invalid_token = _fernet()
    try:
        return fernet.decrypt(row["kubeconfig_ciphertext"])
    except invalid_token as exc:
        raise RuntimeError("Não foi possível descriptografar o kubeconfig armazenado") from exc


def delete_cluster(tenant_id, cluster_id):
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM clusters WHERE id = ? AND tenant_id = ?",
            (cluster_id, tenant_id),
        )
    return cursor.rowcount > 0


def list_companies():
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, company_name, created_at FROM tenants ORDER BY created_at"
        ).fetchall()
    return [dict(row) for row in rows]
