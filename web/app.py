import hashlib
import os
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from accounts.middleware import TenantAuthenticationMiddleware
from accounts.store import (
    DuplicateAccountError,
    DuplicateClusterError,
    InviteError,
    LastAdminError,
    accept_invite,
    authenticate,
    create_invite,
    delete_user,
    list_invites,
    list_users,
    set_user_role,
    count_tenants,
    create_agent_cluster,
    ensure_incluster_cluster,
    create_cluster,
    find_cluster_by_ingest_token,
    rotate_ingest_token,
    touch_agent_cluster,
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
from approval.store import append_audit, list_reports, load_audit, load_latest_report, load_report
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
    current_cluster_mode,
    current_cluster_name,
    current_tenant_id,
    current_cluster_provider,
    current_user,
)

STATIC_DIR = Path(__file__).parent / "static"


class ApproveRequest(BaseModel):
    # Mantido por compatibilidade; o aprovador real é sempre o usuário autenticado.
    by: str | None = None


class RejectRequest(BaseModel):
    by: str | None = None
    reason: str = Field(default="", max_length=1000)


class ExecuteRequest(BaseModel):
    dry_run: bool = False
    # Execução real exige confirmação explícita do cliente (force=true).
    force: bool = False


def _actor():
    user = current_user.get() or {}
    name = user.get("full_name") or "desconhecido"
    email = user.get("email")
    return f"{name} ({email})" if email else name


class RegisterRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class InviteRequest(BaseModel):
    role: str = Field(pattern="^(leitor|operador|admin)$")
    email: str | None = Field(default=None, max_length=254)


class RoleRequest(BaseModel):
    role: str = Field(pattern="^(leitor|operador|admin)$")


class AgentClusterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class ClusterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    kubeconfig: str = Field(min_length=1, max_length=2_000_000)


app = FastAPI(
    title="Capacity Agent Dashboard",
    description="Dashboard DevOps multiempresa para clusters Kubernetes",
    version="1.0.0",
)

app.add_middleware(TenantAuthenticationMiddleware)


@app.middleware("http")
async def disable_dashboard_asset_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/static/app.js", "/static/styles.css"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.on_event("startup")
def startup():
    initialize_database()
    from engine import sampler
    sampler.start()


@app.on_event("shutdown")
def shutdown():
    from engine import sampler
    sampler.stop()


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


SINGLE_TENANT = os.getenv("CAPACITY_AGENT_SINGLE_TENANT", "false").lower() == "true"
INCLUSTER = os.getenv("CAPACITY_AGENT_INCLUSTER", "false").lower() == "true"
INCLUSTER_NAME = os.getenv("CAPACITY_AGENT_INCLUSTER_NAME", "Este cluster")


def _ensure_incluster(user):
    if INCLUSTER and user and user.get("tenant_id"):
        ensure_incluster_cluster(user["tenant_id"], INCLUSTER_NAME)


@app.get("/healthz")
def healthz():
    from engine import sampler

    return {"status": "ok", "single_tenant": SINGLE_TENANT, "incluster": INCLUSTER,
            "sampler_minutes": sampler.SAMPLE_MINUTES}


@app.get("/api/auth/setup")
def api_auth_setup():
    """Informa à tela de login se o cadastro inicial ainda está aberto."""
    return {"registration_open": not SINGLE_TENANT or count_tenants() == 0,
            "single_tenant": SINGLE_TENANT}


@app.post("/api/auth/register")
def api_register(body: RegisterRequest, response: Response):
    if SINGLE_TENANT and count_tenants() > 0:
        raise HTTPException(
            status_code=403,
            detail="Instalação de empresa única: peça um convite ao administrador",
        )
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Informe um e-mail válido")
    try:
        user = register_account(body.company_name, body.full_name, email, body.password)
    except DuplicateAccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _ensure_incluster(user)
    token, _ = create_session(user["id"])
    _set_session_cookie(response, token)
    return user


LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60
_login_failures = {}


def _login_key(request, email):
    client = request.client.host if request.client else "?"
    return f"{client}|{email.strip().lower()}"


def _recent_failures(key):
    now = time.monotonic()
    attempts = [t for t in _login_failures.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    _login_failures[key] = attempts
    return attempts


@app.post("/api/auth/login")
def api_login(body: LoginRequest, request: Request, response: Response):
    key = _login_key(request, body.email)
    if len(_recent_failures(key)) >= LOGIN_MAX_FAILURES:
        raise HTTPException(
            status_code=429,
            detail="Muitas tentativas de login. Aguarde 15 minutos e tente novamente.",
        )
    user = authenticate(body.email, body.password)
    if not user:
        _login_failures.setdefault(key, []).append(time.monotonic())
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos")
    _login_failures.pop(key, None)
    _ensure_incluster(user)
    token, _ = create_session(user["id"])
    _set_session_cookie(response, token)
    return user


@app.post("/api/auth/accept-invite")
def api_accept_invite(body: AcceptInviteRequest, response: Response):
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Informe um e-mail válido")
    try:
        user = accept_invite(body.token, body.full_name, email, body.password)
    except DuplicateAccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InviteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token, _ = create_session(user["id"])
    _set_session_cookie(response, token)
    return user


@app.get("/api/users")
def api_users():
    user = current_user.get()
    return {
        "users": list_users(user["tenant_id"]),
        "invites": list_invites(user["tenant_id"]),
        "me": user["id"],
    }


@app.post("/api/invites")
def api_create_invite(body: InviteRequest, request: Request):
    user = current_user.get()
    try:
        token, expires_at = create_invite(user["tenant_id"], body.role, _actor(), body.email)
    except InviteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    append_audit("invite", {"role": body.role, "email": body.email, "by": _actor()})
    base = str(request.base_url).rstrip("/")
    return {"link": f"{base}/?invite={token}", "expires_at": expires_at, "role": body.role}


@app.patch("/api/users/{user_id}")
def api_set_role(user_id: str, body: RoleRequest):
    user = current_user.get()
    try:
        changed = set_user_role(user["tenant_id"], user_id, body.role)
    except LastAdminError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(status_code=404, detail="Usuário não encontrado nesta empresa")
    append_audit("role_change", {"user_id": user_id, "role": body.role, "by": _actor()})
    return {"success": True}


@app.delete("/api/users/{user_id}")
def api_delete_user(user_id: str):
    user = current_user.get()
    if user_id == user["id"]:
        raise HTTPException(status_code=409, detail="Você não pode remover a própria conta")
    try:
        removed = delete_user(user["tenant_id"], user_id)
    except LastAdminError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Usuário não encontrado nesta empresa")
    append_audit("user_removed", {"user_id": user_id, "by": _actor()})
    return {"success": True}


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
        "role": user.get("role", "admin"),
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


def _collector_instructions(request, token):
    panel = os.getenv("CAPACITY_AGENT_PUBLIC_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
    image = os.getenv("CAPACITY_AGENT_COLLECTOR_IMAGE", "ghcr.io/<owner>/k8s-capacity-agent")
    chart = os.getenv("CAPACITY_AGENT_COLLECTOR_CHART", "./charts/capacity-collector")
    return {
        "panel_url": panel,
        "helm": (
            f"helm upgrade --install capacity-collector {chart} \\\n"
            f"  --namespace capacity-agent --create-namespace \\\n"
            f"  --set panelUrl={panel} \\\n"
            f"  --set image.repository={image} \\\n"
            f"  --set ingestToken={token}"
        ),
        "local_test": (
            f"CAPACITY_AGENT_PANEL_URL={panel} CAPACITY_AGENT_INGEST_TOKEN={token} "
            "python3 agent.py collect --once"
        ),
    }


@app.post("/api/clusters/agent")
def api_add_agent_cluster(body: AgentClusterRequest, request: Request):
    user = current_user.get()
    try:
        cluster, token = create_agent_cluster(user["tenant_id"], body.name)
    except DuplicateClusterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    append_audit("agent_cluster_created", {"cluster": cluster["name"], "by": _actor()})
    return {"success": True, "cluster": cluster, "token": token,
            "instructions": _collector_instructions(request, token)}


@app.post("/api/clusters/{cluster_id}/rotate-token")
def api_rotate_token(cluster_id: str, request: Request):
    user = current_user.get()
    token = rotate_ingest_token(user["tenant_id"], cluster_id)
    if not token:
        raise HTTPException(status_code=404, detail="Cluster via agente não encontrado nesta empresa")
    append_audit("agent_token_rotated", {"cluster_id": cluster_id, "by": _actor()})
    return {"success": True, "token": token, "instructions": _collector_instructions(request, token)}


MAX_INGEST_COMPRESSED = 20 * 1024 * 1024
MIN_INGEST_INTERVAL_SECONDS = 60


@app.post("/api/ingest")
async def api_ingest(request: Request):
    import gzip
    import json as jsonlib
    import zlib
    from datetime import datetime, timezone

    from analyzers.capacity import analyze_capacity
    from analyzers.workloads import collect_workloads
    from approval.store import save_cluster_snapshot, save_metric_samples, save_workload_samples
    from collectors.snapshot import MAX_SNAPSHOT_BYTES, snapshot_to_data, validate_snapshot

    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    cluster = find_cluster_by_ingest_token(token)
    if not cluster:
        raise HTTPException(status_code=401, detail="Token de ingestão inválido ou revogado")

    if cluster.get("last_seen_at"):
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(cluster["last_seen_at"])).total_seconds()
        if elapsed < MIN_INGEST_INTERVAL_SECONDS:
            raise HTTPException(status_code=429, detail="Envio muito frequente; aguarde 1 minuto")

    length = int(request.headers.get("content-length") or 0)
    if length > MAX_INGEST_COMPRESSED:
        raise HTTPException(status_code=413, detail="Snapshot muito grande")
    raw = await request.body()
    if len(raw) > MAX_INGEST_COMPRESSED:
        raise HTTPException(status_code=413, detail="Snapshot muito grande")
    try:
        if request.headers.get("content-encoding", "").lower() == "gzip":
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            raw = decompressor.decompress(raw, MAX_SNAPSHOT_BYTES + 1)
            if len(raw) > MAX_SNAPSHOT_BYTES or decompressor.unconsumed_tail:
                raise HTTPException(status_code=413, detail="Snapshot descomprimido muito grande")
        snapshot = jsonlib.loads(raw)
        validate_snapshot(snapshot)
    except HTTPException:
        raise
    except (ValueError, zlib.error, gzip.BadGzipFile) as exc:
        raise HTTPException(status_code=422, detail=f"Snapshot inválido: {exc}") from exc

    tokens = [
        (current_tenant_id, current_tenant_id.set(cluster["tenant_id"])),
        (current_cluster_id, current_cluster_id.set(cluster["id"])),
        (current_cluster_name, current_cluster_name.set(cluster["name"])),
        (current_cluster_mode, current_cluster_mode.set("agent")),
    ]
    try:
        save_cluster_snapshot(snapshot)
        data = snapshot_to_data(snapshot)
        if data["node_metrics"]:
            save_metric_samples(analyze_capacity(data["nodes"], data["pods"], data["node_metrics"], data["pod_metrics"]))
            samples, _ = collect_workloads(data["pods"], data["container_metrics"])
            if samples:
                save_workload_samples(samples)
        touch_agent_cluster(cluster["id"], len(data["nodes"]["items"]))
    finally:
        for var, value in reversed(tokens):
            var.reset(value)

    return {"success": True, "detail": "snapshot recebido"}


def _agent_snapshot_or_409():
    from approval.store import load_cluster_snapshot

    snapshot = load_cluster_snapshot()
    if not snapshot:
        raise HTTPException(status_code=409, detail="O coletor ainda não enviou dados deste cluster")
    return snapshot


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
        "show_roadmap": os.getenv("CAPACITY_AGENT_SHOW_ROADMAP", "false").lower() == "true"
        and (user.get("role") == "admin"),
    }


@app.get("/api/cluster")
def api_cluster():
    if not current_cluster_id.get():
        raise HTTPException(status_code=409, detail="Cadastre ou selecione um cluster")
    if current_cluster_mode.get() == "agent":
        from collectors.kubernetes import parse_nodes_overview

        snapshot = _agent_snapshot_or_409()
        return {
            "context": f"agente · último envio {snapshot['_received_at']}",
            "nodes": parse_nodes_overview(snapshot["nodes"]),
            "kubeconfig_configured": False,
            "provider": "kubernetes",
            "mode": "agent",
            "last_seen_at": snapshot["_received_at"],
        }
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
        if current_cluster_mode.get() == "agent":
            from collectors.kubernetes import parse_cluster_pods

            pods = parse_cluster_pods(_agent_snapshot_or_409()["pods"])
        else:
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
    if current_cluster_mode.get() == "agent":
        raise HTTPException(
            status_code=409,
            detail="Logs não ficam disponíveis no modo agente (somente leitura, sem acesso direto à API)",
        )
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
        report = run_evaluation(source="dashboard", actor=_actor())
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

    result = approve(rec_id, _actor())

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/recommendations/{rec_id}/reject")
def api_reject(rec_id: str, body: RejectRequest):

    result = reject(rec_id, _actor(), body.reason)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/recommendations/{rec_id}/execute")
def api_execute(rec_id: str, body: ExecuteRequest):

    if not body.dry_run and (current_user.get() or {}).get("role") != "admin":
        raise HTTPException(status_code=403, detail="Execução real requer papel 'admin'")

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
        mark_executed(rec_id, result, executed_by=_actor())

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
    app_script = STATIC_DIR / "app.js"
    stylesheet = STATIC_DIR / "styles.css"
    version_hash = hashlib.sha256(
        app_script.read_bytes() + stylesheet.read_bytes()
    ).hexdigest()[:12]
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        "/static/styles.css",
        f"/static/styles.css?v={version_hash}",
    ).replace(
        "/static/app.js",
        f"/static/app.js?v={version_hash}",
    )
    return HTMLResponse(html)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
