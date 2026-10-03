import asyncio

from pact import engine
from pact.deal import Deal


def test_price_point_and_money():
    assert engine.price_point(296.99) == 296.99
    assert engine.price_point(313.49) == 313.99
    assert engine.price_point(297.0) == 297.99
    assert engine.money(299.99) == "$299.99" and engine.money(300) == "$300"


async def test_hero_negotiation_price_matches_verified_competitor_and_waits_for_human():
    deal = Deal(pace=0)
    await deal.run()
    for _ in range(200):
        if deal.status != "negotiating":
            break
        await asyncio.sleep(0.01)

    assert deal.status == "awaiting_approval"
    t = deal.agreement.terms
    assert (t.price, t.variant, t.shipping, t.return_window_days) == (299.99, "silver", "free_next_day", 45)
    assert deal.agreement.shopper_savings == 30
    assert deal.decision.decision == "HUMAN_APPROVAL_REQUIRED"

    # Black held at its scarcity floor; silver price-matched to the (cached) Tavily-verified sony.com price.
    counter = next(e["message"]["payload"] for e in deal.events
                   if e["type"] == "message" and e["message"]["payload"]["kind"] == "counteroffer")
    assert [(o["variant"], o["price"]) for o in counter["offers"]] == [("black", 319.99), ("silver", 299.99)]
    assert counter["competitor_check"]["verified"] and counter["competitor_check"]["source"] == "cache"

    # Private constraints never cross the room.
    room_text = " ".join(m.text for m in deal.room.history)
    for secret in ("$300", "$230", "17 units", "10%", "18%"):
        assert secret not in room_text

    checkout = deal.approve()
    assert deal.status == "complete" and checkout["simulated"]
    assert deal.merchant_state.inventory["silver"] == 16


async def test_unverified_competitor_claim_gets_no_price_match():
    from datetime import date
    from pact.protocol import CompetitorClaim
    from pact.scenario import MerchantState, ShopperState
    from pact.tavily import CompetitorCheck
    p = engine.make_proposal(ShopperState(), "deal-1", "sony-wh1000xm5")
    p.competitor_claim = CompetitorClaim(retailer="sony.com", price=249.99)
    bluff = CompetitorCheck(retailer="sony.com", claimed_price=249.99, verified=False,
                            checked_at="now", source="tavily")
    counter, notes = engine.evaluate_proposal(MerchantState(), p, date.today(), bluff)
    silver = next(o for o in counter.offers if o.variant == "silver")
    assert silver.price == 313.99  # promo price, no match
    assert any("not verified" in n for n in notes)


def _agreement(price=299.99, variant="silver", returns=45):
    from datetime import date, timedelta
    from pact.protocol import Agreement, Offer
    terms = Offer(price=price, variant=variant, shipping="free_next_day",
                  delivery_date=date.today() + timedelta(days=1), return_window_days=returns)
    return Agreement(transaction_id="deal-1", terms=terms, list_price=329.99,
                     shopper_savings=round(329.99 - price, 2), human_approval_required=True)


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
    assert (await jev.evaluate(_agreement(price=310), s, m, [])).decision == "REJECT"  # over budget
    m.min_margin_pct, m.max_auto_discount_pct, m.unit_cost = 0, 50, 100
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
