"""Estado operacional do agente.

- Relatórios de avaliação: arquivos JSON imutáveis por empresa/cluster
  (gravação atômica).
- Recomendações e auditoria: SQLite com transações (mesmo banco das contas),
  seguro para acessos simultâneos. A auditoria é unificada por empresa.

Na primeira leitura de um escopo, os arquivos legados recommendations.json e
audit.log são importados automaticamente (uma única vez).
"""
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import STATE_DIR
from tenant_context import current_cluster_id, current_cluster_name, current_tenant_id

LOCAL_TENANT = "local"
UNASSIGNED_CLUSTER = "unassigned"


# ── Escopo e arquivos de relatório ─────────────────────────────

def _scope():
    return (
        current_tenant_id.get() or LOCAL_TENANT,
        current_cluster_id.get() or UNASSIGNED_CLUSTER,
    )


def _state_path(filename):

    tenant_id = current_tenant_id.get()
    if not tenant_id:
        return os.path.join(STATE_DIR, filename)

    cluster_id = current_cluster_id.get() or UNASSIGNED_CLUSTER
    return os.path.join(STATE_DIR, "tenants", tenant_id, cluster_id, filename)


def ensure_state_dir():

    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(_state_path("reports"), exist_ok=True)


def _atomic_write_json(path, data):
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_report(evaluation_id, report):

    ensure_state_dir()

    path = _state_path(f"reports/{evaluation_id}.json")
    _atomic_write_json(path, report)

    return path


def load_report(evaluation_id):

    if not evaluation_id or "/" in evaluation_id or "\\" in evaluation_id or ".." in evaluation_id:
        raise FileNotFoundError(evaluation_id)

    path = _state_path(f"reports/{evaluation_id}.json")

    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def get_latest_evaluation_id():

    recs = load_recommendations()
    evaluation_id = recs.get("evaluation_id")

    if evaluation_id:
        report_path = _state_path(f"reports/{evaluation_id}.json")
        if os.path.isfile(report_path):
            return evaluation_id

    reports = list_reports()
    if reports:
        return reports[0]["evaluation_id"]

    return None


def load_latest_report():

    evaluation_id = get_latest_evaluation_id()

    if not evaluation_id:
        return None

    return load_report(evaluation_id)


def list_reports():

    reports_dir = _state_path("reports")

    if not os.path.isdir(reports_dir):
        return []

    reports = []

    for filename in os.listdir(reports_dir):

        if not filename.endswith(".json") or filename.startswith(("executive-", ".tmp-")):
            continue

        path = os.path.join(reports_dir, filename)

        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue

        reports.append({
            "evaluation_id": filename.replace(".json", ""),
            "created_at": data.get("created_at", ""),
            "cluster": data.get("cluster"),
            "recommendations_count": len(data.get("recommendations", [])),
        })

    reports.sort(key=lambda item: item.get("created_at") or "", reverse=True)

    return reports


# ── SQLite ─────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendation_sets (
    tenant_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL,
    evaluation_id TEXT,
    updated_at TEXT,
    legacy_imported INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, cluster_id)
);
CREATE TABLE IF NOT EXISTS recommendations (
    tenant_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL,
    id TEXT NOT NULL,
    position INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, cluster_id, id)
);
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metric_samples (
    tenant_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    pool TEXT NOT NULL,
    node_count INTEGER NOT NULL,
    cpu_usage_pct REAL,
    mem_usage_pct REAL,
    cpu_req_pct REAL,
    mem_req_pct REAL
);
CREATE INDEX IF NOT EXISTS samples_scope_idx ON metric_samples(tenant_id, cluster_id, timestamp);
CREATE TABLE IF NOT EXISTS workload_samples (
    tenant_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    workload TEXT NOT NULL,
    cpu_m INTEGER NOT NULL,
    mem_b INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS wsamples_scope_idx ON workload_samples(tenant_id, cluster_id, workload, timestamp);
CREATE INDEX IF NOT EXISTS audit_tenant_idx ON audit_log(tenant_id, timestamp);
"""


def _db_path():
    # Lido a cada chamada para respeitar configuração e testes.
    from accounts import store as account_store
    return Path(account_store.DB_PATH)


@contextmanager
def _transaction(write=False):
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=20, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout = 20000")
        connection.executescript(_SCHEMA)
        connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()


def _import_legacy(connection, tenant_id, cluster_id):
    """Importa recommendations.json e audit.log antigos uma única vez por escopo."""
    row = connection.execute(
        "SELECT legacy_imported FROM recommendation_sets WHERE tenant_id = ? AND cluster_id = ?",
        (tenant_id, cluster_id),
    ).fetchone()
    if row and row["legacy_imported"]:
        return

    recs_path = _state_path("recommendations.json")
    evaluation_id, updated_at, items = None, None, []
    if os.path.isfile(recs_path):
        try:
            with open(recs_path, encoding="utf-8") as handle:
                legacy = json.load(handle)
            evaluation_id = legacy.get("evaluation_id")
            updated_at = legacy.get("updated_at")
            items = legacy.get("items", [])
        except (OSError, ValueError):
            pass

    connection.execute(
        "INSERT INTO recommendation_sets(tenant_id, cluster_id, evaluation_id, updated_at, legacy_imported) "
        "VALUES (?, ?, ?, ?, 1) ON CONFLICT(tenant_id, cluster_id) DO UPDATE SET legacy_imported = 1",
        (tenant_id, cluster_id, evaluation_id, updated_at),
    )
    for position, item in enumerate(items):
        connection.execute(
            "INSERT OR IGNORE INTO recommendations(tenant_id, cluster_id, id, position, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (tenant_id, cluster_id, item["id"], position, json.dumps(item, ensure_ascii=False)),
        )

    audit_path = _state_path("audit.log")
    if os.path.isfile(audit_path):
        with open(audit_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                connection.execute(
                    "INSERT INTO audit_log(tenant_id, cluster_id, timestamp, event, details) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (tenant_id, cluster_id, entry.get("timestamp", ""), entry.get("event", ""),
                     json.dumps(entry.get("details", {}), ensure_ascii=False)),
                )


# ── Recomendações ──────────────────────────────────────────────

def load_recommendations():

    tenant_id, cluster_id = _scope()

    with _transaction(write=True) as connection:
        _import_legacy(connection, tenant_id, cluster_id)
        meta = connection.execute(
            "SELECT evaluation_id, updated_at FROM recommendation_sets "
            "WHERE tenant_id = ? AND cluster_id = ?",
            (tenant_id, cluster_id),
        ).fetchone()
        rows = connection.execute(
            "SELECT data FROM recommendations WHERE tenant_id = ? AND cluster_id = ? ORDER BY position",
            (tenant_id, cluster_id),
        ).fetchall()

    return {
        "evaluation_id": meta["evaluation_id"] if meta else None,
        "updated_at": meta["updated_at"] if meta else None,
        "items": [json.loads(row["data"]) for row in rows],
    }


def save_recommendations(evaluation_id, items):

    tenant_id, cluster_id = _scope()
    now = datetime.now(timezone.utc).isoformat()

    with _transaction(write=True) as connection:
        _import_legacy(connection, tenant_id, cluster_id)
        connection.execute(
            "UPDATE recommendation_sets SET evaluation_id = ?, updated_at = ? "
            "WHERE tenant_id = ? AND cluster_id = ?",
            (evaluation_id, now, tenant_id, cluster_id),
        )
        connection.execute(
            "DELETE FROM recommendations WHERE tenant_id = ? AND cluster_id = ?",
            (tenant_id, cluster_id),
        )
        for position, item in enumerate(items):
            connection.execute(
                "INSERT OR REPLACE INTO recommendations(tenant_id, cluster_id, id, position, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (tenant_id, cluster_id, item["id"], position, json.dumps(item, ensure_ascii=False)),
            )

    return f"sqlite:{tenant_id}/{cluster_id}"


def update_recommendation(rec_id, mutate):
    """Lê, altera e grava uma recomendação numa única transação.

    `mutate(item)` altera o dicionário e retorna None em caso de sucesso ou uma
    mensagem de erro (str) para abortar sem gravar.
    Retorna (item, erro); item é None se a recomendação não existir.
    """
    tenant_id, cluster_id = _scope()

    with _transaction(write=True) as connection:
        _import_legacy(connection, tenant_id, cluster_id)
        row = connection.execute(
            "SELECT data FROM recommendations WHERE tenant_id = ? AND cluster_id = ? AND id = ?",
            (tenant_id, cluster_id, rec_id),
        ).fetchone()
        if row is None:
            return None, None
        item = json.loads(row["data"])
        error = mutate(item)
        if error:
            return item, error
        connection.execute(
            "UPDATE recommendations SET data = ? WHERE tenant_id = ? AND cluster_id = ? AND id = ?",
            (json.dumps(item, ensure_ascii=False), tenant_id, cluster_id, rec_id),
        )
        connection.execute(
            "UPDATE recommendation_sets SET updated_at = ? WHERE tenant_id = ? AND cluster_id = ?",
            (datetime.now(timezone.utc).isoformat(), tenant_id, cluster_id),
        )

    return item, None


# ── Auditoria (unificada por empresa) ──────────────────────────

def append_audit(event_type, details):

    tenant_id, cluster_id = _scope()
    details = dict(details or {})
    cluster_name = current_cluster_name.get()
    if cluster_name and "cluster" not in details:
        details["cluster"] = cluster_name

    with _transaction(write=True) as connection:
        _import_legacy(connection, tenant_id, cluster_id)
        connection.execute(
            "INSERT INTO audit_log(tenant_id, cluster_id, timestamp, event, details) VALUES (?, ?, ?, ?, ?)",
            (tenant_id, cluster_id, datetime.now(timezone.utc).isoformat(), event_type,
             json.dumps(details, ensure_ascii=False)),
        )


def load_audit(limit=100):

    tenant_id, cluster_id = _scope()
    limit = max(1, min(int(limit or 100), 1000))

    with _transaction(write=True) as connection:
        _import_legacy(connection, tenant_id, cluster_id)
        rows = connection.execute(
            "SELECT timestamp, event, details, cluster_id FROM audit_log WHERE tenant_id = ? "
            "ORDER BY timestamp DESC, seq DESC LIMIT ?",
            (tenant_id, limit),
        ).fetchall()

    return [
        {
            "timestamp": row["timestamp"],
            "event": row["event"],
            "details": json.loads(row["details"]),
            "cluster_id": row["cluster_id"],
        }
        for row in rows
    ]


# ── Amostras de métricas (histórico sem Prometheus) ─────────────

SAMPLE_RETENTION_DAYS = 30


def save_metric_samples(capacity, timestamp=None):
    """Grava uma amostra por pool a partir do resultado de analyze_capacity."""
    from datetime import timedelta

    tenant_id, cluster_id = _scope()
    now = timestamp or datetime.now(timezone.utc).isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SAMPLE_RETENTION_DAYS)).isoformat()

    with _transaction(write=True) as connection:
        for pool, data in (capacity or {}).items():
            metrics = data.get("metrics", {})
            connection.execute(
                "INSERT INTO metric_samples(tenant_id, cluster_id, timestamp, pool, node_count, "
                "cpu_usage_pct, mem_usage_pct, cpu_req_pct, mem_req_pct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tenant_id, cluster_id, now, pool,
                 data.get("capacity", {}).get("node_count", 0),
                 metrics.get("cpu_usage_vs_alloc_pct"), metrics.get("mem_usage_vs_alloc_pct"),
                 metrics.get("cpu_req_vs_alloc_pct"), metrics.get("mem_req_vs_alloc_pct")),
            )
        connection.execute(
            "DELETE FROM metric_samples WHERE tenant_id = ? AND cluster_id = ? AND timestamp < ?",
            (tenant_id, cluster_id, cutoff),
        )


def load_metric_samples(days=14):
    from datetime import timedelta

    tenant_id, cluster_id = _scope()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with _transaction() as connection:
        rows = connection.execute(
            "SELECT timestamp, pool, node_count, cpu_usage_pct, mem_usage_pct, cpu_req_pct, mem_req_pct "
            "FROM metric_samples WHERE tenant_id = ? AND cluster_id = ? AND timestamp >= ? "
            "ORDER BY timestamp",
            (tenant_id, cluster_id, since),
        ).fetchall()

    return [dict(row) for row in rows]


WORKLOAD_SAMPLE_RETENTION_DAYS = 14


def save_workload_samples(samples, timestamp=None):
    """samples: {workload_key: {"cpu_m": int, "mem_b": int}}"""
    from datetime import timedelta

    tenant_id, cluster_id = _scope()
    now = timestamp or datetime.now(timezone.utc).isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=WORKLOAD_SAMPLE_RETENTION_DAYS)).isoformat()

    with _transaction(write=True) as connection:
        connection.executemany(
            "INSERT INTO workload_samples(tenant_id, cluster_id, timestamp, workload, cpu_m, mem_b) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(tenant_id, cluster_id, now, key, int(v["cpu_m"]), int(v["mem_b"])) for key, v in samples.items()],
        )
        connection.execute(
            "DELETE FROM workload_samples WHERE tenant_id = ? AND cluster_id = ? AND timestamp < ?",
            (tenant_id, cluster_id, cutoff),
        )


def load_workload_samples(days=14):
    """Retorna {workload_key: [(timestamp, cpu_m, mem_b), ...]} em ordem cronológica."""
    from datetime import timedelta

    tenant_id, cluster_id = _scope()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with _transaction() as connection:
        rows = connection.execute(
            "SELECT workload, timestamp, cpu_m, mem_b FROM workload_samples "
            "WHERE tenant_id = ? AND cluster_id = ? AND timestamp >= ? ORDER BY timestamp",
            (tenant_id, cluster_id, since),
        ).fetchall()

    result = {}
    for row in rows:
        result.setdefault(row["workload"], []).append((row["timestamp"], row["cpu_m"], row["mem_b"]))
    return result
