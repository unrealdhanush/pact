"""Deterministic negotiation logic.

The engine decides terms; agents only phrase them. Every function returns the
public result plus private notes that stay on the owner's side of the room.
"""
import math
from datetime import date, timedelta

from .protocol import (
    Agreement, CompetitorClaim, ConditionalAccept, Counteroffer, MerchantAccept, Offer, Proposal, Rejection,
)
from .scenario import MerchantState, ShopperState
from .tavily import CompetitorCheck


def price_point(x: float) -> float:
    """Round up to the next price ending in .99 (296.99 -> 296.99, 313.49 -> 313.99)."""
    return round(math.ceil(round(x - 0.99, 6)) + 0.99, 2)


def money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")


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
    m: MerchantState, p: Proposal, today: date, competitor: CompetitorCheck | None = None
) -> tuple[Counteroffer | Rejection, list[str]]:
    """Scarce variants hold their floor. Overstock leads with a promo price, or price-matches a
    competitor price verified by Tavily, never below margin floor or discount authority."""
    notes: list[str] = []
    standard_arrival = today + timedelta(days=m.standard_shipping_days)
    if standard_arrival <= p.delivery_deadline:
        shipping, arrival, ship_cost = "standard", standard_arrival, 0.0
    else:
        shipping, arrival, ship_cost = "free_next_day", today + timedelta(days=1), m.next_day_shipping_cost
        notes.append(f"Standard shipping misses the deadline; next-day costs us {money(ship_cost)}")

    returns = max(m.standard_return_days, p.minimum_return_days)
    authority_min = price_point(m.list_price * (1 - m.max_auto_discount_pct / 100))
    margin_min = price_point(m.unit_cost / (1 - m.min_margin_pct / 100) + ship_cost)
    lowest = max(authority_min, margin_min)
    promo = max(lowest, price_point(m.list_price * (1 - m.max_auto_discount_pct / 200)))
    if p.requested_price < lowest:
        notes.append(
            f"{money(p.requested_price)} is {discount_pct(m, p.requested_price):.1f}% off — "
            f"beyond my {m.max_auto_discount_pct:.0f}% autonomous authority"
        )
    match = None
    if competitor is not None:
        where = "cached" if competitor.source == "cache" else "live"
        if competitor.verified and competitor.found_price >= lowest:
            match = competitor.found_price
            notes.append(f"{competitor.retailer} at {money(match)} verified ({where}) — price-match allowed")
        elif competitor.verified:
            notes.append(f"{competitor.retailer} at {money(competitor.found_price)} verified but below my "
                         f"authority — can't fully match")
        else:
            notes.append(f"{competitor.retailer} claim of {money(competitor.claimed_price)} not verified — "
                         f"no price match")

    ordered = [p.preferred_variant] + [v for v in p.acceptable_variants if v != p.preferred_variant]
    offers: list[Offer] = []
    for v in ordered:
        stock = m.inventory.get(v, 0)
        if stock <= 0:
            notes.append(f"{v}: out of stock")
            continue
        floor = m.variant_floor.get(v, 0)
        base = floor or (match if match is not None and v in m.overstock else promo)
        price = max(p.requested_price, lowest, base)
        offer = Offer(price=price, variant=v, shipping=shipping,
                      delivery_date=arrival, return_window_days=returns)
        if not within_authority(m, offer):
            notes.append(f"{v}: no offer inside my authority")
            continue
        if floor:
            notes.append(f"{v}: only {stock} left — held at {money(floor)} scarcity floor")
        elif v in m.overstock:
            notes.append(f"{v}: {stock} units overstocked — " +
                         ("match the verified competitor" if match is not None else "lead with promo price"))
        notes.append(f"{v} @ {money(price)}: margin {margin_pct(m, offer):.1f}% (floor {m.min_margin_pct:.0f}%)")
        offers.append(offer)

    if not offers:
        return Rejection(transaction_id=p.transaction_id, party="merchant",
                         reason="No terms available within merchant policy"), notes

    explanation = []
    if match is not None:
        explanation.append(f"Price-matched the verified {competitor.retailer} price")
    if any(o.variant in m.overstock for o in offers):
        explanation.append("Best pricing is on the variant we have in depth")
    if shipping == "free_next_day":
        explanation.append("Free next-day delivery included to meet your deadline")
    return Counteroffer(
        transaction_id=p.transaction_id, offers=offers, merchant_margin_valid=True,
        requires_human_approval=False, explanation=explanation,
        competitor_check=competitor.model_dump() if competitor else None,
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

def opening_price(s: ShopperState, list_price: float) -> float:
    """Open below both the shopper's own target and the public shelf price."""
    return min(s.target_price, math.floor(list_price * 0.90))


def make_proposal(s: ShopperState, transaction_id: str, product_id: str, list_price: float | None = None) -> Proposal:
    return Proposal(
        transaction_id=transaction_id, product_id=product_id,
        requested_price=opening_price(s, list_price) if list_price else s.target_price, preferred_variant=s.preferred_variant,
        acceptable_variants=[s.preferred_variant, *s.fallback_variants],
        delivery_deadline=s.delivery_deadline, minimum_return_days=s.minimum_return_days,
        requires_human_approval=True,
        competitor_claim=CompetitorClaim(retailer=s.competitor_retailer, price=s.competitor_price)
        if s.competitor_retailer and s.competitor_price
        and s.competitor_product_id in (None, product_id) else None,
    )


def _meets_basics(s: ShopperState, o: Offer) -> str | None:
    if o.price > s.max_price:
        return f"{o.variant} @ {money(o.price)} is over my {money(s.max_price)} budget"
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
            notes.append(f"{o.variant} @ {money(o.price)} meets every boundary")
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
        f"{money(terms.price)} ≥ {money(s.approval_required_above)} auto-approve limit — human sign-off required"
        if needs_human else f"{money(terms.price)} under auto-approve limit",
    ]
    return Agreement(
        transaction_id=transaction_id, terms=terms, list_price=list_price,
        shopper_savings=round(list_price - terms.price, 2), human_approval_required=needs_human,
    ), notes


def near_miss(s: ShopperState, c: Counteroffer) -> dict | None:
    """The best offer that misses the shopper's boundaries only on price (right colour, on time)."""
    acceptable = [s.preferred_variant, *s.fallback_variants]
    cands = [o for o in c.offers if o.variant in acceptable and o.delivery_date <= s.delivery_deadline
             and o.price > s.max_price]
    if not cands:
        return None
    o = min(cands, key=lambda x: (x.price, x.variant != s.preferred_variant))
    over = round(o.price - s.max_price, 2)
    return {"offer": o, "over_by": over, "over_pct": round(over / s.max_price * 100, 1), "budget": s.max_price}


# ---------------------------------------------------------------- comparing offers by what the human values
PRIORITIES = ("price", "colour", "speed", "returns")
PRESETS = {  # "shop around for" presets; selected priorities multiply on top
    "best": {"price": 1.0, "colour": 1.0, "speed": 1.0, "returns": 1.0},
    "cheapest": {"price": 1.0, "colour": 0.5, "speed": 0.1, "returns": 0.1},
    "fastest": {"price": 1.0, "colour": 1.0, "speed": 5.0, "returns": 0.5},
}
EMPHASIS = 3.0  # a priority the human marked as important


def weights(preference: str, priorities: list[str] | None) -> dict[str, float]:
    w = dict(PRESETS.get(preference, PRESETS["best"]))
    for p in priorities or []:
        if p in w and p != "price":
            w[p] *= EMPHASIS
        elif p == "price":  # price matters more = everything else matters less
            for k in ("colour", "speed", "returns"):
                w[k] /= EMPHASIS
    return w


def offer_fit(s: ShopperState, t: Offer, w: dict[str, float], today: date | None = None) -> tuple[float, dict]:
    """Effective cost of an offer to this human, in dollars (lower is better), with a breakdown."""
    today = today or date.today()
    if t.variant == s.preferred_variant:
        colour = 0.0
    elif t.variant in s.fallback_variants:
        condition_met = t.return_window_days >= s.fallback_return_days
        colour = (8.0 if condition_met else 25.0) * w["colour"]
    else:
        colour = 1000.0
    days = max(0, (t.delivery_date - today).days)
    speed = 6.0 * w["speed"] * days
    returns = 0.6 * w["returns"] * max(0, t.return_window_days - s.minimum_return_days)
    score = t.price + colour + speed - returns
    return round(score, 2), {"price": t.price, "colour": round(colour, 2), "delivery_days": days,
                             "speed": round(speed, 2), "returns": round(returns, 2), "score": round(score, 2)}


def explain_choice(s: ShopperState, win: Offer, wb: dict, other: Offer, ob: dict) -> str:
    """One sentence on why `win` beat `other`, in the human's terms."""
    bits = []
    if win.variant != other.variant:
        if win.variant == s.preferred_variant:
            bits.append(f"it's your preferred {win.variant}")
        elif win.variant in s.fallback_variants and win.return_window_days >= s.fallback_return_days:
            bits.append(f"{win.variant} instead of {other.variant} (you said {win.variant} is fine with "
                        f"{s.fallback_return_days}-day returns)")
    if wb["delivery_days"] < ob["delivery_days"]:
        d = ob["delivery_days"] - wb["delivery_days"]
        bits.append(f"arrives {d} day{'s' if d > 1 else ''} sooner")
    if win.return_window_days > other.return_window_days:
        bits.append(f"{win.return_window_days - other.return_window_days} more days to return it")
    if win.price < other.price:
        bits.append(f"{money(other.price - win.price)} cheaper")
    return "; ".join(bits) or "best overall fit"


# ---------------------------------------------------------------- returns / post-purchase resolution
from .protocol import ResolutionAccept, ResolutionCounter, ResolutionOffer, ReturnRequest  # noqa: E402

COMFORT = ("uncomfortable", "comfort", "hurt", "tight", "pressure", "fit")


def resolution_cost(m: MerchantState, r: ResolutionOffer) -> float:
    """What a resolution costs the merchant."""
    if r.resolution == "refund":
        return m.return_shipping_cost + r.amount * (1 - m.open_box_recovery) + r.goodwill_credit
    if r.resolution == "exchange":
        return m.return_shipping_cost * 2 + r.amount * (1 - m.open_box_recovery) * 0.5 + r.goodwill_credit
    return r.goodwill_credit  # store credit keeps the revenue; only the bonus costs us


def merchant_first_resolution(m: MerchantState, req: ReturnRequest, price: float, product: str
                              ) -> tuple[ResolutionOffer, list[str]]:
    """Lead with what's cheapest for the store that still addresses the customer."""
    goodwill = min(15.0, m.max_goodwill)
    offer = ResolutionOffer(transaction_id=req.transaction_id, resolution="exchange", amount=price,
                            goodwill_credit=goodwill, exchange_for=product)
    refund = ResolutionOffer(transaction_id=req.transaction_id, resolution="refund", amount=price)
    notes = [f"Refund would cost us {money(resolution_cost(m, refund))} (return shipping + open-box resale loss)",
             f"Exchange + {money(goodwill)} goodwill keeps the sale — leading with that"]
    return offer, notes


def shopper_evaluate_resolution(s: ShopperState, offer: ResolutionOffer, reason: str
                                ) -> tuple[ResolutionAccept | ResolutionCounter, list[str]]:
    notes = []
    if offer.resolution == "refund":
        return ResolutionAccept(transaction_id=offer.transaction_id, terms=offer), ["A full refund resolves it"]
    if offer.resolution == "store_credit" and offer.goodwill_credit >= s.store_credit_min_bonus:
        notes.append(f"Store credit with a {money(offer.goodwill_credit)} bonus clears my "
                     f"{money(s.store_credit_min_bonus)} minimum")
        return ResolutionAccept(transaction_id=offer.transaction_id, terms=offer), notes
    if offer.resolution == "exchange" and any(w in reason.lower() for w in COMFORT):
        notes.append("Same model again won't fix a comfort problem — an exchange doesn't resolve it")
    else:
        notes.append(f"{offer.resolution.replace('_', ' ')} with {money(offer.goodwill_credit)} isn't enough")
    return ResolutionCounter(transaction_id=offer.transaction_id, acceptable=[
        {"resolution": "refund"}, {"resolution": "store_credit", "min_bonus": s.store_credit_min_bonus}]), notes


def merchant_resolve_counter(m: MerchantState, c: ResolutionCounter, price: float
                             ) -> tuple[ResolutionOffer | None, list[str]]:
    """Pick the acceptable option that costs the store least, within goodwill authority."""
    options = []
    for a in c.acceptable:
        if a["resolution"] == "refund":
            options.append(ResolutionOffer(transaction_id=c.transaction_id, resolution="refund", amount=price))
        elif a["resolution"] == "store_credit":
            bonus = float(a.get("min_bonus", 0))
            if bonus <= m.max_goodwill:
                options.append(ResolutionOffer(transaction_id=c.transaction_id, resolution="store_credit",
                                               amount=price, goodwill_credit=bonus))
    if not options:
        return None, ["Nothing they'd accept is within my authority"]
    options.sort(key=lambda r: resolution_cost(m, r))
    best = options[0]
    notes = [f"{o.resolution.replace('_', ' ')}: costs us {money(resolution_cost(m, o))}" for o in options]
    notes.append(f"Cheapest acceptable: {best.resolution.replace('_', ' ')}"
                 + (f" + {money(best.goodwill_credit)} bonus (within my {money(m.max_goodwill)} goodwill limit)"
                    if best.goodwill_credit else ""))
    return best, notes
