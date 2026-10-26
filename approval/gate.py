from datetime import datetime, timezone

from config import AUTO_EXECUTE, REQUIRE_APPROVAL

from approval.store import append_audit, load_recommendations, update_recommendation


def get_recommendation(rec_id):

    data = load_recommendations()

    for item in data["items"]:
        if item["id"] == rec_id:
            return item, data

    return None, data


def list_by_status(status=None):

    data = load_recommendations()
    items = data["items"]

    if status:
        items = [i for i in items if i["status"] == status]

    return data["evaluation_id"], items


def approve(rec_id, approver):

    def mutate(item):
        if item["status"] != "pending":
            return f"Recomendação já está com status '{item['status']}'"
        if not item.get("operation", {}).get("executable"):
            return ("Esta recomendação requer intervenção manual e não pode ser "
                    "aprovada para execução automática")
        item["status"] = "approved"
        item["approved_by"] = approver
        item["approved_at"] = datetime.now(timezone.utc).isoformat()
        return None

    item, error = update_recommendation(rec_id, mutate)

    if item is None:
        return {"success": False, "error": f"Recomendação {rec_id} não encontrada"}
    if error:
        return {"success": False, "error": error}

    append_audit("approve", {
        "rec_id": rec_id,
        "approver": approver,
        "type": item["type"],
        "pool": item.get("pool"),
    })

    return {"success": True, "item": item}


def reject(rec_id, rejector, reason=""):

    def mutate(item):
        if item["status"] != "pending":
            return f"Recomendação já está com status '{item['status']}'"
        item["status"] = "rejected"
        item["rejected_by"] = rejector
        item["rejected_at"] = datetime.now(timezone.utc).isoformat()
        item["rejection_reason"] = reason
        return None

    item, error = update_recommendation(rec_id, mutate)

    if item is None:
        return {"success": False, "error": f"Recomendação {rec_id} não encontrada"}
    if error:
        return {"success": False, "error": error}

    append_audit("reject", {
        "rec_id": rec_id,
        "rejector": rejector,
        "reason": reason,
        "type": item["type"],
    })

    return {"success": True, "item": item}


def mark_executed(rec_id, result, executed_by=None):

    def mutate(item):
        item["status"] = "executed" if result.get("success") else "failed"
        item["executed_at"] = datetime.now(timezone.utc).isoformat()
        item["execution_result"] = result
        item["executed_by"] = executed_by
        return None

    item, _ = update_recommendation(rec_id, mutate)

    if item is None:
        return

    append_audit("execute", {
        "rec_id": rec_id,
        "success": result.get("success"),
        "executed_by": executed_by,
        "type": item["type"],
        "pool": item.get("pool"),
        "output": result.get("output", "")[:500],
    })


def can_execute(item, force=False):

    if not item.get("operation", {}).get("executable"):
        return False, "Operação não executável automaticamente"

    if item["status"] != "approved":
        return False, f"Status atual: {item['status']} — requer aprovação DevOps"

    if REQUIRE_APPROVAL and not item.get("approved_by"):
        return False, "Aprovação DevOps obrigatória"

    if not AUTO_EXECUTE and not force:
        return False, "AUTO_EXECUTE desabilitado — use --force para executar"

    return True, None


def gate_summary():

    data = load_recommendations()
    items = data["items"]

    counts = {}

    for item in items:
        status = item["status"]
        counts[status] = counts.get(status, 0) + 1

    return {
        "evaluation_id": data.get("evaluation_id"),
        "updated_at": data.get("updated_at"),
        "counts": counts,
        "require_approval": REQUIRE_APPROVAL,
        "auto_execute": AUTO_EXECUTE,
    }
