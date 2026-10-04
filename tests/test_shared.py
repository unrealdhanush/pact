"""Serverless: a deal owned by one instance is readable and actionable from another, via Redis."""
import asyncio

import pytest

from pact import server  # import first: it loads .env files, which the test fixtures then override
from pact import shared


class FakeRedis:
    def __init__(self):
        self.kv, self.lists = {}, {}

    async def pipeline(self, cmds):
        out = []
        for c in cmds:
            op, key, *rest = c
            if op == "SET":
                self.kv[key] = rest[0]; out.append("OK")
            elif op == "GET":
                out.append(self.kv.get(key))
            elif op == "EXISTS":
                out.append(int(key in self.kv))
            elif op == "RPUSH":
                self.lists.setdefault(key, []).extend(rest); out.append(len(self.lists[key]))
            elif op == "LRANGE":
                lst = self.lists.get(key, []); out.append(lst[int(rest[0]):] if rest[1] == "-1" or rest[1] == -1 else lst)
            elif op == "LPOP":
                lst = self.lists.get(key, []); out.append(lst.pop(0) if lst else None)
            else:  # EXPIRE
                out.append(1)
        return out


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setenv("KV_REST_API_URL", "https://fake"); monkeypatch.setenv("KV_REST_API_TOKEN", "t")
    monkeypatch.setattr(shared, "pipeline", r.pipeline)
    monkeypatch.setattr(shared, "FLUSH_S", 0.01); monkeypatch.setattr(shared, "POLL_S", 0.01)
    return r


async def test_other_instance_reads_and_approves_through_redis(fake_redis):
    snap = await server.create_deal(pace=0, prefer="fastest")
    did = snap["id"]
    owner = server.store.deals[did]
    for _ in range(500):
        if owner.status == "awaiting_approval":
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.1)  # let the mirror flush

    del server.store.deals[did]  # this request now behaves like a different serverless instance
    try:
        s = await server.get_deal(did)  # served from Redis
        assert s["status"] == "awaiting_approval" and any(e["type"] == "authority" for e in s["events"])
        r = await server.approve(did)  # queued for the owner instance
        assert r == {"ok": True, "queued": True}
        for _ in range(200):
            if owner.status == "complete":
                break
            await asyncio.sleep(0.01)
        assert owner.status == "complete"  # the owner applied the queued approval
        await asyncio.sleep(0.1)
        assert (await server.get_deal(did))["status"] == "complete"
    finally:
        for t in getattr(owner, "_shared_tasks", []):
            t.cancel()


async def test_unknown_everywhere_is_404(fake_redis):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        await server.approve("deal-0000")
    assert e.value.status_code == 404
