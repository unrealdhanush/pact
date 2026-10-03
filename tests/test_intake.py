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
    assert v["product"]["name"] == "Sennheiser Momentum 4" and v["product"]["list_price"] == 259.99
    assert v["fields"]["max_price"] == {**v["fields"]["max_price"], "value": 280.0, "source": "you"}
    assert "sony.com" not in v["reply"]  # the remembered Sony price doesn't apply to the Sennheiser
    s = it.shopper_state()
    p = engine.make_proposal(s, "deal-1", "sennheiser-m4", 259.99)
    assert p.competitor_claim is None and p.requested_price <= 259.99 * 0.9
    with pytest.raises(ValueError):
        await it.choose("airpods-max")  # not sold by a reachable merchant
