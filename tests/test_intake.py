from datetime import date

import pytest

from pact import memory as memory_mod
from pact.intake import Intake, parse


@pytest.fixture(autouse=True)
def fresh_memory(monkeypatch):
    monkeypatch.setattr("pact.intake.memory", memory_mod.ShopperMemory())


def test_parse_explicit_boundaries():
    p = parse("get me sony headphones black under three hundred dollars by tuesday, "
              "and ask me before anything over 250", date(2026, 10, 3))
    assert p == {"approval_required_above": 250.0, "max_price": 300.0, "preferred_variant": "black",
                 "delivery_deadline": date(2026, 10, 6)}
    assert "max_price" not in parse("Sony WH-1000XM5 please")  # model number isn't a price


async def test_intake_fills_gaps_from_memory_and_tags_sources():
    it = Intake()
    v = await it.turn("Find me Sony noise-cancelling headphones in black, under 300, by Tuesday")
    assert v["product"]["name"] == "Sony WH-1000XM5" and v["product"]["carried"]
    f = v["fields"]
    assert f["max_price"]["source"] == "you" and f["preferred_variant"]["source"] == "you"
    assert f["fallback_variants"] == {**f["fallback_variants"], "value": ["silver"], "source": "memory"}
    assert f["approval_required_above"]["source"] == "memory" and f["approval_required_above"]["value"] == 250
    assert v["memory"]["mode"] == "fallback"  # labelled: no Moss in tests
    assert [o["product_id"] for o in v["options"] if o["carried"]][0] == "sony-wh1000xm5"
    assert len([o for o in v["options"] if o["carried"]]) == 3
    assert "Pick one and set your max price" in v["reply"]

    v = await it.turn("actually make it under 310")  # the human's correction wins
    assert v["fields"]["max_price"] == {**v["fields"]["max_price"], "value": 310.0, "source": "you"}
    v = await it.turn("yes, go ahead")
    assert v["confirmed"]
    s = it.shopper_state()
    assert (s.max_price, s.approval_required_above, s.competitor_price) == (310.0, 250, 299.99)
    assert s.target_price <= s.competitor_price


async def test_intake_deal_completes_and_is_remembered():
    from pact.deal import Deal
    import asyncio
    mem = memory_mod.ShopperMemory()
    it = Intake()
    await it.turn("Sony headphones in black under 300 by Tuesday")
    remembered = []

    async def remember(deal):
        remembered.append(await mem.remember(f"outcome-{deal.id}", "Bought silver", {}))
    deal = Deal(pace=0, shopper_state=it.shopper_state(), on_complete=remember)
    await deal.run()
    for _ in range(300):
        if deal.status == "awaiting_approval":
            break
        await asyncio.sleep(0.01)
    deal.approve()
    await asyncio.sleep(0.05)
    assert remembered == ["local"]
    hits, _ = await mem.recall("what did I buy last time silver", top_k=6)
    assert any(h.id.startswith("outcome-") for h in hits)


async def test_discovery_ranks_band_peers_and_picks_the_runnable_merchant(monkeypatch):
    from pact import discovery
    from pact.band import BandConfig
    monkeypatch.setattr("pact.memory.memory", memory_mod.ShopperMemory())

    async def fake_request(method, url, key, body):
        assert url.endswith("/agent/peers") and key == "shop-key"
        return {"data": [
            {"type": "User", "name": "Dhanush"},
            {"type": "Agent", "name": "KitchenProAgent", "description": "sells espresso machines and blenders"},
            {"type": "Agent", "name": "MerchantAgent", "description": "Aria Audio: sells Sony WH-1000XM5 headphones and audio"},
            {"type": "Agent", "name": "ShopperAgent", "description": "shopper"},
        ]}
    monkeypatch.setattr(discovery, "urllib_request", fake_request)
    found = await discovery.discover_merchant("Sony WH-1000XM5", BandConfig("shop-key", "merch-key"))
    assert [c["name"] for c in found["candidates"]][0] == "MerchantAgent"
    assert found["chosen"]["name"] == "MerchantAgent" and found["ranker"] == "local"
    assert "ShopperAgent" not in [c["name"] for c in found["candidates"]]


async def test_choosing_another_product_and_price():
    from pact import engine
    it = Intake()
    await it.turn("noise-cancelling headphones in black by Tuesday")
    v = await it.choose("sennheiser-m4", max_price=280)
    assert v["product"]["name"] == "Sennheiser Momentum 4" and v["product"]["list_price"] == 209.99
    assert v["fields"]["max_price"] == {**v["fields"]["max_price"], "value": 280.0, "source": "you"}
    assert "sony.com" not in v["reply"]  # the remembered Sony price doesn't apply to the Sennheiser
    s = it.shopper_state()
    p = engine.make_proposal(s, "deal-1", "sennheiser-m4", 209.99)
    assert p.competitor_claim is None and p.requested_price <= 209.99 * 0.9
    with pytest.raises(ValueError):
        await it.choose("airpods-max")  # not sold by a reachable merchant


async def test_editing_limits_reaches_the_authority_gate():
    from pact.gate import local_decision
    from pact.protocol import Agreement, Offer
    from pact.scenario import MerchantState

    it = Intake()
    await it.turn("Sony headphones in black under 300 by Tuesday")
    v = await it.choose("sony-wh1000xm5", max_price=350, approval_required_above=320)
    assert not v["confirmed"]
    assert v["fields"]["approval_required_above"]["source"] == "you"
    shopper = it.shopper_state()
    assert (shopper.max_price, shopper.approval_required_above) == (350, 320)
    agreement = Agreement(transaction_id="limits-test", list_price=329.99, shopper_savings=30,
                          human_approval_required=False,
                          terms=Offer(price=299.99, variant="silver", shipping="free_next_day",
                                      delivery_date=shopper.delivery_deadline, return_window_days=45))
    assert local_decision(agreement, shopper, MerchantState())["decision"] == "AUTO_APPROVE"
    await it.choose("sony-wh1000xm5", approval_required_above=250)
    assert local_decision(agreement, it.shopper_state(), MerchantState())["decision"] == "HUMAN_APPROVAL_REQUIRED"
    await it.choose("sony-wh1000xm5", max_price=290)
    assert local_decision(agreement, it.shopper_state(), MerchantState())["decision"] == "REJECT"


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "not a number"])
async def test_invalid_limit_edits_are_atomic(bad):
    it = Intake()
    await it.turn("Sony headphones in black under 300 by Tuesday")
    before = it.shopper_state()
    with pytest.raises(ValueError):
        await it.choose("sennheiser-m4", max_price=350, approval_required_above=bad)
    assert it.product["product_id"] == "sony-wh1000xm5"
    assert it.shopper_state() == before


async def test_limit_edit_api_and_product_assets(monkeypatch):
    import httpx
    from pact import server

    it = Intake()
    await it.turn("Sony headphones in black under 300 by Tuesday")
    monkeypatch.setattr(server.intakes, "items", {it.id: it})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://pact.test") as client:
        r = await client.post(f"/api/intake/{it.id}/choose", json={"product_id": "sony-wh1000xm5", "max_price": 350, "approval_required_above": 0})
        assert r.status_code == 200
        assert r.json()["fields"]["approval_required_above"]["value"] == 0
        r = await client.post(f"/api/intake/{it.id}/choose", json={"product_id": "sony-wh1000xm5", "approval_required_above": -1})
        assert r.status_code == 409
        r = await client.get("/api/scenario?product_id=sennheiser-m4")
        assert r.json()["merchant"]["inventory"] == {"black": 9, "white": 4}
        assert (await client.get("/api/scenario?product_id=unknown")).status_code == 422
        for name in ("sony-wh1000xm5", "bose-qc-ultra", "sennheiser-m4"):
            r = await client.get(f"/assets/{name}.png")
            assert r.status_code == 200 and r.headers["content-type"] == "image/png"


@pytest.mark.parametrize("text,expect", [
    ("Hi", "What are you looking for"),
    ("hello there", "What are you looking for"),
    ("what can you do?", "I'm your shopping agent"),
    ("thanks!", "You're welcome"),
    ("I need a gift for my dad", "couldn't match"),
])
async def test_small_talk_does_not_trigger_a_product_search(text, expect):
    it = Intake()
    v = await it.turn(text)
    assert expect in v["reply"] and v["product"] is None and v["options"] == [] and v["recalled"] == []
    v = await it.turn("Find me Sony noise-cancelling headphones in black, under 300, by Tuesday")
    assert v["product"]["name"] == "Sony WH-1000XM5"  # then a real request works in the same chat
