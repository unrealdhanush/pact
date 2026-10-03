import asyncio

import pytest

from pact.hunt import Hunt


async def settle(h, until=("awaiting_approval", "complete", "failed")):
    for _ in range(500):
        if h.status in until and (h.authority is not None or h.status == "failed"):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"hunt stuck in {h.status}")


@pytest.mark.parametrize("preference,winner,variant", [
    ("best", "soundhub", "black"),      # preferred colour wins
    ("fastest", "aria", "silver"),      # next-day beats 3-day standard
    ("cheapest", "aria", "silver"),     # same price; tie broken by speed
])
async def test_shopper_compares_merchants_by_preference(preference, winner, variant):
    h = Hunt(pace=0, preference=preference)
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
