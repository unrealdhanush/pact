"""Authority gate seam used by the deal orchestration.

The live gate (Jev + policy) is owned by `pact/authority.py`, exposing
`async check_authority(agreement, shopper_state, merchant_state) -> AuthorityDecision`.
Until that module exists, or if it fails, this file evaluates the same
contract with deterministic local rules and labels the result `source="local"`.
The final decision is never looser than the local rules.
"""
import asyncio
import inspect
import logging
from typing import Literal

from . import engine
from .protocol import Agreement
from .scenario import MerchantState, ShopperState

log = logging.getLogger("pact.gate")

try:  # owned by the merchant/Jev side; optional until it lands
    from . import authority as _authority  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - depends on the other branch
    _authority = None

Decision = Literal["AUTO_APPROVE", "HUMAN_APPROVAL_REQUIRED", "REJECT"]
_STRICTNESS = {"AUTO_APPROVE": 0, "HUMAN_APPROVAL_REQUIRED": 1, "REJECT": 2}
LOCAL_LABEL = "Jev live decision service unavailable — local policy rules"


def local_decision(agreement: Agreement, shopper: ShopperState, merchant: MerchantState) -> dict:
    t = agreement.terms
    acceptable = [shopper.preferred_variant, *shopper.fallback_variants]
    margin = engine.margin_pct(merchant, t)
    discount = engine.discount_pct(merchant, t.price)
    merchant_checks = [
        {"side": "merchant", "rule": "Margin above floor", "ok": margin >= merchant.min_margin_pct,
         "detail": f"{margin:.1f}% vs {merchant.min_margin_pct:.0f}% floor"},
        {"side": "merchant", "rule": "Discount within agent authority",
         "ok": discount <= merchant.max_auto_discount_pct + 1e-9,
         "detail": f"{discount:.1f}% off list (cap {merchant.max_auto_discount_pct:.0f}%)"},
        {"side": "merchant", "rule": "Variant price floor",
         "ok": t.price >= merchant.variant_floor.get(t.variant, 0),
         "detail": f"{t.variant} has no scarcity floor" if t.variant not in merchant.variant_floor
         else f"floor {engine.money(merchant.variant_floor[t.variant])}"},
        {"side": "merchant", "rule": "Return window within policy",
         "ok": t.return_window_days <= merchant.max_return_days,
         "detail": f"{t.return_window_days} days (max {merchant.max_return_days})"},
        {"side": "merchant", "rule": "Inventory available", "ok": merchant.inventory.get(t.variant, 0) > 0,
         "detail": f"{t.variant} in stock"},
    ]
    shopper_hard = [
        {"side": "shopper", "rule": "Within budget", "ok": t.price <= shopper.max_price,
         "detail": f"{engine.money(t.price)} of {engine.money(shopper.max_price)} max"},
        {"side": "shopper", "rule": "Acceptable variant", "ok": t.variant in acceptable,
         "detail": f"{t.variant} ({'preferred' if t.variant == shopper.preferred_variant else 'fallback'})"},
        {"side": "shopper", "rule": "Arrives by deadline", "ok": t.delivery_date <= shopper.delivery_deadline,
         "detail": f"{t.delivery_date.isoformat()} ≤ {shopper.delivery_deadline.isoformat()}"},
        {"side": "shopper", "rule": "Return window", "ok": t.return_window_days >= shopper.minimum_return_days,
         "detail": f"{t.return_window_days} ≥ {shopper.minimum_return_days} days"},
    ]
    needs_human = t.price >= shopper.approval_required_above
    threshold = {"side": "shopper", "rule": "Auto-approval threshold", "ok": not needs_human,
                 "detail": f"{engine.money(t.price)} vs {engine.money(shopper.approval_required_above)} auto-approve limit"}

    merchant_ok = all(c["ok"] for c in merchant_checks)
    shopper_hard_ok = all(c["ok"] for c in shopper_hard)
    if not merchant_ok or not shopper_hard_ok:
        failed = next(c for c in merchant_checks + shopper_hard if not c["ok"])
        decision, reason = "REJECT", f"{failed['rule']} failed: {failed['detail']}"
    elif needs_human:
        decision, reason = "HUMAN_APPROVAL_REQUIRED", "Transaction exceeds shopper auto-approval threshold"
    else:
        decision, reason = "AUTO_APPROVE", "Inside every merchant and shopper boundary"
    return {
        "transaction_id": agreement.transaction_id,
        "decision": decision,
        "merchant_policy_ok": merchant_ok,
        "shopper_policy_ok": shopper_hard_ok and not needs_human,
        "reason": reason,
        "checks": [*merchant_checks, *shopper_hard, threshold],
        "source": "local",
        "jev_raw": None,
    }


def _as_dict(d) -> dict:
    return d.model_dump(mode="json") if hasattr(d, "model_dump") else dict(d)


async def evaluate(agreement: Agreement, shopper: ShopperState, merchant: MerchantState,
                   timeout: float = 8.0, transcript: list[str] | None = None) -> dict:
    local = local_decision(agreement, shopper, merchant)
    check = getattr(_authority, "check_authority", None)
    if check is None:
        return {**local, "source_label": LOCAL_LABEL}
    try:
        # The transcript (for Jev's risk check) is optional to the authority contract.
        kw = {"transcript": transcript} if "transcript" in inspect.signature(check).parameters else {}
        remote = _as_dict(await asyncio.wait_for(check(agreement, shopper, merchant, **kw), timeout))
    except Exception as e:  # noqa: BLE001 - any failure falls back to local rules
        log.warning("authority.check_authority failed: %s", e)
        detail = str(e)[:120] or type(e).__name__
        return {**local, "source_label": f"{LOCAL_LABEL} ({detail})"}
    remote.setdefault("checks", local["checks"])
    if _STRICTNESS.get(remote.get("decision"), 2) < _STRICTNESS[local["decision"]]:
        remote["decision"], remote["reason"] = local["decision"], f"{local['reason']} (local rules are stricter)"
        remote["merchant_policy_ok"] = remote.get("merchant_policy_ok", True) and local["merchant_policy_ok"]
        remote["shopper_policy_ok"] = remote.get("shopper_policy_ok", True) and local["shopper_policy_ok"]
    label = "Jev live decision" if remote.get("source") == "jev" else LOCAL_LABEL
    return {**remote, "source_label": label}


def integration_status() -> dict:
    status = getattr(_authority, "integration_status", None)
    if status:
        try:
            return status()
        except Exception as e:  # noqa: BLE001
            return {"name": "Jev", "mode": "fallback", "detail": f"authority status error: {e}"}
    return {"name": "Jev", "mode": "fallback",
            "detail": "pact/authority.py not present — deterministic local policy rules"}
