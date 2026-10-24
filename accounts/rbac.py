"""Controle de acesso por papel (RBAC).

leitor   : visualiza dashboards, relatórios e auditoria
operador : + avalia, aprova/rejeita, simula execução, lê logs de pods
admin    : + gerencia clusters e executa alterações reais
"""
import re

ROLE_RANK = {"leitor": 1, "operador": 2, "admin": 3}
ROLES = tuple(ROLE_RANK)

# (método, regex do caminho, papel mínimo). Primeira regra que casar vale.
POLICY = [
    ("POST", r"/api/auth/logout", "leitor"),
    ("POST", r"/api/clusters", "admin"),
    ("DELETE", r"/api/clusters/[^/]+", "admin"),
    ("POST", r"/api/evaluate", "operador"),
    ("POST", r"/api/recommendations/[^/]+/(approve|reject)", "operador"),
    ("POST", r"/api/recommendations/[^/]+/execute", "operador"),  # execução real exige admin no endpoint
    ("GET", r"/api/cluster/pod-logs", "operador"),  # logs podem conter dados sensíveis
    ("POST", r"/api/clusters/agent", "admin"),
    ("POST", r"/api/clusters/[^/]+/rotate-token", "admin"),
    ("GET", r"/api/users", "admin"),
    ("POST", r"/api/invites", "admin"),
    ("PATCH", r"/api/users/[^/]+", "admin"),
    ("DELETE", r"/api/users/[^/]+", "admin"),
]

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def required_role(method, path):
    method = method.upper()
    for rule_method, pattern, role in POLICY:
        if rule_method == method and re.fullmatch(pattern, path):
            return role
    # Leitura liberada para todos; qualquer outra escrita é negada por padrão.
    return "leitor" if method in SAFE_METHODS else "admin"


def has_role(user_role, needed):
    return ROLE_RANK.get(user_role or "", 0) >= ROLE_RANK[needed]
