from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from accounts.rbac import has_role, required_role
from accounts.store import get_cluster, get_session, list_clusters
from tenant_context import (
    current_cluster_id,
    current_cluster_name,
    current_cluster_provider,
    current_tenant_id,
    current_user,
)


PUBLIC_API_PATHS = {"/api/auth/register", "/api/auth/login"}
PUBLIC_PATHS = {"/", "/favicon.ico"}


class TenantAuthenticationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in PUBLIC_PATHS or path.startswith("/static/"):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        method = scope.get("method", "GET").upper()
        if method not in {"GET", "HEAD", "OPTIONS"}:
            origin = headers.get(b"origin")
            host = headers.get(b"host", b"").decode("latin-1").lower()
            if origin:
                origin_host = urlsplit(origin.decode("latin-1")).netloc.lower()
                if not host or origin_host != host:
                    response = JSONResponse({"detail": "Origem da requisição não autorizada"}, status_code=403)
                    await response(scope, receive, send)
                    return
            elif headers.get(b"sec-fetch-site") == b"cross-site":
                response = JSONResponse({"detail": "Origem da requisição não autorizada"}, status_code=403)
                await response(scope, receive, send)
                return

        if path in PUBLIC_API_PATHS:
            await self.app(scope, receive, send)
            return

        token = self._cookie_token(headers.get(b"cookie", b""))
        session = get_session(token)
        if not session:
            response = JSONResponse({"detail": "Autenticação necessária"}, status_code=401)
            await response(scope, receive, send)
            return

        needed = required_role(method, path)
        if not has_role(session.get("role"), needed):
            response = JSONResponse(
                {"detail": f"Permissão insuficiente: requer papel '{needed}'"},
                status_code=403,
            )
            await response(scope, receive, send)
            return

        tenant_id = session["tenant_id"]
        requested_cluster_id = headers.get(b"x-cluster-id", b"").decode("ascii", errors="ignore")
        cluster = get_cluster(tenant_id, requested_cluster_id) if requested_cluster_id else None
        if requested_cluster_id and not cluster:
            response = JSONResponse({"detail": "Cluster não encontrado nesta empresa"}, status_code=404)
            await response(scope, receive, send)
            return
        if not requested_cluster_id:
            clusters = list_clusters(tenant_id)
            if clusters:
                cluster = get_cluster(tenant_id, clusters[0]["id"])

        tokens = [
            (current_user, current_user.set(session)),
            (current_tenant_id, current_tenant_id.set(tenant_id)),
            (current_cluster_id, current_cluster_id.set(cluster["id"] if cluster else None)),
            (current_cluster_name, current_cluster_name.set(cluster["name"] if cluster else None)),
            (current_cluster_provider, current_cluster_provider.set("kubernetes" if cluster else None)),
        ]
        try:
            await self.app(scope, receive, send)
        finally:
            for context_var, context_token in reversed(tokens):
                context_var.reset(context_token)

    @staticmethod
    def _cookie_token(header):
        cookie = SimpleCookie()
        try:
            cookie.load(header.decode("latin-1"))
        except Exception:
            return None
        morsel = cookie.get("capacity_session")
        return morsel.value if morsel else None
