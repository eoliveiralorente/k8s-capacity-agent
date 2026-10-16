import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from accounts.middleware import TenantAuthenticationMiddleware
from accounts.store import (
    DuplicateAccountError,
    DuplicateClusterError,
    authenticate,
    create_cluster,
    create_session,
    delete_cluster,
    delete_session,
    initialize_database,
    inspect_kubeconfig,
    list_clusters,
    register_account,
)
from approval.gate import (
    approve,
    can_execute,
    gate_summary,
    get_recommendation,
    list_by_status,
    mark_executed,
    reject,
)
from approval.store import list_reports, load_audit, load_latest_report, load_report
from config import (
    AUTO_EXECUTE,
    CLUSTER,
    KUBECONFIG,
    KUBERNETES_PROVIDER,
    PROJECT,
    REGION,
    REQUIRE_APPROVAL,
)
from collectors.kubernetes import (
    get_cluster_overview,
    get_cluster_pod_logs,
    get_cluster_pods,
)
from engine.evaluation import ensure_stability, run_evaluation, summarize_report_for_api
from executors.gke import execute_operation
from reporters.executive import build_executive_report
from tenant_context import (
    current_cluster_id,
    current_cluster_name,
    current_cluster_provider,
    current_user,
)

STATIC_DIR = Path(__file__).parent / "static"


class ApproveRequest(BaseModel):
    by: str = Field(min_length=1)


class RejectRequest(BaseModel):
    by: str = Field(min_length=1)
    reason: str = ""


class ExecuteRequest(BaseModel):
    dry_run: bool = False
    force: bool = True


class RegisterRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class ClusterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    kubeconfig: str = Field(min_length=1, max_length=2_000_000)


app = FastAPI(
    title="Capacity Agent Dashboard",
    description="Dashboard DevOps multiempresa para clusters Kubernetes",
    version="1.0.0",
)

app.add_middleware(TenantAuthenticationMiddleware)


@app.on_event("startup")
def startup():
    initialize_database()


def _set_session_cookie(response, token):
    secure = os.getenv("CAPACITY_AGENT_COOKIE_SECURE", "true").lower() == "true"
    response.set_cookie(
        "capacity_session",
        token,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=14 * 24 * 60 * 60,
        path="/",
    )


@app.post("/api/auth/register")
def api_register(body: RegisterRequest, response: Response):
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Informe um e-mail válido")
    try:
        user = register_account(body.company_name, body.full_name, email, body.password)
    except DuplicateAccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    token, _ = create_session(user["id"])
    _set_session_cookie(response, token)
    return user


@app.post("/api/auth/login")
def api_login(body: LoginRequest, response: Response):
    user = authenticate(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos")
    token, _ = create_session(user["id"])
    _set_session_cookie(response, token)
    return user


@app.post("/api/auth/logout")
def api_logout(request: Request, response: Response):
    delete_session(request.cookies.get("capacity_session"))
    secure = os.getenv("CAPACITY_AGENT_COOKIE_SECURE", "true").lower() == "true"
    response.delete_cookie("capacity_session", path="/", secure=secure, httponly=True, samesite="strict")
    return {"success": True}


@app.get("/api/auth/me")
def api_auth_me():
    user = current_user.get()
    if not user:
        raise HTTPException(status_code=401, detail="Autenticação necessária")
    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "company_name": user["company_name"],
        "tenant_id": user["tenant_id"],
    }


@app.get("/api/clusters")
def api_clusters():
    user = current_user.get()
    return {"clusters": list_clusters(user["tenant_id"])}


@app.post("/api/clusters")
def api_add_cluster(body: ClusterRequest):
    user = current_user.get()
    kubeconfig = body.kubeconfig.encode("utf-8")
    try:
        profile = inspect_kubeconfig(kubeconfig)
        cluster = create_cluster(
            user["tenant_id"], body.name, kubeconfig,
            profile["context_name"], profile["node_count"],
        )
    except DuplicateClusterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "cluster": cluster}


@app.delete("/api/clusters/{cluster_id}")
def api_delete_cluster(cluster_id: str):
    user = current_user.get()
    if not delete_cluster(user["tenant_id"], cluster_id):
        raise HTTPException(status_code=404, detail="Cluster não encontrado nesta empresa")
    return {"success": True}


@app.get("/api/status")
def api_status():

    summary = gate_summary()
    latest_report = None
    evaluation_id = summary.get("evaluation_id")

    report = load_latest_report()

    if report:
        latest_report = summarize_report_for_api(report)
        evaluation_id = report.get("evaluation_id", evaluation_id)

    provider = current_cluster_provider.get() or KUBERNETES_PROVIDER
    user = current_user.get() or {}
    return {
        "cluster": current_cluster_name.get() or CLUSTER,
        "provider": provider,
        "region": REGION if provider == "gke" else None,
        "project": PROJECT if provider == "gke" else None,
        "company_name": user.get("company_name"),
        "kubeconfig_configured": bool(KUBECONFIG or current_cluster_id.get()),
        "gate": summary,
        "evaluation_id": evaluation_id,
        "require_approval": REQUIRE_APPROVAL,
        "auto_execute": AUTO_EXECUTE,
        "latest_report": latest_report,
    }


@app.get("/api/cluster")
def api_cluster():
    if not current_cluster_id.get():
        raise HTTPException(status_code=409, detail="Cadastre ou selecione um cluster")
    try:
        overview = get_cluster_overview()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Falha ao acessar o cluster: {exc}") from exc

    return {
        **overview,
        "provider": current_cluster_provider.get() or KUBERNETES_PROVIDER,
    }


@app.get("/api/cluster/pods")
def api_cluster_pods(namespace: str | None = None):
    if not current_cluster_id.get():
        raise HTTPException(status_code=409, detail="Cadastre ou selecione um cluster")
    try:
        pods = get_cluster_pods()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Falha ao consultar pods: {exc}") from exc

    namespaces = sorted({pod["namespace"] for pod in pods})
    filtered_pods = [
        pod for pod in pods
        if not namespace or pod["namespace"] == namespace
    ]
    return {
        "pods": filtered_pods,
        "namespaces": namespaces,
        "total": len(filtered_pods),
        "namespace": namespace,
    }


@app.get("/api/cluster/pod-logs")
def api_cluster_pod_logs(
    namespace: str,
    pod: str,
    container: str | None = None,
    previous: bool = False,
):
    if not current_cluster_id.get():
        raise HTTPException(status_code=409, detail="Cadastre ou selecione um cluster")
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", namespace) or len(namespace) > 63:
        raise HTTPException(status_code=422, detail="Namespace Kubernetes inválido")
    if (
        len(pod) > 253
        or not re.fullmatch(r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?", pod)
    ):
        raise HTTPException(status_code=422, detail="Nome de pod Kubernetes inválido")
    if container and (
        len(container) > 63
        or not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", container)
    ):
        raise HTTPException(status_code=422, detail="Nome de container Kubernetes inválido")

    try:
        logs = get_cluster_pod_logs(namespace, pod, container, previous)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Falha ao consultar logs: {exc}") from exc

    return {
        "namespace": namespace,
        "pod": pod,
        "container": container,
        "previous": previous,
        "logs": logs,
        "truncated": len(logs.encode("utf-8")) >= 262_144,
    }


@app.get("/api/stability")
def api_stability():

    report = load_latest_report()

    if report is None:
        raise HTTPException(status_code=404, detail="Nenhuma avaliação encontrada")

    stability = ensure_stability(report)

    if stability is None:
        raise HTTPException(status_code=404, detail="Dados de capacity indisponíveis")

    return {
        "evaluation_id": report.get("evaluation_id"),
        "created_at": report.get("created_at"),
        "stability": stability,
    }


@app.get("/api/recommendations")
def api_recommendations(status: str | None = None):

    evaluation_id, items = list_by_status(status)

    return {
        "evaluation_id": evaluation_id,
        "items": items,
    }


@app.get("/api/reports")
def api_reports():

    return {"reports": list_reports()}


@app.get("/api/reports/{evaluation_id}")
def api_report(evaluation_id: str):

    try:
        report = load_report(evaluation_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Relatório não encontrado") from exc

    return summarize_report_for_api(report)


@app.get("/api/audit")
def api_audit(limit: int = 50):

    return {"entries": load_audit(limit=limit)}


@app.post("/api/evaluate")
def api_evaluate():

    if not current_cluster_id.get():
        raise HTTPException(status_code=409, detail="Cadastre ou selecione um cluster")

    try:
        report = run_evaluation(source="dashboard")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Falha na avaliação: {exc}",
        ) from exc

    return {
        "success": True,
        "report": summarize_report_for_api(report),
    }


@app.post("/api/recommendations/{rec_id}/approve")
def api_approve(rec_id: str, body: ApproveRequest):

    result = approve(rec_id, body.by)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/recommendations/{rec_id}/reject")
def api_reject(rec_id: str, body: RejectRequest):

    result = reject(rec_id, body.by, body.reason)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/recommendations/{rec_id}/execute")
def api_execute(rec_id: str, body: ExecuteRequest):

    item, _ = get_recommendation(rec_id)

    if item is None:
        raise HTTPException(status_code=404, detail="Recomendação não encontrada")

    allowed, reason = can_execute(
        item,
        force=body.force or body.dry_run,
    )

    if not allowed and not body.dry_run:
        raise HTTPException(status_code=400, detail=reason)

    result = execute_operation(item["operation"], dry_run=body.dry_run)

    if not body.dry_run:
        mark_executed(rec_id, result)

    return {
        "success": result.get("success", False),
        "dry_run": body.dry_run,
        "result": result,
        "item": get_recommendation(rec_id)[0],
    }


@app.get("/api/executive-report")
def api_executive_report_latest():

    report = load_latest_report()

    if report is None:
        raise HTTPException(status_code=404, detail="Nenhuma avaliação encontrada")

    return build_executive_report(summarize_report_for_api(report))


@app.get("/api/executive-report/{evaluation_id}")
def api_executive_report(evaluation_id: str):

    try:
        report = load_report(evaluation_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Relatório não encontrado") from exc

    return build_executive_report(summarize_report_for_api(report))


@app.get("/relatorio")
def relatorio_page():

    return FileResponse(STATIC_DIR / "relatorio.html")


@app.get("/")
def index():

    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
