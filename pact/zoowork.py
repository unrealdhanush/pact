"""Minimal async client for the ZooWork Platform REST API.

ZooWork only publishes a TypeScript SDK; routes and bodies here mirror
@zoowork-ai/sdk src/client.ts (v0.9.x).
"""
import json
import os
import uuid
from pathlib import Path

import httpx

DEFAULT_BASE_URL = "https://clawapi.ecap.gsmo.ai/service/v1"
STATE_FILE = Path(__file__).resolve().parent.parent / ".local" / "zoowork.json"


class ZooWorkError(RuntimeError):
    pass


class ZooWorkClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 30):
        key = api_key or os.environ.get("ZOOWORK_API_KEY")
        if not key:
            raise ZooWorkError("ZOOWORK_API_KEY is not set")
        self._http = httpx.AsyncClient(
            base_url=base_url or os.environ.get("ZOOWORK_BASE_URL") or DEFAULT_BASE_URL,
            headers={"Authorization": f"Bearer {key}", "User-Agent": "pact/0.1"},
            timeout=timeout,
        )

    async def _req(self, method: str, path: str, body: dict | None = None,
                   idempotency_key: str | None = None) -> dict:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        res = await self._http.request(method, path, json=body, headers=headers)
        if res.status_code >= 400:
            raise ZooWorkError(f"{method} {path} → {res.status_code}: {res.text[:300]}")
        return res.json() if res.content else {}

    async def aclose(self) -> None:
        await self._http.aclose()

    # agents
    async def create_agent(self, resource: dict, idempotency_key: str) -> dict:
        return await self._req("POST", "/agents", {"resource": {**resource, "onboarding": False}},
                               idempotency_key)

    async def get_agent(self, agent_id: str) -> dict:
        return await self._req("GET", f"/agents/{agent_id}")

    async def update_agent(self, agent_id: str, resource: dict) -> dict:
        return await self._req("PUT", f"/agents/{agent_id}", resource)

    async def start_agent(self, agent_id: str) -> dict:
        return await self._req("POST", f"/agents/{agent_id}/start")

    # sessions
    async def create_session(self, agent_id: str, metadata: dict) -> str:
        data = await self._req("POST", f"/agents/{agent_id}/sessions", {"metadata": metadata},
                               idempotency_key=f"pact:session:{uuid.uuid4().hex}")
        return data["session_id"]

    async def send_message(self, agent_id: str, session_id: str, text: str) -> dict:
        return await self._req("POST", f"/agents/{agent_id}/sessions/{session_id}/events", {
            "events": [{"type": "user.message", "content": text,
                        "idempotency_key": f"pact:msg:{uuid.uuid4().hex}"}],
        })

    # custom tools
    async def pending_tool_calls(self, agent_id: str, session_id: str) -> list[dict]:
        data = await self._req(
            "GET", f"/agents/{agent_id}/custom_tool_calls?status=pending&session_id={session_id}")
        return data.get("custom_tool_calls", [])

    async def resolve_tool_call(self, agent_id: str, call_id: str, result, is_error: bool = False) -> dict:
        return await self._req("POST", f"/agents/{agent_id}/custom_tool_calls/{call_id}/result", {
            "content": [{"type": "json", "value": result}],
            "isError": is_error,
            "resolvedBy": "pact-server",
        })


def load_agent_id() -> str | None:
    if os.environ.get("ZOOWORK_AGENT_ID"):
        return os.environ["ZOOWORK_AGENT_ID"]
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text()).get("agent_id")
    return None
