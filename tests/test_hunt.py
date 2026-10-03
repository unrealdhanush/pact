import asyncio

import pytest

from pact.hunt import Hunt


async def settle(h, until=("awaiting_approval", "complete", "failed")):
    for _ in range(500):
        if h.status in until and (h.authority is not None or h.status == "failed"):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"hunt stuck in {h.status}")


@pytest.mark.parametrize("preference,priorities,winner,variant", [
    # silver is an accepted fallback with 45-day returns, and Aria is 2 days faster with 15 more return days
    ("best", [], "aria", "silver"),
    ("best", ["colour"], "soundhub", "black"),   # the human cares most about getting black
    ("fastest", [], "aria", "silver"),           # next-day beats 3-day standard
    ("cheapest", [], "soundhub", "black"),       # same price; preferred colour breaks the tie
])
async def test_shopper_compares_merchants_by_what_the_human_values(preference, priorities, winner, variant):
    from pact.scenario import ShopperState
    h = Hunt(pace=0, preference=preference, shopper_state=ShopperState(priorities=priorities))
    await h.setup()
    await h.run()
    await settle(h)
    assert {q["merchant"] for q in h.quotes} == {"aria", "soundhub"}
    assert all("price" in q for q in h.quotes) and all(q["price"] == 299.99 for q in h.quotes)
    assert h.winner.merchant_id == winner and h.agreement.terms.variant == variant
    assert h.status == "awaiting_approval" and h.authority["decision"] == "HUMAN_APPROVAL_REQUIRED"
    assert any(e["type"] == "quotes" and e["winner"] == winner for e in h.events)
    # only the winner's status events reach the outside
    assert {e.get("merchant") for e in h.events if e["type"] == "status" and e.get("merchant")} == {winner}
    h.approve()
    assert h.status == "complete"


async def test_hunt_fails_cleanly_when_no_merchant_fits():
    h = Hunt(pace=0, product_id="bose-qc-ultra")
    await h.setup()
    await h.run()
    await settle(h)
    assert h.status == "failed" and h.winner is None and len(h.quotes) == 2
    with pytest.raises(ValueError):
        h.approve()


async def _near_miss_hunt(monkeypatch, budget):
    from pact.scenario import ShopperState
    s = ShopperState(max_price=budget, target_price=int(budget * 0.93))
    h = Hunt(pace=0, shopper_state=s)
    await h.setup()
    await h.run()
    for _ in range(500):
        if h.status in ("awaiting_exception", "failed"):
            break
        await asyncio.sleep(0.01)
    return h


async def test_near_miss_is_put_to_the_human_and_can_be_accepted(monkeypatch):
    h = await _near_miss_hunt(monkeypatch, 290)  # both stores land at $299.99: 3.4% over -> grey zone
    assert h.status == "awaiting_exception"
    ex = next(e for e in h.events if e["type"] == "status" and e["status"] == "awaiting_exception")["exception"]
    assert ex["over_by"] == 9.99 and ex["decision"]["decision"] == "ASK_HUMAN"  # local rule: ask up to 5%
    h.resolve_exception(True)
    await settle(h)
    assert h.status == "awaiting_approval" and h.agreement.terms.price == 299.99
    assert any("approved going" in w for w in h.why())


async def test_far_over_budget_walks_away_without_asking(monkeypatch):
    h = await _near_miss_hunt(monkeypatch, 250)  # $299.99 is 20% over -> code rule: walk away
    assert h.status == "failed" and not any(e["type"] == "status" and e["status"] == "awaiting_exception"
                                            for e in h.events)


async def test_order_tracking_after_execution():
    h = Hunt(pace=0, preference="fastest")
    await h.setup()
    await h.run()
    await settle(h)
    h.approve()
    for _ in range(200):
        if sum(e["type"] == "tracking" for e in h.events) == 5:
            break
        await asyncio.sleep(0.01)
    stages = [e["stage"] for e in h.events if e["type"] == "tracking"]
    assert stages == ["confirmed", "packed", "shipped", "out_for_delivery", "delivered"]
    last = [e for e in h.events if e["type"] == "tracking"][-1]
    assert last["simulated"] and last["date"] == h.agreement.terms.delivery_date.isoformat()


async def test_return_flow_negotiates_store_credit_and_needs_the_human():
    h = Hunt(pace=0, preference="fastest")
    await h.setup()
    await h.run()
    await settle(h)
    h.approve()
    await h.start_return("They're uncomfortable after an hour")
    for _ in range(300):
        rs = getattr(h.winner, "return_state", {}) or {}
        if rs.get("status") in ("awaiting_approval", "resolved", "rejected"):
            break
        await asyncio.sleep(0.01)
    rs = h.winner.return_state
    kinds = [m.payload["kind"] for m in h.winner.room.history if m.payload and m.payload["kind"].startswith(("return", "resolution"))]
    assert kinds == ["return_request", "resolution_offer", "resolution_counter", "resolution_offer", "resolution_accept"]
    assert rs["status"] == "awaiting_approval" and rs["terms"]["resolution"] == "store_credit"
    assert rs["terms"]["goodwill_credit"] == 30 and rs["authority"]["decision"] == "HUMAN_APPROVAL_REQUIRED"
    out = h.approve_return()
    assert out["simulated"] and h.winner.return_state["status"] == "resolved"
    with pytest.raises(ValueError):
        await h.start_return("again")
