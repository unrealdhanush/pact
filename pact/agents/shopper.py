from .. import engine
from ..engine import money
from ..protocol import Agreement, ConditionalAccept, Counteroffer, MerchantAccept, Rejection
from ..scenario import Product, ShopperState
from .base import Agent

MERCHANT = "MerchantAgent"


def _day(d) -> str:
    return d.strftime("%a %b %-d")


class ShopperAgent(Agent):
    name = "ShopperAgent"
    side = "shopper"

    def __init__(self, room, trace, state: ShopperState, product: Product, on_agreement, **kw):
        super().__init__(room, trace, **kw)
        self.state = state
        self.product = product
        self.on_agreement = on_agreement

    async def start(self) -> None:
        s = self.state
        self.think(f"Owner wants {self.product.name}; budget ceiling stays private")
        await self.pause(0.6)
        self.think(f"Opening below ceiling at {money(engine.opening_price(s, self.product.list_price))}")
        if s.competitor_price and s.competitor_product_id in (None, self.product.id):
            self.think(f"Found it at {s.competitor_retailer} for {money(s.competitor_price)} — citing it as leverage")
        p = engine.make_proposal(s, self.room.id, self.product.id, self.product.list_price)
        await self.pause()
        await self.room.post(
            self.name,
            f"@{MERCHANT} My customer wants the {self.product.name} in {s.preferred_variant}. "
            f"Can you do {money(p.requested_price)} with delivery by {_day(s.delivery_deadline)}? "
            f"They need at least a {s.minimum_return_days}-day return window."
            + (f" For reference, {p.competitor_claim.retailer} lists it at {money(p.competitor_claim.price)}."
               if p.competitor_claim else ""),
            p, [MERCHANT],
        )

    async def handle(self, payload) -> None:
        if isinstance(payload, Counteroffer):
            await self._on_counter(payload)
        elif isinstance(payload, MerchantAccept):
            await self._on_accept(payload)
        elif isinstance(payload, Rejection):
            self.think(f"Merchant walked away: {payload.reason}")

    async def _on_counter(self, c: Counteroffer) -> None:
        self.think("Checking counteroffer against owner's boundaries")
        await self.pause(0.8)
        result, notes = engine.evaluate_counteroffer(self.state, c)
        for n in notes:
            self.think(n)
            await self.pause(0.5)

        if isinstance(result, Rejection):
            await self.room.post(self.name, f"@{MERCHANT} None of those work for my customer. Passing.",
                                 result, [MERCHANT])
            return

        o = result.offer
        rejected = [x for x in c.offers if x != o]
        lead = " ".join(f"{x.variant.capitalize()} at {money(x.price)} is outside my customer's budget."
                        for x in rejected if x.price > self.state.max_price)
        if result.conditions:
            if o.variant != self.state.preferred_variant:
                self.reasons.append(f"You accepted {o.variant} because your colour preference was flexible")
                self.reasons.append(f"Your agent made {o.variant} conditional on "
                                    f"{result.conditions['return_window_days']}-day returns")
            text = (f"@{MERCHANT} {lead} My customer will take {o.variant} at {money(o.price)} "
                    f"if the return window is extended to {result.conditions['return_window_days']} days.")
        else:
            text = f"@{MERCHANT} {lead} We'll take {o.variant} at {money(o.price)} as offered."
        await self.room.post(self.name, text.replace("  ", " "), result, [MERCHANT])

    async def _on_accept(self, a: MerchantAccept) -> None:
        self.think("Verifying final terms")
        await self.pause(0.8)
        agreement, notes = engine.finalize(self.state, a.transaction_id, a.terms, self.product.list_price)
        for n in notes:
            self.think(n)
            await self.pause(0.5)
        if isinstance(agreement, Rejection):
            await self.room.post(self.name, f"@{MERCHANT} Can't confirm: {agreement.reason}",
                                 agreement, [MERCHANT])
            return
        text = (f"@{MERCHANT} Confirmed on my side. I'm comparing offers from other merchants before "
                f"anything executes." if getattr(self, "comparing", False) else
                f"@{MERCHANT} Confirmed on my side. Sending the agreement for authority check before "
                f"anything executes.")
        await self.room.post(self.name, text, agreement, [MERCHANT])
        await self.pause(0.3)  # let the room message land before the authority gate
        self.on_agreement(agreement)
