from datetime import date

from .. import engine
from ..engine import money
from ..tavily import verify_competitor_price
from ..protocol import Agreement, ConditionalAccept, Proposal, Rejection
from ..scenario import MerchantState, Product
from .base import Agent
from .merchant_tools import MerchantTools

SHOPPER = "ShopperAgent"


def _day(d) -> str:
    return d.strftime("%a %b %-d")


class MerchantAgent(Agent):
    """Local merchant agent. Same tools the ZooWork-hosted version will use."""
    name = "MerchantAgent"
    side = "merchant"

    def __init__(self, room, trace, state: MerchantState, product: Product, **kw):
        super().__init__(room, trace, **kw)
        self.state = state
        self.tools = MerchantTools(state, product)

    async def handle(self, payload) -> None:
        if isinstance(payload, Proposal):
            await self._on_proposal(payload)
        elif isinstance(payload, ConditionalAccept):
            await self._on_conditional(payload)
        elif isinstance(payload, Agreement):
            self.think("Shopper confirmed; unit held pending authority check")

    async def verify_claim(self, p: Proposal):
        """Verify the shopper's competitor price with Tavily (only if one was cited)."""
        if not p.competitor_claim:
            return None
        c = p.competitor_claim
        check = await verify_competitor_price(self.tools.product.name, c.retailer, c.price)
        label = {"tavily": "live", "cache": f"CACHED from {check.checked_at}"}.get(check.source, check.source)
        self.tool(f"verify_competitor_price({c.retailer}, {money(c.price)}) → "
                  f"{'verified' if check.verified else 'NOT verified'} [Tavily {label}]")
        if check.verified:
            self.reasons.append(f"The merchant price-matched {c.retailer} after verifying "
                                f"{money(check.found_price)} with Tavily")
        return check

    async def _on_proposal(self, p: Proposal) -> None:
        self.tool(f"get_inventory() → {self.tools.get_inventory()}")
        await self.pause(0.6)
        c = self.tools.get_margin_constraints()
        self.tool(f"get_margin_constraints() → min margin {c['min_margin_pct']:.0f}%, "
                  f"max auto-discount {c['max_auto_discount_pct']:.0f}%")
        await self.pause(0.6)
        check = await self.verify_claim(p)
        result, notes = engine.evaluate_proposal(self.state, p, date.today(), check)
        for n in notes:
            self.think(n)
            await self.pause(0.5)

        if isinstance(result, Rejection):
            await self.room.post(self.name, f"@{SHOPPER} {result.reason}.", result, [SHOPPER])
            return
        for o in result.offers:
            m = self.tools.calculate_offer_margin(o)
            self.tool(f"calculate_offer_margin({o.variant}, {money(o.price)}) → "
                      f"{m['margin_pct']}% margin, {m['discount_pct']}% off")
            if o.variant in self.state.overstock:
                self.reasons.append(f"The merchant discounted {o.variant} because {o.variant} inventory is high")
        await self.pause(0.5)

        parts = []
        for o in result.offers:
            if o.variant == p.preferred_variant and o.price > p.requested_price:
                parts.append(f"{o.variant.capitalize()} can't go to {money(p.requested_price)} — "
                             f"best I can do on {o.variant} is {money(o.price)}.")
            else:
                ship = "free next-day delivery" if o.shipping == "free_next_day" else "standard shipping"
                cc = result.competitor_check
                if cc and cc["verified"] and o.variant in self.state.overstock:
                    parts.append(f"I checked {cc['retailer']} and confirmed {money(cc['found_price'])} — I'll match it.")
                parts.append(f"{o.variant.capitalize()} I can offer at {money(o.price)} with {ship} "
                             f"(arrives {_day(o.delivery_date)}), {o.return_window_days}-day returns.")
        await self.room.post(self.name, f"@{SHOPPER} " + " ".join(parts), result, [SHOPPER])

    async def _on_conditional(self, c: ConditionalAccept) -> None:
        if c.conditions:
            self.think(f"Shopper wants changes: {c.conditions}")
        await self.pause(0.6)
        result, notes = engine.evaluate_conditions(self.state, c)
        for n in notes:
            self.think(n)
            await self.pause(0.5)
        if isinstance(result, Rejection):
            await self.room.post(self.name, f"@{SHOPPER} {result.reason}.", result, [SHOPPER])
            return
        t = result.terms
        m = self.tools.calculate_offer_margin(t)
        self.tool(f"calculate_offer_margin(final) → {m['margin_pct']}% margin")
        if c.conditions:
            self.reasons.append(f"The merchant extended returns to {t.return_window_days} days because "
                                f"margin stayed above its required threshold")
        ship = "free next-day delivery" if t.shipping == "free_next_day" else "standard shipping"
        await self.room.post(
            self.name,
            f"@{SHOPPER} Accepted: {money(t.price)}, {t.variant}, {ship}, "
            f"{t.return_window_days}-day returns. Unit held pending your customer's approval.",
            result, [SHOPPER],
        )
