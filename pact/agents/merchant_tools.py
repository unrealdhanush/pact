"""Merchant tools. These are the functions the ZooWork merchant agent will be
given; for now they run locally against mocked merchant data."""
import uuid
from dataclasses import asdict

from .. import engine
from ..protocol import Offer
from ..scenario import MerchantState, Product


class MerchantTools:
    def __init__(self, state: MerchantState, product: Product):
        self.state = state
        self.product = product

    def get_product(self) -> dict:
        return asdict(self.product)

    def get_inventory(self) -> dict[str, int]:
        return dict(self.state.inventory)

    def get_margin_constraints(self) -> dict:
        m = self.state
        return {"min_margin_pct": m.min_margin_pct, "max_auto_discount_pct": m.max_auto_discount_pct,
                "variant_floor": m.variant_floor, "max_return_days": m.max_return_days}

    def calculate_offer_margin(self, offer: Offer) -> dict:
        return {"margin_pct": round(engine.margin_pct(self.state, offer), 1),
                "discount_pct": round(engine.discount_pct(self.state, offer.price), 1),
                "within_authority": engine.within_authority(self.state, offer)}

    def reserve_inventory(self, variant: str) -> dict:
        self.state.inventory[variant] -= 1
        return {"variant": variant, "remaining": self.state.inventory[variant], "simulated": True}

    def create_checkout(self, offer: Offer) -> dict:
        return {"order_id": f"ord_{uuid.uuid4().hex[:8]}", "amount": offer.price, "simulated": True}
