import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from accounts import store as account_store
from assistant import engine, tools
from assistant.redact import redact

MI = 1024 ** 2


def _pods():
    return {"items": [
        {"metadata": {"namespace": "app", "name": "api-1", "creationTimestamp": "2026-10-20T10:00:00Z"},
         "spec": {"nodeName": "n1", "containers": [{"name": "api", "image": "api:1",
                                                    "resources": {"limits": {"memory": "128Mi"}}}]},
         "status": {"phase": "Running", "containerStatuses": [
             {"name": "api", "ready": False, "restartCount": 7, "state": {"waiting": {"reason": "CrashLoopBackOff"}},
              "lastState": {"terminated": {"reason": "OOMKilled", "exitCode": 137}}}]}},
        {"metadata": {"namespace": "app", "name": "web-1", "creationTimestamp": "2026-10-20T10:00:00Z"},
         "spec": {"nodeName": "n1", "containers": [{"name": "web"}]},
         "status": {"phase": "Running", "containerStatuses": [{"name": "web", "ready": True, "restartCount": 0,
                                                              "state": {"running": {}}}]}},
    ]}


def _events():
    return {"items": [{"type": "Warning", "reason": "BackOff", "message": "Back-off restarting container",
                       "count": 30, "involvedObject": {"namespace": "app", "name": "api-1"}}]}


class RedactTest(unittest.TestCase):
    def test_masks_secrets(self):
        text = ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456 password=SuperSecreta "
                "user eu@empresa.com.br from 10.0.3.7 key AKIAABCDEFGHIJKLMNOP "
                "postgres://admin:segredo@db:5432/x cag_" + "a" * 30)
        out = redact(text)
        for secret in ("abcdefghijklmnopqrstuvwxyz123456", "SuperSecreta", "eu@empresa.com.br",
                       "10.0.3.7", "AKIAABCDEFGHIJKLMNOP", "segredo", "cag_aaaa"):
            self.assertNotIn(secret, out)


class ToolsTest(unittest.TestCase):
    def test_problem_pods_and_details(self):
        with patch.object(tools, "_pods_and_events", return_value=(_pods(), _events())):
            problems = json.loads(tools.run_tool("pods_com_problema", {}, {"role": "leitor"}))
            self.assertEqual([p["name"] for p in problems["pods"]], ["api-1"])
            details = json.loads(tools.run_tool("detalhes_pod", {"namespace": "app", "pod": "api-1"}, {}))
            self.assertEqual(details["containers"][0]["ultimo_estado"]["terminated"]["reason"], "OOMKilled")
            self.assertEqual(details["eventos"][0]["motivo"], "BackOff")

    def test_logs_require_operator(self):
        out = json.loads(tools.run_tool("logs_pod", {"namespace": "app", "pod": "api-1"}, {"role": "leitor"}))
        self.assertIn("erro", out)

    def test_unknown_tool(self):
        self.assertIn("desconhecida", tools.run_tool("apagar_tudo", {}, {}))


class EngineTest(unittest.TestCase):
    def test_anthropic_tool_loop(self):
        calls = []

        def transport(url, headers, body):
            calls.append(body)
            if len(calls) == 1:
                return {"content": [{"type": "tool_use", "id": "t1", "name": "pods_com_problema", "input": {}}]}
            self.assertEqual(body["messages"][-1]["content"][0]["type"], "tool_result")
            return {"content": [{"type": "text", "text": "Diagnóstico: OOMKilled em app/api-1."}]}

        with patch.object(tools, "_pods_and_events", return_value=(_pods(), _events())):
            answer, used = engine.ask({"provider": "anthropic", "model": "m", "api_key": "k"},
                                      [{"role": "user", "content": "o que está quebrado?"}], {"role": "admin"},
                                      transport=transport)
        self.assertIn("OOMKilled", answer)
        self.assertEqual(used, ["pods_com_problema"])
        self.assertTrue(all(t["name"] != "aplicar" for t in calls[0]["tools"]))

    def test_openai_compatible_loop(self):
        calls = []

        def transport(url, headers, body):
            calls.append((url, headers))
            if len(calls) == 1:
                return {"choices": [{"message": {"content": None, "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "detalhes_pod", "arguments": json.dumps({"namespace": "app", "pod": "api-1"})}}]}}]}
            return {"choices": [{"message": {"content": "Aumente o limit de memória."}}]}

        with patch.object(tools, "_pods_and_events", return_value=(_pods(), _events())):
            answer, used = engine.ask({"provider": "openai", "model": "llama3.1", "base_url": "http://ollama:11434/v1"},
                                      [{"role": "user", "content": "por que api-1 reinicia?"}], {}, transport=transport)
        self.assertEqual(calls[0][0], "http://ollama:11434/v1/chat/completions")
        self.assertEqual(used, ["detalhes_pod"])
        self.assertIn("memória", answer)

    def test_question_is_redacted_before_sending(self):
        seen = {}

        def transport(url, headers, body):
            seen["body"] = json.dumps(body)
            return {"content": [{"type": "text", "text": "ok"}]}

        engine.ask({"provider": "anthropic", "model": "m", "api_key": "k"},
                   [{"role": "user", "content": "senha=Abc123456 do banco"}], {}, transport=transport)
        self.assertNotIn("Abc123456", seen["body"])


class ConfigStoreTest(unittest.TestCase):
    def test_key_encrypted_and_kept(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(account_store, "DB_PATH", Path(tmp) / "a.sqlite3"):
            admin = account_store.register_account("E", "A", "a@x.com", "senha-muito-forte-1")
            account_store.save_assistant_config(admin["tenant_id"], "anthropic", "m", api_key="sk-segredo-123")
            account_store.save_assistant_config(admin["tenant_id"], "anthropic", "m2")  # mantém a chave
            cfg = account_store.get_assistant_config(admin["tenant_id"], include_key=True)
            self.assertEqual((cfg["model"], cfg["api_key"]), ("m2", "sk-segredo-123"))
            self.assertNotIn("api_key", account_store.get_assistant_config(admin["tenant_id"]))
            raw = (Path(tmp) / "a.sqlite3").read_bytes()
            self.assertNotIn(b"sk-segredo-123", raw)
            self.assertEqual(account_store.increment_assistant_usage(admin["tenant_id"]), 1)
            self.assertEqual(account_store.increment_assistant_usage(admin["tenant_id"]), 2)


class TessTest(unittest.TestCase):
    def test_tess_sem_ferramentas_envia_contexto_e_headers(self):
        from assistant import engine

        run_tool = patch.object(engine, "run_tool", lambda name, args, ctx: '{"pods": [{"namespace": "loja", "name": "api-1"}]}')
        run_tool.start()
        self.addCleanup(run_tool.stop)
        seen = {}

        def transport(url, headers, body):
            seen.update(url=url, headers=headers, body=body)
            return {"choices": [{"message": {"content": "Diagnóstico: deploy quebrado"}}]}

        config = {"provider": "tess", "model": "tess-5", "api_key": "k", "base_url": "123", "api_version": "77"}
        answer, used = engine.ask(config, [{"role": "user", "content": "por que o pod cai?"}], {}, transport)
        assert answer == "Diagnóstico: deploy quebrado"
        assert seen["url"] == "https://api.tess.im/agents/123/openai/chat/completions"
        assert seen["headers"] == {"Authorization": "Bearer k", "x-workspace-id": "77"}
        assert seen["body"]["tools"] == "no-tools" and "DADOS DO CLUSTER" in seen["body"]["messages"][-1]["content"]
        assert seen["body"]["messages"][-1]["content"].endswith("por que o pod cai?")
        assert "detalhes_pod" in used


if __name__ == "__main__":
    unittest.main()
