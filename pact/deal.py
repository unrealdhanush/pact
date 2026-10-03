"""One negotiation: room + both agents + authority gate + an event log the UI streams."""
import asyncio
import logging
import os
import random
import time
from dataclasses import asdict
from typing import Literal

from . import gate
from .agents.merchant import MerchantAgent
from .agents.shopper import ShopperAgent
from .agents.zoowork_merchant import ZooWorkMerchantAgent
from .band import BandConfig, BandRoom, bootstrap_agents
from .protocol import Agreement, RoomMessage
from .scenario import MerchantState, Product, ShopperState
from .engine import money
from .transport import LocalRoom
from .zoowork import load_agent_id

log = logging.getLogger("pact.deal")

Status = Literal["negotiating", "awaiting_approval", "complete", "failed"]


class Deal:
    def __init__(self, pace: float = 1.2, deal_id: str | None = None, band: BandConfig | None = None,
                 shopper_state: ShopperState | None = None, on_complete=None):
        self.id = deal_id or f"deal-{random.randint(1000, 9999)}"
        self.pace = pace
        self.status: Status = "negotiating"
        self.phase = "setup"
        self.product = Product()
        self.shopper_state = shopper_state or ShopperState()
        self.on_complete = on_complete  # async callback(deal) after execution, e.g. remember the outcome
        self.merchant_state = MerchantState()
        self.agreement: Agreement | None = None
        self.authority: dict | None = None
        self.execution: dict | None = None
        self.failure: str | None = None
        self.events: list[dict] = []
        self._queues: set[asyncio.Queue] = set()
        self._tasks: set[asyncio.Task] = set()
        self._band = band
        self.room: LocalRoom | BandRoom | None = None
        self.shopper: ShopperAgent | None = None
        self.merchant: MerchantAgent | None = None

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

    def _set_phase(self, phase: str, **data) -> None:
        self.phase = phase
        self.emit("phase", phase=phase, **data)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _on_room_message(self, msg: RoomMessage) -> None:
        self.emit("message", message=msg.model_dump(mode="json"))
        payload = msg.payload or {}
        if payload.get("kind") == "rejection" and self.status == "negotiating":
            self._fail(f"{payload.get('party', 'agent')} walked away: {payload.get('reason', '')}")

    def _on_room_status(self, status: dict) -> None:
        self.emit("room", room=status)

    # ------------------------------------------------------------ setup
    async def setup(self) -> None:
        if self.shopper is not None:
            return
        if self.room is None:
            try:
                cfg = self._band or await bootstrap_agents()
                self.room = await BandRoom.create(self.id, cfg) if cfg else LocalRoom(self.id)
            except Exception as e:  # noqa: BLE001 - never block the demo on BAND
                log.warning("BAND room setup failed: %s", e)
                self.room = LocalRoom(self.id, fallback_reason=f"BAND setup failed: {e}")
        if hasattr(self.room, "on_status"):
            self.room.on_status = self._on_room_status
        self.room.subscribe(self._on_room_message)
        self.shopper = ShopperAgent(self.room, self._trace, self.shopper_state, self.product,
                                    on_agreement=self._on_agreement, pace=self.pace)
        zoowork_id = load_agent_id() if os.environ.get("PACT_MERCHANT", "zoowork") == "zoowork" else None
        if zoowork_id:  # ZooWork runs the merchant's reasoning; falls back to local logic per turn on failure
            self.merchant = ZooWorkMerchantAgent(self.room, self._trace, self.merchant_state, self.product,
                                                 agent_id=zoowork_id, pace=self.pace)
        else:
            self.merchant = MerchantAgent(self.room, self._trace, self.merchant_state, self.product,
                                          pace=self.pace)
        self.emit("room", room=self.room.status())

    async def run(self) -> None:
        await self.setup()
        self._set_phase("negotiating")
        self.emit("status", status=self.status)
        await self.shopper.start()

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        if self.room is not None:
            await self.room.close()

    # ------------------------------------------------------------ authority gate
    def _on_agreement(self, agreement: Agreement) -> asyncio.Task:
        """Starts the authority gate. Returns the gate task, so the shopper may `await` it or not."""
        self.agreement = agreement
        self._set_phase("checking_authority", agreement=agreement.model_dump(mode="json"))
        task = asyncio.create_task(self._gate(agreement))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _gate(self, agreement: Agreement) -> None:
        if self.pace:
            await asyncio.sleep(min(self.pace, 1.0))
        try:
            transcript = [f"{m.sender}: {m.text}" for m in self.room.history]
            decision = await gate.evaluate(agreement, self.shopper_state, self.merchant_state,
                                           transcript=transcript)
        except Exception as e:  # noqa: BLE001 - fail closed
            log.exception("authority gate crashed")
            decision = {**gate.local_decision(agreement, self.shopper_state, self.merchant_state),
                        "source_label": f"{gate.LOCAL_LABEL} (gate error: {e})"}
            if decision["decision"] == "AUTO_APPROVE":
                decision["decision"] = "HUMAN_APPROVAL_REQUIRED"
        self.authority = decision
        self.emit("authority", decision=decision)
        self._trace("shopper", "think", f"Jev gate → {decision['decision']}: {decision['reason']}")
        self._spawn(self.room.post_event(
            f"Pact authority check for {self.room.status()['title']}: {decision['decision']} — {decision['reason']}",
            "task", {"decision": decision["decision"], "merchant_policy_ok": decision["merchant_policy_ok"],
                     "shopper_policy_ok": decision["shopper_policy_ok"], "source": decision.get("source")}))

        if decision["decision"] == "AUTO_APPROVE":
            self._execute(approved_by="policy")
        elif decision["decision"] == "HUMAN_APPROVAL_REQUIRED":
            self.status = "awaiting_approval"
            self._set_phase("awaiting_approval")
            self.emit("status", status=self.status, agreement=agreement.model_dump(mode="json"),
                      authority=decision, why=self.why())
        else:
            self._fail(decision["reason"])

    def _fail(self, reason: str) -> None:
        self.status = "failed"
        self.failure = reason
        self._set_phase("failed")
        self.emit("status", status=self.status, reason=reason,
                  agreement=self.agreement.model_dump(mode="json") if self.agreement else None,
                  authority=self.authority)

    # ------------------------------------------------------------ lifecycle
    def snapshot(self) -> dict:
        return {
            "id": self.id, "status": self.status, "phase": self.phase,
            "transport": self.room.transport_name if self.room else "not connected",
            "room": self.room.status() if self.room else None,
            "product": asdict(self.product),
            "shopper": _jsonable(asdict(self.shopper_state)),
            "merchant": _jsonable(asdict(self.merchant_state)),
            "agreement": self.agreement.model_dump(mode="json") if self.agreement else None,
            "authority": self.authority, "execution": self.execution, "failure": self.failure,
        }

    def why(self) -> list[str]:
        reasons = [*(self.merchant.reasons if self.merchant else []),
                   *(self.shopper.reasons if self.shopper else []),
                   "Both agents remained within the authority granted by their owners"]
        if self.authority:
            d = self.authority
            if d["decision"] == "HUMAN_APPROVAL_REQUIRED":
                reasons.append(f"Jev blocked automatic execution: {d['reason']}")
            else:
                reasons.append(f"Jev decision {d['decision']}: {d['reason']}")
        return reasons

    def approve(self) -> dict:
        if (self.status != "awaiting_approval" or not self.agreement or not self.authority
                or self.authority["decision"] != "HUMAN_APPROVAL_REQUIRED"):
            raise ValueError(f"Deal is {self.status}, not awaiting approval")
        return self._execute(approved_by="human")

    def _execute(self, approved_by: str) -> dict:
        terms = self.agreement.terms
        tools = self.merchant.tools
        reservation = tools.reserve_inventory(terms.variant)
        self._trace("merchant", "tool", f"reserve_inventory({terms.variant}) → {reservation['remaining']} left")
        checkout = tools.create_checkout(terms)
        self._trace("merchant", "tool", f"create_checkout({money(terms.price)}) → {checkout['order_id']}")
        self.status = "complete"
        self.execution = {"order_id": checkout["order_id"], "amount": checkout.get("amount", terms.price),
                          "simulated": bool(checkout.get("simulated", True)), "approved_by": approved_by,
                          "approved_at": time.time()}
        self._set_phase("complete")
        if self.on_complete is not None:
            self._spawn(self.on_complete(self))
        self.emit("status", status=self.status, agreement=self.agreement.model_dump(mode="json"),
                  authority=self.authority, execution=self.execution, why=self.why())
        if self.room is not None:
            who = "the shopper's human" if approved_by == "human" else "policy (auto-approve)"
            self._spawn(self.room.post_event(
                f"Approved by {who}. Checkout {checkout['order_id']} for {money(terms.price)}"
                f"{' (simulated — no real payment)' if self.execution['simulated'] else ''}.",
                "task", {"order_id": checkout["order_id"], "approved_by": approved_by,
                         "simulated": self.execution["simulated"]}))
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

    async def create(self, pace: float = 1.2, deal_id: str | None = None,
                     shopper_state: ShopperState | None = None, on_complete=None) -> Deal:
        old = self.deals.pop(deal_id, None) if deal_id else None
        if old is not None:
            await old.close()
        deal = Deal(pace=pace, deal_id=deal_id, shopper_state=shopper_state, on_complete=on_complete)
        await deal.setup()
        self.deals[deal.id] = deal
        task = asyncio.create_task(deal.run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return deal
