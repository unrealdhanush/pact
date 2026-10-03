"""Live authority check for `pact.gate`: the Jev (TypeSafe) decision in `pact.jev`.

`gate.evaluate` calls `check_authority`; it already falls back to local rules if
this raises and never lets the result be looser than those rules.
"""
import os

from . import jev
from .protocol import Agreement
from .scenario import MerchantState, ShopperState


async def check_authority(agreement: Agreement, shopper: ShopperState, merchant: MerchantState,
                          transcript: list[str] | None = None) -> dict:
    if not (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")):
        raise RuntimeError("Jev not configured")  # gate falls back to its labelled local rules
    d = await jev.evaluate(agreement, shopper, merchant, transcript or [])
    if d.source != "jev":  # Jev call failed inside pact.jev; let the gate label the fallback
        raise RuntimeError(d.reason)
    return d.model_dump()


def integration_status() -> dict:
    if os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY"):
        return {"name": "Jev", "mode": "live",
                "detail": "TypeSafe jev-latest: one Choice decision + transcript risk Noul; can only tighten rules"}
    return {"name": "Jev", "mode": "fallback", "detail": "no TYPESAFE_API_KEY — deterministic local policy rules"}
