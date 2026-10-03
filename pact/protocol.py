"""Wire contracts exchanged between agents in the negotiation room.

Only these payloads cross the room boundary. Private state (budgets, floors,
inventory counts) never does.
"""
from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class Offer(BaseModel):
    price: float
    variant: str
    shipping: Literal["standard", "free_next_day"]
    delivery_date: date
    return_window_days: int


class CompetitorClaim(BaseModel):
    retailer: str
    price: float


class Proposal(BaseModel):
    kind: Literal["proposal"] = "proposal"
    transaction_id: str
    product_id: str
    requested_price: float
    preferred_variant: str
    acceptable_variants: list[str]
    delivery_deadline: date
    minimum_return_days: int
    requires_human_approval: bool
    competitor_claim: CompetitorClaim | None = None


class Counteroffer(BaseModel):
    kind: Literal["counteroffer"] = "counteroffer"
    transaction_id: str
    status: Literal["counteroffer"] = "counteroffer"
    offers: list[Offer]
    merchant_margin_valid: bool
    requires_human_approval: bool
    explanation: list[str]
    # Public result of verifying the shopper's competitor claim (Tavily), if one was made.
    competitor_check: dict | None = None


class ConditionalAccept(BaseModel):
    """Shopper accepts an offer provided some terms change."""
    kind: Literal["conditional_accept"] = "conditional_accept"
    transaction_id: str
    offer: Offer
    conditions: dict[str, int]


class MerchantAccept(BaseModel):
    kind: Literal["merchant_accept"] = "merchant_accept"
    transaction_id: str
    terms: Offer
    explanation: list[str]


class Rejection(BaseModel):
    kind: Literal["rejection"] = "rejection"
    transaction_id: str
    party: Literal["shopper", "merchant"]
    reason: str


class Agreement(BaseModel):
    kind: Literal["agreement"] = "agreement"
    transaction_id: str
    status: Literal["agreement_ready"] = "agreement_ready"
    terms: Offer
    list_price: float
    shopper_savings: float
    human_approval_required: bool


# ---------------------------------------------------------------- post-purchase resolution (returns)
Resolution = Literal["refund", "exchange", "store_credit"]


class ReturnRequest(BaseModel):
    kind: Literal["return_request"] = "return_request"
    transaction_id: str
    order_id: str
    reason: str
    wants: Resolution = "refund"


class ResolutionOffer(BaseModel):
    kind: Literal["resolution_offer"] = "resolution_offer"
    transaction_id: str
    resolution: Resolution
    amount: float  # refund / credit value (the purchase price)
    goodwill_credit: float = 0
    exchange_for: str | None = None


class ResolutionCounter(BaseModel):
    """Shopper: what would resolve it (any one of these)."""
    kind: Literal["resolution_counter"] = "resolution_counter"
    transaction_id: str
    acceptable: list[dict]  # e.g. [{"resolution": "refund"}, {"resolution": "store_credit", "min_bonus": 30}]


class ResolutionAccept(BaseModel):
    kind: Literal["resolution_accept"] = "resolution_accept"
    transaction_id: str
    terms: ResolutionOffer


Payload = Annotated[
    Union[Proposal, Counteroffer, ConditionalAccept, MerchantAccept, Rejection, Agreement,
          ReturnRequest, ResolutionOffer, ResolutionCounter, ResolutionAccept],
    Field(discriminator="kind"),
]
payload_adapter: TypeAdapter[Payload] = TypeAdapter(Payload)


class RoomMessage(BaseModel):
    id: str
    room: str
    sender: str
    mentions: list[str]
    text: str
    payload: dict | None = None
    ts: float
