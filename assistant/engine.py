"""Assistente de triagem (SRE/DevOps) com ferramentas somente leitura.

Provedores suportados (chave de API do próprio cliente):
  - anthropic : API Messages da Anthropic (Claude)
  - openai    : qualquer API compatível com OpenAI Chat Completions
                (OpenAI, Azure OpenAI via base_url, Ollama em http://<host>:11434/v1)
  - tess      : Tess AI (endpoint OpenAI-compatível de um agente). A Tess não aceita
                function calling, então os dados do cluster são coletados antes e
                enviados como contexto (modo sem ferramentas).
"""
import json
import os
import ssl
import urllib.error
import urllib.request

from assistant.redact import redact
from assistant.tools import run_tool, tool_schemas

MAX_STEPS = 6
MAX_TOKENS = 1500
MAX_HISTORY = 10
TIMEOUT = int(os.getenv("CAPACITY_AGENT_AI_TIMEOUT", "240"))  # IA local em CPU é mais lenta

SYSTEM_PROMPT = """Você é o assistente de SRE do Capacity Agent, ajudando profissionais de DevOps/SRE
a diagnosticar clusters Kubernetes. Responda sempre em português do Brasil.

Regras:
- Baseie-se SOMENTE nos dados das ferramentas. Se faltar informação, diga o que falta e qual ferramenta usar.
- Cite as evidências (pod, evento, métrica, linha de log) que sustentam a conclusão.
- Estruture: Diagnóstico provável → Evidências → Próximos passos (comandos kubectl sugeridos, quando útil).
- Você NÃO executa nada no cluster. Nunca diga que aplicou uma mudança. Mudanças passam pelo fluxo
  de aprovação do painel ou pelo time.
- Dados sensíveis foram mascarados (ex.: [TOKEN], [IP]); não tente reconstruí-los.
- Seja objetivo; o usuário é técnico."""


class AssistantError(RuntimeError):
    pass


def _version():
    try:
        from version import VERSION
        return VERSION
    except Exception:
        return "1"


def _post(url, headers, body):
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        # User-Agent explícito: provedores atrás do Cloudflare (ex.: Tess) bloqueiam o
        # padrão "Python-urllib" com HTTP 403 "error code: 1010".
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": f"CapacityAgent/{_version()}", **headers},
    )
    context = ssl.create_default_context(cafile=os.getenv("CAPACITY_AGENT_CA_FILE") or None)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise AssistantError(f"Provedor de IA respondeu HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AssistantError(f"Não foi possível conectar ao provedor de IA: {exc.reason}") from exc


# ── Anthropic ────────────────────────────────────────────────

def _anthropic_loop(config, messages, ctx, transport):
    url = (config.get("base_url") or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
    headers = {"x-api-key": config["api_key"], "anthropic-version": "2023-06-01"}
    convo = [{"role": m["role"], "content": m["content"]} for m in messages]
    tools_used = []
    for _ in range(MAX_STEPS):
        data = transport(url, headers, {
            "model": config["model"], "max_tokens": MAX_TOKENS, "system": SYSTEM_PROMPT,
            "tools": tool_schemas(), "messages": convo,
        })
        content = data.get("content", [])
        calls = [b for b in content if b.get("type") == "tool_use"]
        if not calls:
            text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            return text, tools_used
        convo.append({"role": "assistant", "content": content})
        results = []
        for call in calls:
            tools_used.append(call["name"])
            results.append({"type": "tool_result", "tool_use_id": call["id"],
                            "content": run_tool(call["name"], call.get("input"), ctx)})
        convo.append({"role": "user", "content": results})
    return "Limite de passos atingido; reformule a pergunta de forma mais específica.", tools_used


# ── OpenAI-compatível ────────────────────────────────────────

def _openai_loop(config, messages, ctx, transport):
    base = (config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    url = base + "/chat/completions"
    if config.get("api_version"):  # Azure OpenAI
        url += f"?api-version={config['api_version']}"
    headers = {}
    if config.get("api_key"):
        if config.get("auth_header") == "api-key":
            headers["api-key"] = config["api_key"]
        else:
            headers["Authorization"] = f"Bearer {config['api_key']}"
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                               "parameters": t["input_schema"]}} for t in tool_schemas()]
    convo = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        {"role": m["role"], "content": m["content"]} for m in messages]
    tools_used = []
    for _ in range(MAX_STEPS):
        data = transport(url, headers, {"model": config["model"], "messages": convo, "tools": tools,
                                        "max_tokens": MAX_TOKENS})
        message = (data.get("choices") or [{}])[0].get("message", {})
        calls = message.get("tool_calls") or []
        if not calls:
            return (message.get("content") or "").strip(), tools_used
        convo.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            tools_used.append(name)
            convo.append({"role": "tool", "tool_call_id": call["id"], "content": run_tool(name, args, ctx)})
    return "Limite de passos atingido; reformule a pergunta de forma mais específica.", tools_used


# ── Tess AI (sem function calling) ───────────────────────────

TESS_CONTEXT_CHARS = 24000
TESS_PREFETCH = [("resumo_cluster", {}), ("pods_com_problema", {}),
                 ("recomendacoes", {"status": "pending"}), ("achados_scheduling", {})]


def tess_agent_base(value):
    """Aceita o ID do agente, a URL da API ou a URL do painel da Tess (…/add-or-update/<ID>?w=…)."""
    import re

    base = (value or "").strip().rstrip("/")
    if base.isdigit():
        return f"https://api.tess.im/agents/{base}/openai"
    if "tess.im" in base and "api.tess.im/agents/" not in base:
        found = re.findall(r"/(\d+)(?=[/?#]|$)", base.split("?")[0] + "/")
        if found:
            return f"https://api.tess.im/agents/{found[-1]}/openai"
    return base


def _tess_url(config):
    base = tess_agent_base(config.get("base_url"))
    if not base.startswith("http"):
        raise AssistantError("Informe o ID do agente Tess (ou a URL https://api.tess.im/agents/<ID>/openai)")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def _cluster_header():
    from tenant_context import current_cluster_mode, current_cluster_name

    modes = {"agent": "agente (dados enviados pelo agente instalado no cluster)",
             "incluster": "in-cluster (o painel roda dentro do cluster)"}
    mode = current_cluster_mode.get()
    return (f"CLUSTER ATIVO: {current_cluster_name.get() or 'desconhecido'} · modo "
            f"{modes.get(mode, mode or 'desconhecido')}. Todos os dados abaixo são deste cluster.")


def _tess_context(ctx):
    """Coleta os dados que o modelo pediria via ferramentas (somente leitura, mascarados)."""
    used, parts = [], []
    for name, args in TESS_PREFETCH:
        used.append(name)
        parts.append(f"### {name}\n{run_tool(name, args, ctx)}")
    try:
        pods = json.loads(run_tool("pods_com_problema", {}, ctx)).get("pods", [])[:3]
    except (ValueError, AttributeError):
        pods = []
    for pod in pods:
        if pod.get("namespace") and pod.get("name"):
            used.append("detalhes_pod")
            parts.append(f"### detalhes_pod {pod['namespace']}/{pod['name']}\n"
                         + run_tool("detalhes_pod", {"namespace": pod["namespace"], "pod": pod["name"]}, ctx))
    text = _cluster_header() + "\n\n" + "\n\n".join(parts)
    if len(text) > TESS_CONTEXT_CHARS:
        text = text[:TESS_CONTEXT_CHARS] + "… [truncado]"
    return text, used


def _tess_answer(data):
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        return (message.get("content") or choices[0].get("text") or "").strip()
    for key in ("output", "answer", "content"):
        if isinstance(data.get(key), str):
            return data[key].strip()
    raise AssistantError("Resposta da Tess em formato inesperado")


def _tess_call(config, messages, ctx, transport):
    if not config.get("api_key"):
        raise AssistantError("Informe a chave de API da Tess")
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    workspace = str(config.get("api_version") or "").strip()
    if workspace and not workspace.isdigit():
        raise AssistantError("O ID do workspace Tess é um número (não o e-mail). Veja na URL do workspace ou no perfil da API na Tess.")
    if workspace:
        headers["x-workspace-id"] = workspace
    context, used = _tess_context(ctx)
    system = (SYSTEM_PROMPT + "\n\nNeste modo você não chama ferramentas: os dados atuais do cluster "
              "já foram coletados (somente leitura) e estão abaixo. Se a pergunta exigir algo que não está "
              "aqui (ex.: logs), diga o que falta e o comando kubectl para obter.\n\n"
              "DADOS DO CLUSTER:\n" + context)
    # Agentes da Tess podem ignorar a mensagem "system" (usam as instruções do próprio agente).
    # Por isso as instruções e os dados vão também junto da pergunta atual.
    convo = [dict(m) for m in messages]
    convo[-1]["content"] = (system + "\n\n=== PERGUNTA DO USUÁRIO ===\n" + convo[-1]["content"])
    body = {"model": config["model"], "temperature": "0", "stream": False, "tools": "no-tools",
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + convo}
    if str(config.get("model", "")).strip().lower() in ("", "auto", "padrao", "padrão", "default"):
        body.pop("model")
    url = _tess_url(config)
    try:
        return _tess_answer(transport(url, headers, body)), used
    except AssistantError as exc:
        # Cada agente da Tess aceita uma lista própria de modelos/temperaturas. Se recusar,
        # tenta de novo sem os campos inválidos (o agente usa os valores dele).
        text = str(exc)
        if "422" not in text:
            raise
        dropped = [k for k in ("model", "temperature", "tools") if f'"{k}"' in text and k in body]
        if not dropped:
            raise
        for k in dropped:
            body.pop(k)
        try:
            return _tess_answer(transport(url, headers, body)), used
        except AssistantError as again:
            raise AssistantError(f"{again} — confira no agente da Tess quais modelos ele aceita "
                                 "(ou use \"auto\" no campo Modelo para o padrão do agente)") from again


def ask(config, history, ctx, transport=_post):
    """history: [{"role": "user"|"assistant", "content": str}], a última é a pergunta."""
    if not config or not config.get("model"):
        raise AssistantError("Assistente não configurado (provedor e modelo)")
    if config.get("provider") == "anthropic" and not config.get("api_key"):
        raise AssistantError("Informe a chave de API do provedor")
    messages = [
        {"role": m["role"], "content": redact(str(m["content"]))[:4000]}
        for m in history[-MAX_HISTORY:] if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    if not messages or messages[-1]["role"] != "user":
        raise AssistantError("Envie uma pergunta")
    if config.get("provider") == "anthropic":
        return _anthropic_loop(config, messages, ctx, transport)
    if config.get("provider") == "openai":
        return _openai_loop(config, messages, ctx, transport)
    if config.get("provider") == "tess":
        return _tess_call(config, messages, ctx, transport)
    raise AssistantError("Provedor não suportado")
