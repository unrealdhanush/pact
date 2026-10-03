import asyncio

import pytest

from pact import gate
from pact.deal import Deal, DealStore


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for k in ("BAND_SHOPPER_AGENT_KEY", "BAND_MERCHANT_AGENT_KEY", "BAND_API_KEY", "BAND_HUMAN_API_KEY",
              "JEV_API_KEY"):
        monkeypatch.delenv(k, raising=False)


async def settle(deal: Deal, until=("awaiting_approval", "complete", "failed")):
    for _ in range(300):
        if deal.status in until and deal.authority is not None or deal.status == "failed":
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"deal stuck in {deal.status}/{deal.phase}")


def types(deal):
    return [e["type"] for e in deal.events]


async def test_hero_requires_human_then_completes():
    deal = Deal(pace=0, deal_id="deal-1842")
    await deal.run()
    await settle(deal)

    assert deal.id == "deal-1842"
    assert deal.status == "awaiting_approval"
    a = deal.authority
    assert a["decision"] == "HUMAN_APPROVAL_REQUIRED"
    assert a["merchant_policy_ok"] is True and a["shopper_policy_ok"] is False
    assert a["reason"] == "Transaction exceeds shopper auto-approval threshold"
    assert a["source"] == "local" and "unavailable" in a["source_label"]
    assert types(deal).index("authority") < max(i for i, t in enumerate(types(deal)) if t == "status")
    assert any("Jev blocked automatic execution" in w for w in deal.why())

    checkout = deal.approve()
    assert deal.status == "complete" and checkout["simulated"]
    assert deal.execution["approved_by"] == "human"
    with pytest.raises(ValueError):
        deal.approve()
    await asyncio.sleep(0.01)
    assert [e["content"].split(":")[0] for e in deal.room.events][0].startswith("Pact authority check")


async def test_auto_approve_executes_without_human(monkeypatch):
    async def auto(agreement, shopper, merchant, timeout=8.0, **_):
        d = gate.local_decision(agreement, shopper, merchant)
        return {**d, "decision": "AUTO_APPROVE", "shopper_policy_ok": True, "reason": "test", "source_label": "t"}
    monkeypatch.setattr(gate, "evaluate", auto)
    deal = Deal(pace=0)
    await deal.run()
    await settle(deal)
    assert deal.status == "complete" and deal.execution["approved_by"] == "policy"
    with pytest.raises(ValueError):
        deal.approve()


async def test_reject_fails_deal(monkeypatch):
    async def reject(agreement, shopper, merchant, timeout=8.0, **_):
        return {**gate.local_decision(agreement, shopper, merchant), "decision": "REJECT",
                "reason": "risk flag", "source_label": "t"}
    monkeypatch.setattr(gate, "evaluate", reject)
    deal = Deal(pace=0)
    await deal.run()
    await settle(deal)
    assert deal.status == "failed" and deal.failure == "risk flag"
    with pytest.raises(ValueError):
        deal.approve()


def test_local_rules_reject_over_budget():
    from datetime import date
    from pact.protocol import Agreement, Offer
    from pact.scenario import MerchantState, ShopperState
    s = ShopperState()
    terms = Offer(price=310, variant="silver", shipping="free_next_day", delivery_date=date.today(),
                  return_window_days=45)  # $310 > $300 shopper budget; fine for the merchant
    a = Agreement(transaction_id="deal-1", terms=terms, list_price=329.99, shopper_savings=19.99,
                  human_approval_required=True)
    d = gate.local_decision(a, s, MerchantState())
    assert d["decision"] == "REJECT" and "budget" in d["reason"].lower()


async def test_remote_gate_can_only_tighten(monkeypatch):
    class Fake:
        @staticmethod
        async def check_authority(agreement, shopper, merchant):
            return {"transaction_id": agreement.transaction_id, "decision": "AUTO_APPROVE",
                    "merchant_policy_ok": True, "shopper_policy_ok": True, "reason": "looks fine",
                    "checks": [], "source": "jev"}
    monkeypatch.setattr(gate, "_authority", Fake)
    deal = Deal(pace=0)
    await deal.run()
    await settle(deal)
    assert deal.authority["decision"] == "HUMAN_APPROVAL_REQUIRED"
    assert deal.authority["source"] == "jev" and "stricter" in deal.authority["reason"]


async def test_remote_gate_failure_falls_back(monkeypatch):
    class Broken:
        @staticmethod
        async def check_authority(agreement, shopper, merchant):
            raise RuntimeError("jev down")
    monkeypatch.setattr(gate, "_authority", Broken)
    deal = Deal(pace=0)
    await deal.run()
    await settle(deal)
    assert deal.authority["source"] == "local" and "(jev down)" in deal.authority["source_label"]


async def test_store_replaces_fixed_id():
    store = DealStore()
    a = await store.create(pace=0, deal_id="deal-1842")
    await settle(a)
    b = await store.create(pace=0, deal_id="deal-1842")
    assert store.deals["deal-1842"] is b and a is not b
    await settle(b)
    assert b.status == "awaiting_approval"


async def test_on_agreement_can_be_awaited_by_a_shopper():
    from pact import engine
    deal = Deal(pace=0)
    await deal.setup()
    s = deal.shopper_state
    terms = engine.Offer(price=s.max_price - 1, variant=s.preferred_variant, shipping="free_next_day",
                         delivery_date=s.delivery_deadline, return_window_days=s.minimum_return_days)
    agreement = engine.Agreement(transaction_id=deal.id, terms=terms, list_price=deal.product.list_price,
                                 shopper_savings=deal.product.list_price - terms.price, human_approval_required=True)
    await deal._on_agreement(agreement)
    assert deal.authority is not None and deal.status in ("awaiting_approval", "complete", "failed")
