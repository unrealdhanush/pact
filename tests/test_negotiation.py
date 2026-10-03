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


def _agreement(price=219, variant="silver", returns=45):
    from datetime import date, timedelta
    from pact.protocol import Agreement, Offer
    terms = Offer(price=price, variant=variant, shipping="free_next_day",
                  delivery_date=date.today() + timedelta(days=1), return_window_days=returns)
    return Agreement(transaction_id="deal-1", terms=terms, list_price=249,
                     shopper_savings=249 - price, human_approval_required=True)


async def test_gate_without_jev_key_uses_local_rules(monkeypatch):
    from pact import jev
    from pact.scenario import MerchantState, ShopperState
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    s, m = ShopperState(), MerchantState()

    d = await jev.evaluate(_agreement(), s, m, [])
    assert (d.decision, d.merchant_policy_ok, d.shopper_policy_ok, d.source) == \
        ("HUMAN_APPROVAL_REQUIRED", True, False, "local-rules")

    assert (await jev.evaluate(_agreement(price=199), s, m, [])).decision == "REJECT"  # under margin floor
    assert (await jev.evaluate(_agreement(price=230), s, m, [])).decision == "REJECT"  # over budget
    m.min_margin_pct, m.max_auto_discount_pct = 0, 25
    assert (await jev.evaluate(_agreement(price=199), s, m, [])).decision == "AUTO_APPROVE"


async def test_jev_can_only_tighten(monkeypatch):
    from pact import jev
    from pact.scenario import MerchantState, ShopperState
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"answers": {
            "decision": {"choice": "AUTO_APPROVE", "confidence": 0.95}, "risk": {"noul": 0.1}}}

    async def fake_post(self, *a, **kw): return FakeResp()
    monkeypatch.setattr(jev.httpx.AsyncClient, "post", fake_post)
    d = await jev.evaluate(_agreement(), ShopperState(), MerchantState(), [])
    assert d.decision == "HUMAN_APPROVAL_REQUIRED" and d.source == "jev"  # Jev can't loosen rules
