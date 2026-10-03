"""One negotiation: room + both agents + an event log the UI streams."""
import asyncio
import random
import time
from dataclasses import asdict
from typing import Literal

from .agents.merchant import MerchantAgent
from .agents.shopper import ShopperAgent
from .protocol import Agreement, RoomMessage
from .scenario import MerchantState, Product, ShopperState
from .transport import LocalRoom

Status = Literal["negotiating", "awaiting_approval", "complete", "failed"]


class Deal:
    def __init__(self, pace: float = 1.2):
        self.id = f"deal-{random.randint(1000, 9999)}"
        self.status: Status = "negotiating"
        self.product = Product()
        self.shopper_state = ShopperState()
        self.merchant_state = MerchantState()
        self.agreement: Agreement | None = None
        self.events: list[dict] = []
        self._queues: set[asyncio.Queue] = set()

        self.room = LocalRoom(self.id)
        self.room.subscribe(self._on_room_message)
        self.shopper = ShopperAgent(self.room, self._trace, self.shopper_state, self.product,
                                    on_agreement=self._on_agreement, pace=pace)
        self.merchant = MerchantAgent(self.room, self._trace, self.merchant_state, self.product, pace=pace)

    # ------------------------------------------------------------ events
    def emit(self, type_: str, **data) -> None:
        event = {"type": type_, "ts": time.time(), **data}
        self.events.append(event)
        for q in self._queues:
            q.put_nowait(event)

    def listen(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for e in self.events:
            q.put_nowait(e)
        self._queues.add(q)
        return q

    def unlisten(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def _trace(self, side: str, kind: str, text: str) -> None:
        self.emit("trace", side=side, kind=kind, text=text)

    async def _on_room_message(self, msg: RoomMessage) -> None:
        self.emit("message", message=msg.model_dump(mode="json"))

    def _on_agreement(self, agreement: Agreement) -> None:
        self.agreement = agreement
        self.status = "awaiting_approval" if agreement.human_approval_required else "complete"
        self.emit("status", status=self.status, agreement=agreement.model_dump(mode="json"),
                  why=self.why())

    # ------------------------------------------------------------ lifecycle
    def snapshot(self) -> dict:
        return {
            "id": self.id, "status": self.status, "transport": self.room.transport_name,
            "product": asdict(self.product),
            "shopper": _jsonable(asdict(self.shopper_state)),
            "merchant": _jsonable(asdict(self.merchant_state)),
        }

    async def run(self) -> None:
        self.emit("status", status=self.status)
        await self.shopper.start()

    def why(self) -> list[str]:
        return [*self.merchant.reasons, *self.shopper.reasons,
                "Both agents remained within the authority granted by their owners"]

    def approve(self) -> dict:
        if self.status != "awaiting_approval" or not self.agreement:
            raise ValueError(f"Deal is {self.status}, not awaiting approval")
        terms = self.agreement.terms
        tools = self.merchant.tools
        reservation = tools.reserve_inventory(terms.variant)
        self._trace("merchant", "tool", f"reserve_inventory({terms.variant}) → {reservation['remaining']} left")
        checkout = tools.create_checkout(terms)
        self._trace("merchant", "tool", f"create_checkout(${terms.price:.0f}) → {checkout['order_id']}")
        self.status = "complete"
        self.emit("status", status=self.status, agreement=self.agreement.model_dump(mode="json"),
                  execution={"order_id": checkout["order_id"], "simulated": True})
        return checkout


def _jsonable(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, set):
            v = sorted(v)
        elif hasattr(v, "isoformat"):
            v = v.isoformat()
        out[k] = v
    return out


class DealStore:
    def __init__(self):
        self.deals: dict[str, Deal] = {}
        self._tasks: set[asyncio.Task] = set()

    def create(self, pace: float = 1.2) -> Deal:
        deal = Deal(pace=pace)
        self.deals[deal.id] = deal
        task = asyncio.create_task(deal.run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return deal
