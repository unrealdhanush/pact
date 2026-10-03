from datetime import date

from .. import engine
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

    async def _on_proposal(self, p: Proposal) -> None:
        self.tool(f"get_inventory() → {self.tools.get_inventory()}")
        await self.pause(0.6)
        c = self.tools.get_margin_constraints()
        self.tool(f"get_margin_constraints() → min margin {c['min_margin_pct']:.0f}%, "
                  f"max auto-discount {c['max_auto_discount_pct']:.0f}%")
        await self.pause(0.6)
        result, notes = engine.evaluate_proposal(self.state, p, date.today())
        for n in notes:
            self.think(n)
            await self.pause(0.5)

        if isinstance(result, Rejection):
            await self.room.post(self.name, f"@{SHOPPER} {result.reason}.", result, [SHOPPER])
            return
        for o in result.offers:
            m = self.tools.calculate_offer_margin(o)
            self.tool(f"calculate_offer_margin({o.variant}, ${o.price:.0f}) → "
                      f"{m['margin_pct']}% margin, {m['discount_pct']}% off")
            if o.variant in self.state.overstock:
                self.reasons.append(f"The merchant discounted {o.variant} because {o.variant} inventory is high")
        await self.pause(0.5)

        parts = []
        for o in result.offers:
            if o.variant == p.preferred_variant and o.price > p.requested_price:
                parts.append(f"{o.variant.capitalize()} can't go to ${p.requested_price:.0f} — "
                             f"best I can do on {o.variant} is ${o.price:.0f}.")
            else:
                ship = "free next-day delivery" if o.shipping == "free_next_day" else "standard shipping"
                parts.append(f"{o.variant.capitalize()} I can offer at ${o.price:.0f} with {ship} "
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
            f"@{SHOPPER} Accepted: ${t.price:.0f}, {t.variant}, {ship}, "
            f"{t.return_window_days}-day returns. Unit held pending your customer's approval.",
            result, [SHOPPER],
        )
