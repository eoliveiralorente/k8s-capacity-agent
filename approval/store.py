import json
import os
from datetime import datetime, timezone

from config import STATE_DIR
from tenant_context import current_cluster_id, current_tenant_id


def _state_path(filename):

    tenant_id = current_tenant_id.get()
    if not tenant_id:
        return os.path.join(STATE_DIR, filename)

    cluster_id = current_cluster_id.get() or "unassigned"
    return os.path.join(STATE_DIR, "tenants", tenant_id, cluster_id, filename)


def ensure_state_dir():

    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(_state_path("reports"), exist_ok=True)


def save_report(evaluation_id, report):

    ensure_state_dir()

    path = _state_path(f"reports/{evaluation_id}.json")

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    return path


def load_report(evaluation_id):

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

        if not filename.endswith(".json"):
            continue

        if filename.startswith("executive-"):
            continue

        path = os.path.join(reports_dir, filename)

        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)

        created_at = data.get("created_at", "")

        reports.append({
            "evaluation_id": filename.replace(".json", ""),
            "created_at": created_at,
            "cluster": data.get("cluster"),
            "recommendations_count": len(
                data.get("recommendations", [])
            ),
            "_mtime": os.path.getmtime(path),
        })

    reports.sort(
        key=lambda item: item.get("created_at") or "",
        reverse=True,
    )

    for item in reports:
        item.pop("_mtime", None)

    return reports


def load_recommendations():

    ensure_state_dir()

    path = _state_path("recommendations.json")

    if not os.path.isfile(path):
        return {"evaluation_id": None, "items": []}

    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_recommendations(evaluation_id, items):

    ensure_state_dir()

    data = {
        "evaluation_id": evaluation_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }

    path = _state_path("recommendations.json")

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)

    return path


def append_audit(event_type, details):

    ensure_state_dir()

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "details": details,
    }

    path = _state_path("audit.log")

    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_audit(limit=100):

    path = _state_path("audit.log")

    if not os.path.isfile(path):
        return []

    entries = []

    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    return list(reversed(entries[-limit:]))
