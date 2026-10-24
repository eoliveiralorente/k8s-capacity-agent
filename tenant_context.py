from contextvars import ContextVar


current_tenant_id = ContextVar("current_tenant_id", default=None)
current_cluster_id = ContextVar("current_cluster_id", default=None)
current_cluster_provider = ContextVar("current_cluster_provider", default=None)
current_cluster_name = ContextVar("current_cluster_name", default=None)
current_user = ContextVar("current_user", default=None)
current_cluster_mode = ContextVar("current_cluster_mode", default=None)
