"""Cross-instance deal state for serverless hosting (Upstash Redis REST, e.g. Vercel's Upstash integration).

On a serverless platform each request may land on a different instance, but a deal runs as live
tasks inside one instance (its "owner"). The owner mirrors events + a snapshot into Redis and polls
a per-deal action queue; any other instance serves reads from Redis and queues the human's actions
(approve, accept, return, drop-off) for the owner. Intakes are persisted the same way.

Without Redis env vars everything stays in process (local dev), exactly as before.
"""
import asyncio
import json
import logging
import os
import uuid

import httpx

log = logging.getLogger("pact.shared")

INSTANCE = uuid.uuid4().hex[:8]
TTL_S = 3 * 3600
FLUSH_S = 0.3
POLL_S = 0.5


def _cfg() -> tuple[str, str] | None:
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    return (url.rstrip("/"), token) if url and token else None


def _redis_url() -> str | None:
    return os.environ.get("REDIS_URL") or os.environ.get("KV_URL")


def enabled() -> bool:
    return _cfg() is not None or _redis_url() is not None


_client = None


async def _redis_pipeline(cmds: list[list]) -> list:
    """Redis protocol (REDIS_URL), for providers without a REST API."""
    global _client
    import redis.asyncio as aioredis
    if _client is None:
        _client = aioredis.from_url(_redis_url(), decode_responses=True, socket_timeout=10)
    pipe = _client.pipeline(transaction=False)
    for c in cmds:
        pipe.execute_command(*[str(a) for a in c])
    return await pipe.execute()


async def pipeline(cmds: list[list]) -> list:
    cfg = _cfg()
    if not cmds:
        return []
    if not cfg:
        return await _redis_pipeline(cmds) if _redis_url() else []
    async with httpx.AsyncClient(timeout=10) as http:
        r = await http.post(f"{cfg[0]}/pipeline", headers={"Authorization": f"Bearer {cfg[1]}"},
                            json=[[str(a) for a in c] for c in cmds])
        r.raise_for_status()
        return [x.get("result") for x in r.json()]


async def cmd(*args):
    out = await pipeline([list(args)])
    return out[0] if out else None


# ---------------------------------------------------------------- owner side: mirror + action queue
def attach(deal, apply_action) -> None:
    """Mirror a locally running deal into Redis and apply queued actions to it."""
    if not enabled():
        return
    buf: list[dict] = []
    original = deal.emit

    def emit(type_: str, **data) -> None:
        original(type_, **data)
        buf.append(deal.events[-1])
    deal.emit = emit
    buf.extend(deal.events)  # anything emitted during setup

    async def flush_loop() -> None:
        while True:
            try:
                batch, buf[:] = list(buf), []
                cmds = [["SET", f"pact:owner:{deal.id}", INSTANCE, "EX", TTL_S]]
                if batch:
                    cmds.append(["RPUSH", f"pact:ev:{deal.id}", *[json.dumps(e, default=str) for e in batch]])
                    cmds.append(["EXPIRE", f"pact:ev:{deal.id}", TTL_S])
                    cmds.append(["SET", f"pact:snap:{deal.id}", json.dumps(deal.snapshot(), default=str), "EX", TTL_S])
                await pipeline(cmds)
            except Exception as e:  # noqa: BLE001 - keep mirroring through transient errors
                log.warning("mirror flush failed: %s", e)
            await asyncio.sleep(FLUSH_S)

    async def action_loop() -> None:
        while True:
            try:
                raw = await cmd("LPOP", f"pact:act:{deal.id}")
                if raw:
                    a = json.loads(raw)
                    await apply_action(deal, a)
                    continue
            except Exception as e:  # noqa: BLE001
                log.warning("queued action failed: %s", e)
            await asyncio.sleep(POLL_S)

    deal._shared_tasks = [asyncio.create_task(flush_loop()), asyncio.create_task(action_loop())]


# ---------------------------------------------------------------- any instance: reads + queued actions
async def snapshot(deal_id: str) -> dict | None:
    raw = await cmd("GET", f"pact:snap:{deal_id}")
    if not raw:
        return None
    snap = json.loads(raw)
    events = await cmd("LRANGE", f"pact:ev:{deal_id}", 0, -1) or []
    return {**snap, "events": [json.loads(e) for e in events]}


async def events_from(deal_id: str, start: int) -> list[dict]:
    raw = await cmd("LRANGE", f"pact:ev:{deal_id}", start, -1) or []
    return [json.loads(e) for e in raw]


async def exists(deal_id: str) -> bool:
    return bool(await cmd("EXISTS", f"pact:snap:{deal_id}"))


async def queue_action(deal_id: str, action: str, **data) -> None:
    await pipeline([["RPUSH", f"pact:act:{deal_id}", json.dumps({"action": action, **data})],
                    ["EXPIRE", f"pact:act:{deal_id}", TTL_S]])


# ---------------------------------------------------------------- intakes (multi-turn chat state)
async def save_intake(intake_id: str, data: dict) -> None:
    if enabled():
        await cmd("SET", f"pact:intake:{intake_id}", json.dumps(data, default=str), "EX", TTL_S)


async def load_intake(intake_id: str) -> dict | None:
    if not enabled():
        return None
    raw = await cmd("GET", f"pact:intake:{intake_id}")
    return json.loads(raw) if raw else None


def status() -> dict:
    seen = sorted(k for k in os.environ if any(t in k for t in ("REDIS", "KV_", "UPSTASH")))  # names only
    if enabled():
        via = "REST" if _cfg() else "redis://"
        return {"name": "State", "mode": "live", "detail": f"Shared deal state in Redis via {via} (instance {INSTANCE})",
                "env": seen}
    return {"name": "State", "mode": "fallback",
            "detail": "In-process deal state (single server)" + (f" — saw {', '.join(seen)}" if seen else
                                                                 " — no Redis env vars present"), "env": seen}
