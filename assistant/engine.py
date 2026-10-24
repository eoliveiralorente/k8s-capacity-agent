"""Assistente de triagem (SRE/DevOps) com ferramentas somente leitura.

Provedores suportados (chave de API do próprio cliente):
  - anthropic : API Messages da Anthropic (Claude)
  - openai    : qualquer API compatível com OpenAI Chat Completions
                (OpenAI, Azure OpenAI via base_url, Ollama em http://<host>:11434/v1)
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
TIMEOUT = 90

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


def _post(url, headers, body):
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **headers},
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
    raise AssistantError("Provedor não suportado")
