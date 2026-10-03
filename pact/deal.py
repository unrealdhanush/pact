"""One negotiation: room + both agents + authority gate + an event log the UI streams."""
import asyncio
import logging
import os
import random
import time
from dataclasses import asdict
from typing import Literal

from . import discovery, gate, jev
from .agents.merchant import MerchantAgent
from .agents.shopper import ShopperAgent
from .agents.zoowork_merchant import ZooWorkMerchantAgent
from .band import BandConfig, BandRoom, bootstrap_agents
from .protocol import Agreement, RoomMessage
from . import scenario
from .scenario import ShopperState
from .engine import money
from .transport import LocalRoom
from .zoowork import load_agent_id

log = logging.getLogger("pact.deal")

Status = Literal["negotiating", "awaiting_exception", "awaiting_approval", "complete", "failed"]


class Deal:
    def __init__(self, pace: float = 1.2, deal_id: str | None = None, band: BandConfig | None = None,
                 shopper_state: ShopperState | None = None, on_complete=None,
                 product_id: str = "sony-wh1000xm5", merchant_id: str = "aria",
                 discover: bool = True, hold_gate: bool = False):
        self.id = deal_id or f"deal-{random.randint(1000, 9999)}"
        self.pace = pace
        self.status: Status = "negotiating"
        self.phase = "setup"
        self.product = scenario.product(product_id)
        self.shopper_state = shopper_state or ShopperState()
        self.on_complete = on_complete  # async callback(deal) after execution, e.g. remember the outcome
        self.merchant_id = merchant_id
        self.merchant_info = scenario.MERCHANTS[merchant_id]
        self.merchant_state = scenario.merchant_state(product_id, merchant_id)
        self.discover = discover
        self.hold_gate = hold_gate  # a Hunt compares agreements first, then releases the winner's gate
        self.agreed = asyncio.Event()  # set when this negotiation settles: agreement, failure or a pending exception
        self.exception: dict | None = None  # over-budget offer waiting on the human
        self._exception_future: asyncio.Future | None = None
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
                if cfg and self.discover:
                    await self._discover(cfg)
                self.room = await BandRoom.create(self.id, cfg) if cfg else LocalRoom(self.id)
            except Exception as e:  # noqa: BLE001 - never block the demo on BAND
                log.warning("BAND room setup failed: %s", e)
                self.room = LocalRoom(self.id, fallback_reason=f"BAND setup failed: {e}")
        if hasattr(self.room, "on_status"):
            self.room.on_status = self._on_room_status
        self.room.subscribe(self._on_room_message)
        self.shopper = ShopperAgent(self.room, self._trace, self.shopper_state, self.product,
                                    on_agreement=self._on_agreement, pace=self.pace)
        self.shopper.comparing = self.hold_gate
        self.shopper.on_near_miss = self._near_miss
        self.shopper.on_human_exception = self._human_exception
        zoowork_id = (load_agent_id() if os.environ.get("PACT_MERCHANT", "zoowork") == "zoowork"
                      and self.merchant_info["runtime"] == "zoowork" else None)
        if zoowork_id:  # ZooWork runs the merchant's reasoning; falls back to local logic per turn on failure
            self.merchant = ZooWorkMerchantAgent(self.room, self._trace, self.merchant_state, self.product,
                                                 agent_id=zoowork_id, pace=self.pace)
        else:
            self.merchant = MerchantAgent(self.room, self._trace, self.merchant_state, self.product,
                                          pace=self.pace)
        self.emit("room", room=self.room.status())

    async def _discover(self, cfg) -> None:
        """Shopper agent searches BAND's agent directory for a merchant that sells the product."""
        self._trace("shopper", "think", f"Searching BAND's agent directory for merchants selling the {self.product.name}…")
        try:
            found = await discovery.discover_merchant(self.product.name, cfg)
        except Exception as e:  # noqa: BLE001 - discovery is best-effort; the configured merchant still works
            self._trace("shopper", "think", f"BAND directory unavailable ({type(e).__name__}); using known MerchantAgent")
            return
        for c in found["candidates"]:
            self._trace("shopper", "tool", f"band_lookup_peers → {c['name']} · relevance {c['score']:.2f}")
        if found["chosen"]:
            self._trace("shopper", "think", f"Best match: @{found['chosen']['name']} "
                        f"(ranked by {'Moss' if found['ranker'] == 'moss' else 'keywords'} in {found['ms']} ms) — "
                        f"inviting it to the deal room")
        self.emit("discovery", **found)

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
        self.agreed.set()
        if self.hold_gate:  # the Hunt decides which agreement goes to the authority gate
            self._set_phase("agreed", agreement=agreement.model_dump(mode="json"))
            return None
        return self.release_gate()

    async def _near_miss(self, nm: dict) -> str:
        """No offer fits: Jev (inside code rules) decides whether to ask the human or walk away."""
        transcript = [f"{m.sender}: {m.text}" for m in self.room.history]
        d = await jev.near_miss_decision(nm, self.shopper_state, self.merchant_info["name"], transcript)
        o = nm["offer"]
        self.exception = {"merchant": self.merchant_id, "merchant_name": self.merchant_info["name"],
                          "offer": o.model_dump(mode="json"), "over_by": nm["over_by"], "over_pct": nm["over_pct"],
                          "budget": nm["budget"], "decision": d}
        self._trace("shopper", "think", f"No offer fits. Best: {self.merchant_info['name']} {money(o.price)} "
                    f"{o.variant}, {money(nm['over_by'])} over → {d['decision']} ({d['source']}): {d['reason']}")
        self.emit("near_miss", **self.exception)
        if d["decision"] != "ASK_HUMAN":
            self.exception = None
        return "ask" if d["decision"] == "ASK_HUMAN" else "walk"

    async def _human_exception(self, nm: dict) -> bool:
        self._exception_future = asyncio.get_running_loop().create_future()
        if self.hold_gate:
            self.agreed.set()  # let the Hunt decide whether this is the offer to put to the human
        else:
            self.status = "awaiting_exception"
            self._set_phase("awaiting_exception")
            self.emit("status", status=self.status, exception=self.exception)
        return await self._exception_future

    def resolve_exception(self, accept: bool) -> None:
        if self._exception_future is None or self._exception_future.done():
            raise ValueError("No over-budget offer is waiting for an answer")
        self.status = "negotiating"
        if accept:
            self._set_phase("negotiating")
        self._exception_future.set_result(accept)

    def release_gate(self) -> asyncio.Task:
        agreement = self.agreement
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
        self.agreed.set()  # a Hunt waiting on this deal can stop waiting
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
        self._spawn(self._track(checkout["order_id"]))
        return checkout

    async def _track(self, order_id: str) -> None:
        """Post-purchase tracking (simulated carrier, sped-up demo clock). The merchant agent posts each
        update into the same BAND room, so the deal and its fulfilment share one auditable thread."""
        from datetime import date, datetime, timedelta
        t = self.agreement.terms
        tracking_no = f"PCT{abs(hash(order_id)) % 10**9:09d}"
        ship_day = date.today() if t.shipping == "free_next_day" else date.today() + timedelta(days=1)
        stages = [
            ("confirmed", f"Order {order_id} confirmed by {self.merchant_info['name']}", date.today()),
            ("packed", "Packed at the warehouse", date.today()),
            ("shipped", f"Shipped · {'next-day air' if t.shipping == 'free_next_day' else 'ground'} · {tracking_no}", ship_day),
            ("out_for_delivery", "Out for delivery", t.delivery_date),
            ("delivered", f"Delivered · {t.return_window_days}-day return window starts", t.delivery_date),
        ]
        step = float(os.environ.get("PACT_TRACKING_STEP_S", "6"))
        for i, (key, label, when) in enumerate(stages):
            if i:
                await asyncio.sleep(step)
            self.emit("tracking", stage=key, index=i, total=len(stages), label=label, date=when.isoformat(),
                      tracking_no=tracking_no, merchant_name=self.merchant_info["name"], simulated=True)
            if self.room is not None:
                try:
                    await self.room.post_event(f"Tracking {tracking_no}: {label} ({when:%a %b %-d})", "task",
                                               {"order_id": order_id, "stage": key, "simulated": True},
                                               sender="MerchantAgent")
                except Exception as e:  # noqa: BLE001 - tracking is best-effort
                    log.warning("tracking event failed: %s", e)


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
                     shopper_state: ShopperState | None = None, on_complete=None,
                     product_id: str = "sony-wh1000xm5", shop_around: bool = False,
                     preference: str = "best") -> Deal:
        old = self.deals.pop(deal_id, None) if deal_id else None
        if old is not None:
            await old.close()
        if shop_around:  # negotiate with every merchant in parallel, keep the best agreement
            from .hunt import Hunt
            deal = Hunt(pace=pace, hunt_id=deal_id, shopper_state=shopper_state, product_id=product_id,
                        preference=preference, on_complete=on_complete)
        else:
            deal = Deal(pace=pace, deal_id=deal_id, shopper_state=shopper_state, on_complete=on_complete,
                        product_id=product_id)
        await deal.setup()
        self.deals[deal.id] = deal
        task = asyncio.create_task(deal.run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return deal
