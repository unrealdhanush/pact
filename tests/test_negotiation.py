import asyncio

from pact import engine
from pact.deal import Deal


def test_charm_up():
    assert engine.charm_up(216.63) == 219
    assert engine.charm_up(219) == 219
    assert engine.charm_up(220) == 229


async def test_hero_negotiation_reaches_219_silver_and_waits_for_human():
    deal = Deal(pace=0)
    await deal.run()
    for _ in range(200):
        if deal.status != "negotiating":
            break
        await asyncio.sleep(0.01)

    assert deal.status == "awaiting_approval"
    t = deal.agreement.terms
    assert (t.price, t.variant, t.shipping, t.return_window_days) == (219, "silver", "free_next_day", 45)
    assert deal.agreement.shopper_savings == 30

    # The ladder the UI shows: 249 -> 235 (black) -> 219 (silver)
    counter = next(e["message"]["payload"] for e in deal.events
                   if e["type"] == "message" and e["message"]["payload"]["kind"] == "counteroffer")
    assert [(o["variant"], o["price"]) for o in counter["offers"]] == [("black", 235), ("silver", 219)]

    # Private constraints never cross the room.
    room_text = " ".join(m.text for m in deal.room.history)
    for secret in ("$220", "$205", "$168", "17 units", "13%"):
        assert secret not in room_text

    checkout = deal.approve()
    assert deal.status == "complete" and checkout["simulated"]
    assert deal.merchant_state.inventory["silver"] == 16
