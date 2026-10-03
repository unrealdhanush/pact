"""Demo scenario: one merchant (Aria Audio) with a small catalog, one shopper. All mocked locally.

Each product has its own private merchant economics, designed so the three products
end three different ways: Sony (price-match, human approval), Sennheiser (auto-approved
under the shopper's limit), Bose (over budget, the shopper's agent walks away)."""
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class Product:
    id: str = "sony-wh1000xm5"
    name: str = "Sony WH-1000XM5"
    list_price: float = 329.99  # the merchant's shelf price (MSRP $399.99)
    variants: tuple[str, ...] = ("black", "silver")
    specs: str = "Over-ear · industry-leading ANC · 30 h battery"
    search: str = "Sony WH-1000XM5 price"  # live market search (Tavily)
    match: tuple[str, ...] = ("wh1000xm5",)  # tokens a listing title/url must contain


@dataclass
class ShopperState:
    """Private to the shopper's agent."""
    max_price: float = 300
    target_price: float = 279
    preferred_variant: str = "black"
    fallback_variants: list[str] = field(default_factory=lambda: ["silver"])
    delivery_deadline: date = field(default_factory=lambda: next_weekday(date.today(), 1))  # Tuesday
    minimum_return_days: int = 30
    # Willing to take a fallback colour only if returns are extended to this.
    fallback_return_days: int = 45
    approval_required_above: float = 250
    # Price the shopper's agent found elsewhere; the merchant verifies it with Tavily.
    competitor_retailer: str | None = "sony.com"
    competitor_price: float | None = 299.99
    competitor_product_id: str | None = "sony-wh1000xm5"  # the claim only applies to this product
    # What this human weighs most when comparing offers: any of price / colour / speed / returns.
    priorities: list[str] = field(default_factory=list)


@dataclass
class MerchantState:
    """Private to the merchant's agent."""
    list_price: float = 329.99
    unit_cost: float = 230
    min_margin_pct: float = 18  # (net - cost) / net
    max_auto_discount_pct: float = 10
    inventory: dict[str, int] = field(default_factory=lambda: {"black": 2, "silver": 17})
    overstock: set[str] = field(default_factory=lambda: {"silver"})
    # Scarce variants are not discounted below this.
    variant_floor: dict[str, float] = field(default_factory=lambda: {"black": 319.99})
    standard_shipping_days: int = 5
    next_day_shipping_cost: float = 12
    standard_return_days: int = 30
    max_return_days: int = 45
    return_cost_per_extra_day: float = 0.10


def next_weekday(d: date, weekday: int) -> date:
    """Next date strictly after d falling on weekday (Mon=0)."""
    days = (weekday - d.weekday()) % 7 or 7
    return d + timedelta(days=days)


# Public listings (what any shopper agent can see) + each product's private merchant economics.
CATALOG: dict[str, tuple[Product, dict]] = {
    "sony-wh1000xm5": (Product(), {}),  # MerchantState defaults are the Sony economics
    "sennheiser-m4": (
        Product(id="sennheiser-m4", name="Sennheiser Momentum 4", list_price=209.99,
                variants=("black", "white"), specs="Over-ear · adaptive ANC · 60 h battery",
                search="Sennheiser Momentum 4 Wireless price", match=("momentum4wireless",)),
        dict(list_price=209.99, unit_cost=145, inventory={"black": 9, "white": 4}, overstock={"black"},
             variant_floor={}),
    ),
    "bose-qc-ultra": (
        Product(id="bose-qc-ultra", name="Bose QuietComfort Ultra (2nd Gen)", list_price=449.00,
                variants=("black", "white"), specs="Over-ear · immersive audio · 30 h battery",
                search="Bose QuietComfort Ultra Headphones 2nd Gen price", match=("quietcomfortultra", "2ndgen")),
        dict(list_price=449.00, unit_cost=315, inventory={"black": 5, "white": 6}, overstock=set(),
             variant_floor={}),
    ),
}


# Competing merchants. Each is its own BAND agent with its own private economics.
MERCHANTS = {
    "aria": {"name": "Aria Audio", "band_agent": "MerchantAgent", "key_env": "BAND_MERCHANT_AGENT_KEY",
             "runtime": "zoowork"},
    "soundhub": {"name": "SoundHub", "band_agent": "SoundHubAgent", "key_env": "BAND_SOUNDHUB_AGENT_KEY",
                 "runtime": "local"},
}

# SoundHub: slightly cheaper shelf prices and free 3-day standard shipping (still arrives by Tuesday),
# deep in black, but only 30-day returns and no silver.
SOUNDHUB = {
    "sony-wh1000xm5": dict(list_price=319.99, unit_cost=232, inventory={"black": 12, "silver": 0},
                           overstock={"black"}, variant_floor={}, standard_shipping_days=3, max_return_days=30),
    "sennheiser-m4": dict(list_price=204.99, unit_cost=142, inventory={"black": 7, "white": 2},
                          overstock={"black"}, variant_floor={}, standard_shipping_days=3, max_return_days=30),
    "bose-qc-ultra": dict(list_price=429.00, unit_cost=305, inventory={"black": 3, "white": 3},
                          overstock=set(), variant_floor={}, standard_shipping_days=3, max_return_days=30),
}


def product(product_id: str) -> Product:
    return CATALOG[product_id][0]


def merchant_state(product_id: str, merchant: str = "aria") -> MerchantState:
    return MerchantState(**(CATALOG[product_id][1] if merchant == "aria" else SOUNDHUB[product_id]))
