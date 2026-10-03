"""One negotiation: room + both agents + an event log the UI streams."""
import asyncio
import os
import random
import time
from dataclasses import asdict
from typing import Literal

from . import jev
from .agents.merchant import MerchantAgent
from .agents.shopper import ShopperAgent
from .agents.zoowork_merchant import ZooWorkMerchantAgent
from .protocol import Agreement, RoomMessage
from .scenario import MerchantState, Product, ShopperState
from .band import BandRoom, load_band_agents
from .transport import LocalRoom
from .zoowork import load_agent_id

Status = Literal["negotiating", "authority_check", "awaiting_approval", "complete", "rejected"]


class Deal:
    def __init__(self, pace: float = 1.2):
        self.id = f"deal-{random.randint(1000, 9999)}"
        self.status: Status = "negotiating"
        self.product = Product()
        self.shopper_state = ShopperState()
        self.merchant_state = MerchantState()
        self.agreement: Agreement | None = None
        self.decision: jev.JevDecision | None = None
        self.events: list[dict] = []
        self._queues: set[asyncio.Queue] = set()
        self.pace = pace
        self.room = None

    async def setup(self) -> None:
        """Open the negotiation room (BAND, else labelled local fallback) and seat both agents."""
        pace = self.pace
        self.room = LocalRoom(self.id)
        self.room_note = ""
        if os.environ.get("PACT_TRANSPORT", "band") == "band" and load_band_agents():
            try:
                self.room = await BandRoom.create(self.id, f"Pact {self.id.upper()} · Aria ANC Headphones")
            except Exception as e:
                self.room_note = f"BAND unavailable ({type(e).__name__}); using local room"
        self.room.subscribe(self._on_room_message)
        self.shopper = ShopperAgent(self.room, self._trace, self.shopper_state, self.product,
                                    on_agreement=self._on_agreement, pace=pace)
        zoowork_id = load_agent_id() if os.environ.get("PACT_MERCHANT", "zoowork") == "zoowork" else None
        if zoowork_id:
            self.merchant = ZooWorkMerchantAgent(self.room, self._trace, self.merchant_state, self.product,
                                                 agent_id=zoowork_id, pace=pace)
            self.merchant_runtime = "ZooWork"
        else:
            self.merchant = MerchantAgent(self.room, self._trace, self.merchant_state, self.product, pace=pace)
            self.merchant_runtime = "local (simulated)"

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

    async def _on_agreement(self, agreement: Agreement) -> None:
        self.agreement = agreement
        self.status = "authority_check"
        self.emit("status", status=self.status, agreement=agreement.model_dump(mode="json"))
        transcript = [f"{m.sender}: {m.text}" for m in self.room.history]
        self.decision = await jev.evaluate(agreement, self.shopper_state, self.merchant_state, transcript)
        self.emit("gate", decision=self.decision.model_dump())
        if self.decision.decision == "AUTO_APPROVE":
            self._execute()
        elif self.decision.decision == "REJECT":
            self.status = "rejected"
            self.room.close()
            self.emit("status", status=self.status, agreement=agreement.model_dump(mode="json"))
        else:
            self.status = "awaiting_approval"
            self.emit("status", status=self.status, agreement=agreement.model_dump(mode="json"),
                      why=self.why())

    # ------------------------------------------------------------ lifecycle
    def snapshot(self) -> dict:
        return {
            "id": self.id, "status": self.status, "transport": self.room.transport_name,
            "band_chat_id": getattr(self.room, "chat_id", None),
            "merchant_runtime": self.merchant_runtime,
            "product": asdict(self.product),
            "shopper": _jsonable(asdict(self.shopper_state)),
            "merchant": _jsonable(asdict(self.merchant_state)),
        }

    async def run(self) -> None:
        if self.room is None:
            await self.setup()
        self.emit("status", status=self.status)
        if self.room_note:
            self._trace("shopper", "think", self.room_note)
        await self.shopper.start()

    def why(self) -> list[str]:
        out = [*self.merchant.reasons, *self.shopper.reasons]
        d = self.decision
        if d and d.decision == "HUMAN_APPROVAL_REQUIRED":
            who = "Jev" if d.source == "jev" else "The authority gate"
            out.append(f"{who} blocked automatic execution: {d.reason}")
        out.append("Both agents remained within the authority granted by their owners")
        return out

    def approve(self) -> dict:
        if self.status != "awaiting_approval" or not self.agreement:
            raise ValueError(f"Deal is {self.status}, not awaiting approval")
        return self._execute()

    def _execute(self) -> dict:
        terms = self.agreement.terms
        tools = self.merchant.tools
        reservation = tools.reserve_inventory(terms.variant)
        self._trace("merchant", "tool", f"reserve_inventory({terms.variant}) → {reservation['remaining']} left")
        checkout = tools.create_checkout(terms)
        self._trace("merchant", "tool", f"create_checkout(${terms.price:.0f}) → {checkout['order_id']}")
        self.status = "complete"
        self.room.close()
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

    async def create(self, pace: float = 1.2) -> Deal:
        deal = Deal(pace=pace)
        await deal.setup()
        self.deals[deal.id] = deal
        task = asyncio.create_task(deal.run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return deal
