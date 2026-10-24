"""Diário de bordo: pendências e notas operacionais por cluster.

Fica no mesmo SQLite das contas, isolado por tenant e cluster.
"""
import uuid
from datetime import date, datetime, timezone

from accounts.store import _connect

KINDS = ("pendencia", "nota")
STATUSES = ("aberta", "andamento", "concluida")
_ready = False


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ensure():
    global _ready
    if _ready:
        return
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS journal_entries (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                cluster_id TEXT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'aberta',
                assignee TEXT NOT NULL DEFAULT '',
                due_date TEXT,
                link_type TEXT,
                link_ref TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_by TEXT,
                updated_at TEXT NOT NULL,
                closed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS journal_scope_idx ON journal_entries(tenant_id, cluster_id, status);
            """
        )
    _ready = True


def _row(row):
    item = dict(row)
    item["overdue"] = bool(
        item["kind"] == "pendencia" and item["status"] != "concluida"
        and item["due_date"] and item["due_date"] < date.today().isoformat()
    )
    return item


def _validate(kind=None, status=None, due_date=None):
    if kind is not None and kind not in KINDS:
        raise ValueError("Tipo inválido")
    if status is not None and status not in STATUSES:
        raise ValueError("Status inválido")
    if due_date:
        date.fromisoformat(due_date)  # ValueError se não for AAAA-MM-DD


def create_entry(tenant_id, cluster_id, actor, kind, title, body="", assignee="", due_date=None,
                 link_type=None, link_ref=None):
    _ensure()
    _validate(kind=kind, due_date=due_date)
    now = _now()
    entry_id = uuid.uuid4().hex[:12]
    status = "aberta" if kind == "pendencia" else "concluida"
    with _connect() as connection:
        connection.execute(
            "INSERT INTO journal_entries (id, tenant_id, cluster_id, kind, title, body, status, assignee, due_date,"
            " link_type, link_ref, created_by, created_at, updated_by, updated_at, closed_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (entry_id, tenant_id, cluster_id, kind, title.strip(), body.strip(), status, assignee.strip(),
             due_date or None, link_type, link_ref, actor, now, actor, now, now if status == "concluida" else None),
        )
    return get_entry(tenant_id, entry_id)


def get_entry(tenant_id, entry_id):
    _ensure()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM journal_entries WHERE tenant_id = ? AND id = ?", (tenant_id, entry_id)
        ).fetchone()
    return _row(row) if row else None


def list_entries(tenant_id, cluster_id, status=None, kind=None, limit=300):
    _ensure()
    sql = "SELECT * FROM journal_entries WHERE tenant_id = ? AND (cluster_id IS ? OR cluster_id = ?)"
    args = [tenant_id, cluster_id, cluster_id]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    if status in ("abertas", "atrasadas"):
        sql += " AND status != 'concluida'"
    elif status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _connect() as connection:
        items = [_row(r) for r in connection.execute(sql, args)]
    if status == "atrasadas":
        items = [i for i in items if i["overdue"]]
    return items


def summary(tenant_id, cluster_id):
    """Contadores e as 3 pendências mais urgentes (atrasadas, depois por prazo)."""
    open_items = [i for i in list_entries(tenant_id, cluster_id, status="abertas", kind="pendencia")]
    open_items.sort(key=lambda i: (not i["overdue"], i["due_date"] or "9999-12-31", i["created_at"]))
    return {"open": len(open_items), "overdue": sum(1 for i in open_items if i["overdue"]), "top": open_items[:3]}


def update_entry(tenant_id, entry_id, actor, **fields):
    _ensure()
    current = get_entry(tenant_id, entry_id)
    if not current:
        return None
    allowed = {k: v for k, v in fields.items() if k in {"title", "body", "status", "assignee", "due_date"} and v is not None}
    _validate(status=allowed.get("status"), due_date=allowed.get("due_date"))
    if "due_date" in allowed and allowed["due_date"] == "":
        allowed["due_date"] = None
    if "status" in allowed:
        allowed["closed_at"] = _now() if allowed["status"] == "concluida" else None
    allowed["updated_by"] = actor
    allowed["updated_at"] = _now()
    sets = ", ".join(f"{k} = ?" for k in allowed)
    with _connect() as connection:
        connection.execute(f"UPDATE journal_entries SET {sets} WHERE tenant_id = ? AND id = ?",
                           (*allowed.values(), tenant_id, entry_id))
    return get_entry(tenant_id, entry_id)


def delete_entry(tenant_id, entry_id):
    _ensure()
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM journal_entries WHERE tenant_id = ? AND id = ?", (tenant_id, entry_id))
    return cursor.rowcount > 0
