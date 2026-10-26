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
            CREATE TABLE IF NOT EXISTS invites (
                token_hash TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                email TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT
            );
            CREATE INDEX IF NOT EXISTS invites_tenant_idx ON invites(tenant_id);
            CREATE TABLE IF NOT EXISTS assistant_settings (
                tenant_id TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                base_url TEXT,
                api_version TEXT,
                auth_header TEXT,
                api_key_ciphertext BLOB,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alert_settings (
                tenant_id TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
                enabled INTEGER NOT NULL DEFAULT 1,
                min_severity TEXT NOT NULL DEFAULT 'MEDIUM',
                slack_url_c BLOB,
                teams_url_c BLOB,
                webhook_url_c BLOB,
                emails TEXT,
                include_ai INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cost_settings (
                tenant_id TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
                currency TEXT NOT NULL DEFAULT 'BRL',
                cpu_month REAL NOT NULL DEFAULT 0,
                gb_month REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assistant_usage (
                tenant_id TEXT NOT NULL,
                day TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (tenant_id, day)
            );
            """
        )
        # Migração RBAC: contas existentes viram admin.
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        if "role" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
        # Migração modo agente: clusters conectados por coletor in-cluster.
        cluster_columns = {row["name"] for row in connection.execute("PRAGMA table_info(clusters)")}
        if "mode" not in cluster_columns:
            connection.execute("ALTER TABLE clusters ADD COLUMN mode TEXT NOT NULL DEFAULT 'kubeconfig'")
        if "ingest_token_hash" not in cluster_columns:
            connection.execute("ALTER TABLE clusters ADD COLUMN ingest_token_hash TEXT")
        if "last_seen_at" not in cluster_columns:
            connection.execute("ALTER TABLE clusters ADD COLUMN last_seen_at TEXT")
        cost_columns = {row["name"] for row in connection.execute("PRAGMA table_info(cost_settings)")}
        for column in ("machine_prices", "fixed_costs"):
            if column not in cost_columns:
                connection.execute(f"ALTER TABLE cost_settings ADD COLUMN {column} TEXT")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS clusters_ingest_idx ON clusters(ingest_token_hash) "
            "WHERE ingest_token_hash IS NOT NULL"
        )
    try:
        DB_PATH.chmod(0o600)
        DB_PATH.parent.chmod(0o700)
    except OSError:
        pass
    _fernet()


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
                "INSERT INTO users(id, tenant_id, full_name, email, password_hash, created_at, role) "
                "VALUES (?, ?, ?, ?, ?, ?, 'admin')",
                (user_id, tenant_id, full_name.strip(), email, _hash_password(password), now),
            )
    except sqlite3.IntegrityError as exc:
        raise DuplicateAccountError("Já existe uma conta com esse e-mail") from exc
    return {"id": user_id, "tenant_id": tenant_id, "full_name": full_name.strip(), "email": email,
            "company_name": company_name.strip(), "role": "admin"}


def authenticate(email, password):
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT users.id, users.tenant_id, users.full_name, users.email, users.password_hash, "
            "users.role, tenants.company_name FROM users JOIN tenants ON tenants.id = users.tenant_id "
            "WHERE users.email = ?",
            (email.strip().lower(),),
        ).fetchone()
    if row is None or not _verify_password(password, row["password_hash"]):
        return None
    return {key: row[key] for key in ("id", "tenant_id", "full_name", "email", "company_name", "role")}


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
            "SELECT users.id, users.tenant_id, users.full_name, users.email, users.role, "
            "tenants.company_name, sessions.expires_at FROM sessions JOIN users ON users.id = sessions.user_id "
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
    from cryptography.fernet import Fernet, InvalidToken

    key = os.getenv("CAPACITY_AGENT_ENCRYPTION_KEY", "").strip()
    if not key:
        key_path = DB_PATH.with_name("encryption.key")
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            key = key_path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            generated_key = Fernet.generate_key()
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=".encryption-", dir=key_path.parent
            )
            try:
                with os.fdopen(file_descriptor, "wb") as key_file:
                    key_file.write(generated_key)
                    key_file.flush()
                    os.fsync(key_file.fileno())
                try:
                    os.link(temporary_path, key_path)
                except FileExistsError:
                    pass
                key_path.chmod(0o600)
                key = key_path.read_text(encoding="ascii").strip()
            finally:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
        except UnicodeDecodeError as exc:
            raise RuntimeError("Chave de criptografia persistida inválida") from exc

    try:
        return Fernet(key.encode("ascii")), InvalidToken
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError(
            "CAPACITY_AGENT_ENCRYPTION_KEY inválida. Use uma chave Fernet gerada "
            "com `Fernet.generate_key()` ou remova a variável para usar a chave "
            f"persistida em {DB_PATH.with_name('encryption.key')}."
        ) from exc


def _run_kubectl_for_kubeconfig(kubeconfig, args):
    if len(kubeconfig) > MAX_KUBECONFIG_BYTES:
        raise ValueError("Arquivo kubeconfig excede o limite de 2 MB")
    _fernet()
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


def _hash_ingest_token(token):
    return hashlib.sha256(("ingest:" + (token or "")).encode("utf-8")).hexdigest()


def create_agent_cluster(tenant_id, name):
    """Cluster conectado por coletor in-cluster. Retorna (cluster, token em claro — exibido uma vez)."""
    initialize_database()
    fernet, _ = _fernet()
    token = "cag_" + secrets.token_urlsafe(32)
    cluster_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as connection:
            connection.execute(
                "INSERT INTO clusters(id, tenant_id, name, context_name, node_count, kubeconfig_ciphertext, "
                "created_at, mode, ingest_token_hash) VALUES (?, ?, ?, ?, 0, ?, ?, 'agent', ?)",
                (cluster_id, tenant_id, name.strip(), "agente", fernet.encrypt(b""), now,
                 _hash_ingest_token(token)),
            )
    except sqlite3.IntegrityError as exc:
        raise DuplicateClusterError("Já existe um cluster com esse nome nesta empresa") from exc
    return {"id": cluster_id, "name": name.strip(), "context_name": "agente", "node_count": 0,
            "created_at": now, "mode": "agent", "last_seen_at": None}, token


def rotate_ingest_token(tenant_id, cluster_id):
    initialize_database()
    token = "cag_" + secrets.token_urlsafe(32)
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE clusters SET ingest_token_hash = ? WHERE id = ? AND tenant_id = ? AND mode = 'agent'",
            (_hash_ingest_token(token), cluster_id, tenant_id),
        )
    return token if cursor.rowcount else None


def count_tenants():
    initialize_database()
    with _connect() as connection:
        return connection.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]


def ensure_incluster_cluster(tenant_id, name):
    """Modo self-hosted: registra o próprio cluster (acesso via ServiceAccount do pod)."""
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT id FROM clusters WHERE tenant_id = ? AND mode = 'incluster'", (tenant_id,)
        ).fetchone()
        if row:
            return row["id"]
    fernet, _ = _fernet()
    cluster_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO clusters(id, tenant_id, name, context_name, node_count, kubeconfig_ciphertext, "
            "created_at, mode) VALUES (?, ?, ?, ?, 0, ?, ?, 'incluster')",
            (cluster_id, tenant_id, name.strip(), "in-cluster", fernet.encrypt(b""), now),
        )
    return cluster_id


def find_cluster_by_ingest_token(token):
    if not token or not token.startswith("cag_"):
        return None
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, tenant_id, name, last_seen_at FROM clusters "
            "WHERE ingest_token_hash = ? AND mode = 'agent'",
            (_hash_ingest_token(token),),
        ).fetchone()
    return dict(row) if row else None


def touch_agent_cluster(cluster_id, node_count, context_name=None):
    with _connect() as connection:
        connection.execute(
            "UPDATE clusters SET last_seen_at = ?, node_count = ?, context_name = COALESCE(?, context_name) "
            "WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), node_count, context_name, cluster_id),
        )


def list_clusters(tenant_id):
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, name, context_name, node_count, created_at, mode, last_seen_at FROM clusters "
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
            "SELECT id, tenant_id, name, context_name, node_count, kubeconfig_ciphertext, created_at, "
            "mode, last_seen_at FROM clusters WHERE id = ? AND tenant_id = ?",
            (cluster_id, tenant_id),
        ).fetchone()
    return dict(row) if row else None


def decrypt_cluster_kubeconfig(tenant_id, cluster_id):
    row = get_cluster(tenant_id, cluster_id)
    if not row or row.get("mode") == "agent":
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


def list_all_clusters():
    """Todos os clusters de todas as empresas (uso interno do amostrador)."""
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, tenant_id, name, mode FROM clusters ORDER BY created_at"
        ).fetchall()
    return [dict(row) for row in rows]


def list_companies():
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, company_name, created_at FROM tenants ORDER BY created_at"
        ).fetchall()
    return [dict(row) for row in rows]



# ── Usuários e convites (RBAC) ─────────────────────────────────

INVITE_TTL_DAYS = 7
VALID_ROLES = ("leitor", "operador", "admin")


class InviteError(ValueError):
    pass


class LastAdminError(ValueError):
    pass


def _hash_token(token):
    return hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()


def create_invite(tenant_id, role, created_by, email=None):
    if role not in VALID_ROLES:
        raise InviteError("Papel inválido")
    initialize_database()
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=INVITE_TTL_DAYS)).isoformat()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO invites(token_hash, tenant_id, role, email, created_by, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_hash_token(token), tenant_id, role, (email or "").strip().lower() or None,
             created_by, now.isoformat(), expires_at),
        )
    return token, expires_at


def accept_invite(token, full_name, email, password):
    initialize_database()
    email = email.strip().lower()
    now = datetime.now(timezone.utc).isoformat()
    token_hash = _hash_token(token or "")
    with _connect() as connection:
        invite = connection.execute(
            "SELECT invites.*, tenants.company_name FROM invites "
            "JOIN tenants ON tenants.id = invites.tenant_id WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if invite is None or invite["used_at"] or invite["expires_at"] <= now:
            raise InviteError("Convite inválido, expirado ou já utilizado")
        if invite["email"] and invite["email"] != email:
            raise InviteError("Este convite foi emitido para outro e-mail")
        user_id = uuid.uuid4().hex
        try:
            connection.execute(
                "INSERT INTO users(id, tenant_id, full_name, email, password_hash, created_at, role) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, invite["tenant_id"], full_name.strip(), email,
                 _hash_password(password), now, invite["role"]),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateAccountError("Já existe uma conta com esse e-mail") from exc
        connection.execute("UPDATE invites SET used_at = ? WHERE token_hash = ?", (now, token_hash))
    return {"id": user_id, "tenant_id": invite["tenant_id"], "full_name": full_name.strip(),
            "email": email, "company_name": invite["company_name"], "role": invite["role"]}


def list_users(tenant_id):
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, full_name, email, role, created_at FROM users WHERE tenant_id = ? "
            "ORDER BY created_at",
            (tenant_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_invites(tenant_id):
    initialize_database()
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT role, email, created_by, created_at, expires_at FROM invites "
            "WHERE tenant_id = ? AND used_at IS NULL AND expires_at > ? ORDER BY created_at DESC",
            (tenant_id, now),
        ).fetchall()
    return [dict(row) for row in rows]


def _admin_count(connection, tenant_id):
    return connection.execute(
        "SELECT COUNT(*) FROM users WHERE tenant_id = ? AND role = 'admin'", (tenant_id,)
    ).fetchone()[0]


def set_user_role(tenant_id, user_id, role):
    if role not in VALID_ROLES:
        raise InviteError("Papel inválido")
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT role FROM users WHERE id = ? AND tenant_id = ?", (user_id, tenant_id)
        ).fetchone()
        if row is None:
            return False
        if row["role"] == "admin" and role != "admin" and _admin_count(connection, tenant_id) <= 1:
            raise LastAdminError("A empresa precisa manter pelo menos um admin")
        connection.execute(
            "UPDATE users SET role = ? WHERE id = ? AND tenant_id = ?", (role, user_id, tenant_id)
        )
        # Papel mudou: encerra sessões para valer imediatamente.
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return True


def delete_user(tenant_id, user_id):
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT role FROM users WHERE id = ? AND tenant_id = ?", (user_id, tenant_id)
        ).fetchone()
        if row is None:
            return False
        if row["role"] == "admin" and _admin_count(connection, tenant_id) <= 1:
            raise LastAdminError("A empresa precisa manter pelo menos um admin")
        connection.execute("DELETE FROM users WHERE id = ? AND tenant_id = ?", (user_id, tenant_id))
    return True



# ── Assistente de IA (configuração por empresa) ───────────────

def get_assistant_config(tenant_id, include_key=False):
    initialize_database()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM assistant_settings WHERE tenant_id = ?", (tenant_id,)).fetchone()
    if not row:
        return None
    config = {k: row[k] for k in ("provider", "model", "base_url", "api_version", "auth_header", "updated_at")}
    config["enabled"] = bool(row["enabled"])
    config["has_key"] = bool(row["api_key_ciphertext"])
    if include_key and row["api_key_ciphertext"]:
        fernet, invalid = _fernet()
        try:
            config["api_key"] = fernet.decrypt(row["api_key_ciphertext"]).decode("utf-8")
        except invalid as exc:
            raise RuntimeError("Não foi possível descriptografar a chave do assistente") from exc
    return config


def save_assistant_config(tenant_id, provider, model, base_url=None, api_version=None,
                          auth_header=None, api_key=None, enabled=True):
    """api_key=None mantém a chave atual; api_key="" remove."""
    initialize_database()
    fernet, _ = _fernet()
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        current = connection.execute(
            "SELECT api_key_ciphertext FROM assistant_settings WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        if api_key is None:
            ciphertext = current["api_key_ciphertext"] if current else None
        else:
            ciphertext = fernet.encrypt(api_key.encode("utf-8")) if api_key else None
        connection.execute(
            "INSERT OR REPLACE INTO assistant_settings(tenant_id, provider, model, base_url, api_version, "
            "auth_header, api_key_ciphertext, enabled, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, provider, model, base_url or None, api_version or None, auth_header or None,
             ciphertext, int(bool(enabled)), now),
        )


def increment_assistant_usage(tenant_id):
    initialize_database()
    day = datetime.now(timezone.utc).date().isoformat()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO assistant_usage(tenant_id, day, count) VALUES (?, ?, 1) "
            "ON CONFLICT(tenant_id, day) DO UPDATE SET count = count + 1",
            (tenant_id, day),
        )
        return connection.execute(
            "SELECT count FROM assistant_usage WHERE tenant_id = ? AND day = ?", (tenant_id, day)
        ).fetchone()[0]



# ── Custos (estimativa de economia) ───────────────────────────

def get_cost_settings(tenant_id):
    from analyzers.costs import default_settings

    if not tenant_id:
        return default_settings()
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT currency, cpu_month, gb_month, machine_prices, fixed_costs, updated_at "
            "FROM cost_settings WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
    if not row:
        return default_settings()
    settings = dict(row)
    for key in ("machine_prices", "fixed_costs"):
        try:
            settings[key] = json.loads(settings.get(key) or "[]")
        except ValueError:
            settings[key] = []
    return settings


def save_cost_settings(tenant_id, cpu_month, gb_month, currency="BRL", machine_prices=None, fixed_costs=None):
    """machine_prices/fixed_costs=None mantém o que já está salvo."""
    initialize_database()
    current = get_cost_settings(tenant_id)
    machine_prices = current.get("machine_prices", []) if machine_prices is None else machine_prices
    fixed_costs = current.get("fixed_costs", []) if fixed_costs is None else fixed_costs
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO cost_settings(tenant_id, currency, cpu_month, gb_month, machine_prices, "
            "fixed_costs, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, currency, float(cpu_month), float(gb_month), json.dumps(machine_prices),
             json.dumps(fixed_costs), datetime.now(timezone.utc).isoformat()),
        )



# ── Alertas (canais por empresa; URLs cifradas) ───────────────

_ALERT_URLS = ("slack_url", "teams_url", "webhook_url")


def get_alert_settings(tenant_id, include_secrets=False):
    initialize_database()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM alert_settings WHERE tenant_id = ?", (tenant_id,)).fetchone()
    if not row:
        return None
    fernet, invalid = _fernet()
    config = {"enabled": bool(row["enabled"]), "min_severity": row["min_severity"],
              "emails": row["emails"] or "", "include_ai": bool(row["include_ai"]), "updated_at": row["updated_at"]}
    for name in _ALERT_URLS:
        blob = row[f"{name}_c"]
        config[f"has_{name}"] = bool(blob)
        if include_secrets and blob:
            try:
                config[name] = fernet.decrypt(blob).decode("utf-8")
            except invalid:
                config[name] = None
    return config


def save_alert_settings(tenant_id, enabled=True, min_severity="MEDIUM", emails="", include_ai=False, **urls):
    """urls: slack_url/teams_url/webhook_url — None mantém, "" remove, valor substitui."""
    initialize_database()
    fernet, _ = _fernet()
    with _connect() as connection:
        current = connection.execute("SELECT * FROM alert_settings WHERE tenant_id = ?", (tenant_id,)).fetchone()
        blobs = {}
        for name in _ALERT_URLS:
            value = urls.get(name)
            if value is None:
                blobs[name] = current[f"{name}_c"] if current else None
            else:
                blobs[name] = fernet.encrypt(value.encode("utf-8")) if value else None
        connection.execute(
            "INSERT OR REPLACE INTO alert_settings(tenant_id, enabled, min_severity, slack_url_c, teams_url_c, "
            "webhook_url_c, emails, include_ai, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, int(bool(enabled)), min_severity, blobs["slack_url"], blobs["teams_url"],
             blobs["webhook_url"], emails or None, int(bool(include_ai)), datetime.now(timezone.utc).isoformat()),
        )
