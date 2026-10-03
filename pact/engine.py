"""Deterministic negotiation logic.

The engine decides terms; agents only phrase them. Every function returns the
public result plus private notes that stay on the owner's side of the room.
"""
import math
from datetime import date, timedelta

from .protocol import (
    Agreement, ConditionalAccept, Counteroffer, MerchantAccept, Offer, Proposal, Rejection,
)
from .scenario import MerchantState, ShopperState


def charm_up(x: float) -> int:
    """Round up to the next price ending in 9 (216.63 -> 219)."""
    n = math.ceil(x)
    return n + (9 - n % 10) % 10


# ---------------------------------------------------------------- merchant

def net_revenue(m: MerchantState, offer: Offer) -> float:
    ship = m.next_day_shipping_cost if offer.shipping == "free_next_day" else 0
    extra_days = max(0, offer.return_window_days - m.standard_return_days)
    return offer.price - ship - extra_days * m.return_cost_per_extra_day


def margin_pct(m: MerchantState, offer: Offer) -> float:
    net = net_revenue(m, offer)
    return (net - m.unit_cost) / net * 100


def discount_pct(m: MerchantState, price: float) -> float:
    return (m.list_price - price) / m.list_price * 100


def within_authority(m: MerchantState, offer: Offer) -> bool:
    return (
        margin_pct(m, offer) >= m.min_margin_pct
        and discount_pct(m, offer.price) <= m.max_auto_discount_pct + 1e-9
        and offer.price >= m.variant_floor.get(offer.variant, 0)
        and offer.return_window_days <= m.max_return_days
        and m.inventory.get(offer.variant, 0) > 0
    )


def evaluate_proposal(
    m: MerchantState, p: Proposal, today: date
) -> tuple[Counteroffer | Rejection, list[str]]:
    notes: list[str] = []
    standard_arrival = today + timedelta(days=m.standard_shipping_days)
    if standard_arrival <= p.delivery_deadline:
        shipping, arrival, ship_cost = "standard", standard_arrival, 0.0
    else:
        shipping, arrival, ship_cost = "free_next_day", today + timedelta(days=1), m.next_day_shipping_cost
        notes.append(f"Standard shipping misses the deadline; next-day costs us ${ship_cost:.0f}")

    returns = max(m.standard_return_days, p.minimum_return_days)
    authority_min = charm_up(m.list_price * (1 - m.max_auto_discount_pct / 100))
    margin_min = m.unit_cost / (1 - m.min_margin_pct / 100) + ship_cost
    if p.requested_price < authority_min:
        notes.append(
            f"${p.requested_price:.0f} is {discount_pct(m, p.requested_price):.1f}% off — "
            f"beyond my {m.max_auto_discount_pct:.0f}% autonomous authority"
        )

    ordered = [p.preferred_variant] + [v for v in p.acceptable_variants if v != p.preferred_variant]
    offers: list[Offer] = []
    for v in ordered:
        stock = m.inventory.get(v, 0)
        if stock <= 0:
            notes.append(f"{v}: out of stock")
            continue
        floor = m.variant_floor.get(v, 0)
        price = max(p.requested_price, authority_min, charm_up(margin_min), floor)
        offer = Offer(price=price, variant=v, shipping=shipping,
                      delivery_date=arrival, return_window_days=returns)
        if not within_authority(m, offer):
            notes.append(f"{v}: no offer inside my authority")
            continue
        if floor:
            notes.append(f"{v}: only {stock} left — held at ${floor:.0f} scarcity floor")
        elif v in m.overstock:
            notes.append(f"{v}: {stock} units overstocked — lead with deepest authorised price")
        notes.append(f"{v} @ ${price:.0f}: margin {margin_pct(m, offer):.1f}% (floor {m.min_margin_pct:.0f}%)")
        offers.append(offer)

    if not offers:
        return Rejection(transaction_id=p.transaction_id, party="merchant",
                         reason="No terms available within merchant policy"), notes

    explanation = []
    if any(o.variant in m.overstock for o in offers):
        explanation.append("Best pricing is on the variant we have in depth")
    if shipping == "free_next_day":
        explanation.append("Free next-day delivery included to meet your deadline")
    return Counteroffer(
        transaction_id=p.transaction_id, offers=offers, merchant_margin_valid=True,
        requires_human_approval=False, explanation=explanation,
    ), notes


def evaluate_conditions(
    m: MerchantState, c: ConditionalAccept
) -> tuple[MerchantAccept | Rejection, list[str]]:
    terms = c.offer.model_copy(update=c.conditions)
    notes: list[str] = []
    if within_authority(m, terms):
        notes.append(
            f"With {terms.return_window_days}-day returns margin is "
            f"{margin_pct(m, terms):.1f}% — still above {m.min_margin_pct:.0f}% floor"
        )
        return MerchantAccept(
            transaction_id=c.transaction_id, terms=terms,
            explanation=["Extended return window is within merchant policy"],
        ), notes
    notes.append("Requested terms break merchant policy")
    return Rejection(transaction_id=c.transaction_id, party="merchant",
                     reason="Requested terms are outside merchant policy"), notes


# ----------------------------------------------------------------- shopper

def make_proposal(s: ShopperState, transaction_id: str, product_id: str) -> Proposal:
    return Proposal(
        transaction_id=transaction_id, product_id=product_id,
        requested_price=s.target_price, preferred_variant=s.preferred_variant,
        acceptable_variants=[s.preferred_variant, *s.fallback_variants],
        delivery_deadline=s.delivery_deadline, minimum_return_days=s.minimum_return_days,
        requires_human_approval=True,
    )


def _meets_basics(s: ShopperState, o: Offer) -> str | None:
    if o.price > s.max_price:
        return f"{o.variant} @ ${o.price:.0f} is over my ${s.max_price:.0f} budget"
    if o.delivery_date > s.delivery_deadline:
        return f"{o.variant} arrives {o.delivery_date}, after the deadline"
    if o.return_window_days < s.minimum_return_days:
        return f"{o.variant} has only {o.return_window_days}-day returns"
    return None


def evaluate_counteroffer(
    s: ShopperState, c: Counteroffer
) -> tuple[ConditionalAccept | Rejection, list[str]]:
    """Accepting an offer as-is is a ConditionalAccept with no conditions."""
    notes: list[str] = []
    viable: list[Offer] = []
    for o in c.offers:
        problem = _meets_basics(s, o)
        if problem:
            notes.append(problem)
        else:
            viable.append(o)

    for o in viable:
        if o.variant == s.preferred_variant:
            notes.append(f"{o.variant} @ ${o.price:.0f} meets every boundary")
            return ConditionalAccept(transaction_id=c.transaction_id, offer=o, conditions={}), notes

    for o in viable:
        if o.variant in s.fallback_variants:
            notes.append(f"{o.variant} is an acceptable fallback colour")
            if o.return_window_days >= s.fallback_return_days:
                return ConditionalAccept(transaction_id=c.transaction_id, offer=o, conditions={}), notes
            notes.append(f"Fallback colour only if returns are {s.fallback_return_days} days")
            return ConditionalAccept(
                transaction_id=c.transaction_id, offer=o,
                conditions={"return_window_days": s.fallback_return_days},
            ), notes

    return Rejection(transaction_id=c.transaction_id, party="shopper",
                     reason="No offer fits the customer's boundaries"), notes


def finalize(s: ShopperState, transaction_id: str, terms: Offer, list_price: float
             ) -> tuple[Agreement | Rejection, list[str]]:
    problem = _meets_basics(s, terms)
    if problem:
        return Rejection(transaction_id=transaction_id, party="shopper", reason=problem), [problem]
    needs_human = terms.price >= s.approval_required_above
    notes = [
        "Final terms are inside every boundary",
        f"${terms.price:.0f} ≥ ${s.approval_required_above:.0f} auto-approve limit — human sign-off required"
        if needs_human else f"${terms.price:.0f} under auto-approve limit",
    ]
    return Agreement(
        transaction_id=transaction_id, terms=terms, list_price=list_price,
        shopper_savings=list_price - terms.price, human_approval_required=needs_human,
    ), notes
