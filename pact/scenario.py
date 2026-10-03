"""Hero scenario: one product, one shopper, one merchant. All mocked locally."""
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class Product:
    id: str = "headphones-001"
    name: str = "Aria ANC Headphones"
    list_price: float = 249
    variants: tuple[str, ...] = ("black", "silver")


@dataclass
class ShopperState:
    """Private to the shopper's agent."""
    max_price: float = 220
    target_price: float = 215
    preferred_variant: str = "black"
    fallback_variants: list[str] = field(default_factory=lambda: ["silver"])
    delivery_deadline: date = field(default_factory=lambda: next_weekday(date.today(), 1))  # Tuesday
    minimum_return_days: int = 30
    # Willing to take a fallback colour only if returns are extended to this.
    fallback_return_days: int = 45
    approval_required_above: float = 200


@dataclass
class MerchantState:
    """Private to the merchant's agent."""
    list_price: float = 249
    unit_cost: float = 168
    min_margin_pct: float = 18  # (net - cost) / net
    max_auto_discount_pct: float = 13
    inventory: dict[str, int] = field(default_factory=lambda: {"black": 2, "silver": 17})
    overstock: set[str] = field(default_factory=lambda: {"silver"})
    # Scarce variants are not discounted below this.
    variant_floor: dict[str, float] = field(default_factory=lambda: {"black": 235})
    standard_shipping_days: int = 5
    next_day_shipping_cost: float = 12
    standard_return_days: int = 30
    max_return_days: int = 45
    return_cost_per_extra_day: float = 0.10


def next_weekday(d: date, weekday: int) -> date:
    """Next date strictly after d falling on weekday (Mon=0)."""
    days = (weekday - d.weekday()) % 7 or 7
    return d + timedelta(days=days)
