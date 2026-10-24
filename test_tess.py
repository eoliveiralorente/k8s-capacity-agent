import os

import httpx
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("TESS_API_KEY")
workspace_id = os.getenv("TESS_WORKSPACE_ID")
base_url = os.getenv("TESS_BASE_URL", "https://api.tess.im").rstrip("/")

if not token or not workspace_id:
    raise SystemExit("Configure TESS_API_KEY e TESS_WORKSPACE_ID no .env")

headers = {
    "Authorization": f"Bearer {token}",
    "x-workspace-id": workspace_id,
}

try:
    with httpx.Client(timeout=20.0) as client:
        response = client.get(f"{base_url}/agents", headers=headers)
        print("Status HTTP:", response.status_code)
        response.raise_for_status()

        data = response.json()
        for agent in data.get("data", []):
            print(f"ID: {agent['id']} | Agente: {agent['title']}")

except httpx.HTTPStatusError as exc:
    print(f"API retornou HTTP {exc.response.status_code}.")
except httpx.RequestError as exc:
    print(f"Falha de conexão: {type(exc).__name__}")