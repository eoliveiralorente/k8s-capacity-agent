from datetime import datetime, timezone

from config import AUTO_EXECUTE, REQUIRE_APPROVAL

from approval.store import append_audit, load_recommendations, save_recommendations


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

    item, data = get_recommendation(rec_id)

    if item is None:
        return {"success": False, "error": f"Recomendação {rec_id} não encontrada"}

    if item["status"] != "pending":
        return {
            "success": False,
            "error": f"Recomendação já está com status '{item['status']}'",
        }

    if not item.get("operation", {}).get("executable"):
        return {
            "success": False,
            "error": "Esta recomendação requer intervenção manual e não pode ser aprovada para execução automática",
        }

    now = datetime.now(timezone.utc).isoformat()

    item["status"] = "approved"
    item["approved_by"] = approver
    item["approved_at"] = now

    save_recommendations(data["evaluation_id"], data["items"])

    append_audit("approve", {
        "rec_id": rec_id,
        "approver": approver,
        "type": item["type"],
        "pool": item.get("pool"),
    })

    return {"success": True, "item": item}


def reject(rec_id, rejector, reason=""):

    item, data = get_recommendation(rec_id)

    if item is None:
        return {"success": False, "error": f"Recomendação {rec_id} não encontrada"}

    if item["status"] != "pending":
        return {
            "success": False,
            "error": f"Recomendação já está com status '{item['status']}'",
        }

    now = datetime.now(timezone.utc).isoformat()

    item["status"] = "rejected"
    item["rejected_by"] = rejector
    item["rejected_at"] = now
    item["rejection_reason"] = reason

    save_recommendations(data["evaluation_id"], data["items"])

    append_audit("reject", {
        "rec_id": rec_id,
        "rejector": rejector,
        "reason": reason,
        "type": item["type"],
    })

    return {"success": True, "item": item}


def mark_executed(rec_id, result):

    item, data = get_recommendation(rec_id)

    if item is None:
        return

    item["status"] = "executed" if result.get("success") else "failed"
    item["executed_at"] = datetime.now(timezone.utc).isoformat()
    item["execution_result"] = result

    save_recommendations(data["evaluation_id"], data["items"])

    append_audit("execute", {
        "rec_id": rec_id,
        "success": result.get("success"),
        "type": item["type"],
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
