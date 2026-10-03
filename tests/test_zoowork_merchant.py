"""ZooWork merchant without the network: a fake ZooWork session that issues tool calls."""
import asyncio
import itertools
import time

from pact.deal import Deal

_ids = itertools.count()


class FakeZooWork:
    """Each user.message makes the 'model' call the standard tools, then send_message."""

    think_s = 0.4  # the model takes time before its tool calls appear
    consume_s = 0.5  # resolved calls linger in the pending list this long

    def __init__(self):
        self.calls: dict[str, dict] = {}  # call_id -> call
        self.resolved: dict[str, float] = {}  # call_id -> when the run consumes it
        self.resolve_count: dict[str, int] = {}
        FakeZooWork.last = self

    async def create_session(self, agent_id, metadata):
        return "sess_1"

    async def send_message(self, agent_id, session_id, text):
        for name, args in [("get_inventory", {}), ("get_margin_constraints", {}),
                           ("verify_competitor_price", {}), ("evaluate_shopper_message", {}),
                           ("send_message", {"text": "Here are the terms we can offer."})]:
            cid = f"call_{next(_ids)}"
            self.calls[cid] = {"call_id": cid, "session_id": session_id, "name": name, "input": args,
                               "_visible_at": time.monotonic() + self.think_s}

    async def pending_tool_calls(self, agent_id, session_id):
        await asyncio.sleep(0)
        now = time.monotonic()
        # Like ZooWork: a resolved call stays listed as pending until the paused run consumes it.
        return [c for cid, c in self.calls.items()
                if c["_visible_at"] <= now and self.resolved.get(cid, now + 1) > now]

    async def resolve_tool_call(self, agent_id, call_id, result, is_error=False):
        self.resolved.setdefault(call_id, time.monotonic() + self.consume_s)
        self.resolve_count[call_id] = self.resolve_count.get(call_id, 0) + 1


async def test_each_tool_call_runs_once_across_turns(monkeypatch):
    import pact.agents.zoowork_merchant as zm
    monkeypatch.setenv("PACT_MERCHANT", "zoowork")
    monkeypatch.setenv("ZOOWORK_AGENT_ID", "agt_test")
    monkeypatch.setattr(zm, "ZooWorkClient", FakeZooWork)
    monkeypatch.setattr(zm, "POLL_S", 0.3)

    # The shopper answers (pace 0.01) well inside the merchant's poll sleep, and room.post takes
    # network-like time, so overlapping turns would both get through send_message.
    deal = Deal(pace=0.01)
    await deal.setup()
    real_post = deal.room.post

    async def slow_post(*a, **kw):
        await asyncio.sleep(0.05)
        return await real_post(*a, **kw)
    deal.room.post = slow_post
    await deal.run()
    for _ in range(1000):
        if deal.authority is not None:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(1.0)  # give any duplicate turn time to show up

    assert type(deal.merchant).__name__ == "ZooWorkMerchantAgent"
    zw = FakeZooWork.last
    # Every tool call the model makes runs exactly once, and every one of them runs.
    assert set(zw.resolve_count) == set(zw.calls) and max(zw.resolve_count.values()) == 1
    merchant_posts = [m for m in deal.room.history if m.sender == "MerchantAgent"]
    assert [m.payload["kind"] for m in merchant_posts] == ["counteroffer", "merchant_accept"]
    assert sum(e["type"] == "authority" for e in deal.events) == 1
    assert deal.agreement.terms.price == 299.99
