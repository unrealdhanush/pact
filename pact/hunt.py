"""Shopping around: the shopper agent negotiates with several merchant agents at once.

One BAND room per merchant, all negotiated in parallel. Each room runs to an agreement
(or the shopper walks away); the authority gate is held. The shopper then ranks the
agreements by the human's preference (best match / cheapest / fastest), releases the
winner's gate (Jev → approval → execution) and tells the other merchants it went with
another offer. From the outside a Hunt looks like one Deal: same events, approve(), snapshot().
"""
import asyncio
import dataclasses
import logging
import os
import random
import time

from . import discovery, scenario
from .band import BandConfig, bootstrap_agents
from .deal import Deal
from .engine import money
from .scenario import ShopperState

log = logging.getLogger("pact.hunt")

PREFERENCES = ("best", "cheapest", "fastest")
CHILD_ALWAYS = {"message", "trace", "room", "memory", "near_miss"}  # forwarded from every room
CHILD_WINNER = {"phase", "authority", "status"}  # forwarded only from the winning room
NEGOTIATION_TIMEOUT_S = 90


def rank_key(preference: str, shopper: ShopperState, deal: Deal):
    t = deal.agreement.terms
    off_colour = t.variant != shopper.preferred_variant
    if preference == "cheapest":
        return (t.price, t.delivery_date, off_colour)
    if preference == "fastest":
        return (t.delivery_date, t.price, off_colour)
    return (off_colour, t.price, t.delivery_date, -t.return_window_days)  # best match


class Hunt:
    def __init__(self, pace: float = 1.2, hunt_id: str | None = None, shopper_state: ShopperState | None = None,
                 product_id: str = "sony-wh1000xm5", preference: str = "best", on_complete=None):
        self.id = hunt_id or f"deal-{random.randint(1000, 9999)}"
        self.pace = pace
        self.product = scenario.product(product_id)
        self.product_id = product_id
        self.shopper_state = shopper_state or ShopperState()
        self.preference = preference if preference in PREFERENCES else "best"
        self.on_complete = on_complete
        self.deals: dict[str, Deal] = {}
        self.winner: Deal | None = None
        self.quotes: list[dict] = []
        self.failure: str | None = None
        self.pending: Deal | None = None  # deal whose over-budget offer is waiting on the human
        self.events: list[dict] = []
        self._queues: set[asyncio.Queue] = set()
        self._tasks: set[asyncio.Task] = set()
        self.room = None  # compat: the winner's room once chosen

    # ------------------------------------------------------------ Deal-compatible surface
    @property
    def status(self) -> str:
        if self.failure:
            return "failed"
        if self.pending is not None:
            return "awaiting_exception"
        return self.winner.status if self.winner else "negotiating"

    @property
    def agreement(self):
        return self.winner.agreement if self.winner else None

    @property
    def authority(self):
        return self.winner.authority if self.winner else None

    @property
    def execution(self):
        return self.winner.execution if self.winner else None

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

    def why(self) -> list[str]:
        return self.winner.why() if self.winner else []

    def approve(self) -> dict:
        if not self.winner:
            raise ValueError("No winning offer yet")
        return self.winner.approve()

    def snapshot(self) -> dict:
        base = self.winner.snapshot() if self.winner else next(iter(self.deals.values())).snapshot()
        return {**base, "id": self.id, "status": self.status, "hunt": True, "preference": self.preference,
                "merchants": [{"id": m, "name": d.merchant_info["name"], "room": d.room.status() if d.room else None,
                               "runtime": "ZooWork" if type(d.merchant).__name__ == "ZooWorkMerchantAgent" else "local engine"}
                              for m, d in self.deals.items()],
                "quotes": self.quotes, "winner": self.winner.merchant_id if self.winner else None,
                "failure": self.failure or base.get("failure")}

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------ lifecycle
    async def setup(self) -> None:
        cfg = None
        try:
            cfg = await bootstrap_agents()
        except Exception as e:  # noqa: BLE001
            log.warning("BAND bootstrap failed: %s", e)
        merchants = await self._discover(cfg)
        for m in merchants:
            info = scenario.MERCHANTS[m]
            key = os.environ.get(info["key_env"], "")
            if cfg and not key:  # never let one merchant borrow another's BAND identity
                log.warning("no BAND key for %s; skipping", info["name"])
                continue
            band = dataclasses.replace(cfg, merchant_key=key) if cfg else None
            deal = Deal(pace=self.pace, deal_id=f"{self.id}-{m}", band=band,
                        shopper_state=dataclasses.replace(self.shopper_state), product_id=self.product_id,
                        merchant_id=m, discover=False, hold_gate=True, on_complete=self._completed)
            self.deals[m] = deal
        await asyncio.gather(*(d.setup() for d in self.deals.values()))
        for m, d in self.deals.items():
            self._spawn(self._forward(m, d))

    async def _discover(self, cfg) -> list[str]:
        """Find merchant agents on BAND that sell the product; fall back to the known list."""
        known = list(scenario.MERCHANTS)
        if cfg is None:
            return known
        self.emit("trace", side="shopper", kind="think",
                  text=f"Searching BAND's agent directory for merchants selling the {self.product.name}…")
        try:
            found = await discovery.discover_merchant(self.product.name, cfg)
        except Exception as e:  # noqa: BLE001
            self.emit("trace", side="shopper", kind="think", text=f"BAND directory unavailable ({type(e).__name__})")
            return known
        for c in found["candidates"]:
            self.emit("trace", side="shopper", kind="tool", text=f"band_lookup_peers → {c['name']} · relevance {c['score']:.2f}")
        by_agent = {v["band_agent"]: k for k, v in scenario.MERCHANTS.items()}
        picked = [by_agent[c["name"]] for c in found["candidates"]
                  if c["name"] in by_agent and c["score"] >= 0.2][:3] or known
        names = ", ".join("@" + scenario.MERCHANTS[m]["band_agent"] for m in picked)
        self.emit("trace", side="shopper", kind="think",
                  text=f"{len(picked)} merchants sell it (ranked by Moss in {found['ms']} ms): {names}. "
                       f"Opening a deal room with each, in parallel.")
        self.emit("discovery", **found, chosen_all=[scenario.MERCHANTS[m]["band_agent"] for m in picked])
        return picked

    async def _forward(self, merchant: str, deal: Deal) -> None:
        q = deal.listen()
        name = deal.merchant_info["name"]
        while True:
            e = await q.get()
            t = e["type"]
            if t in CHILD_ALWAYS or (t in CHILD_WINNER and deal is self.winner):
                self.emit(t, **{k: v for k, v in e.items() if k not in ("type", "ts")}, merchant=merchant,
                          merchant_name=name)

    async def run(self) -> None:
        self.emit("status", status="negotiating")
        self.emit("hunt", preference=self.preference,
                  merchants=[{"id": m, "name": d.merchant_info["name"]} for m, d in self.deals.items()])
        for d in self.deals.values():
            self._spawn(d.run())
        try:
            await asyncio.wait_for(asyncio.gather(*(d.agreed.wait() for d in self.deals.values())),
                                   NEGOTIATION_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.warning("some negotiations did not finish in %ss", NEGOTIATION_TIMEOUT_S)
        await asyncio.sleep(0.3)  # let the final room messages land
        self._decide()

    def _decide(self) -> None:
        agreed = [d for d in self.deals.values() if d.agreement and d.status != "failed"]
        self.quotes = []
        for m, d in self.deals.items():
            q = {"merchant": m, "name": d.merchant_info["name"]}
            if d in agreed:
                t = d.agreement.terms
                q.update(price=t.price, variant=t.variant, shipping=t.shipping,
                         delivery_date=t.delivery_date.isoformat(), return_window_days=t.return_window_days)
            else:
                q.update(failed=d.failure or "no agreement in time")
            self.quotes.append(q)
        if not agreed:
            waiting = [d for d in self.deals.values() if d.exception and d._exception_future
                       and not d._exception_future.done()]
            if waiting:  # nothing fits, but Jev said a near miss is worth the human's attention
                best = min(waiting, key=lambda d: (d.exception["over_by"],
                                                   d.exception["offer"]["variant"] != self.shopper_state.preferred_variant))
                for d in waiting:
                    if d is not best:
                        d.resolve_exception(False)
                for q in self.quotes:
                    if q["merchant"] == best.merchant_id:
                        q.update(over_budget=best.exception)
                self.pending = self.winner = best
                self.room = best.room
                best.hold_gate = False  # if the human accepts, its agreement goes straight to the gate
                self.emit("quotes", quotes=self.quotes, winner=None, preference=self.preference)
                self.emit("phase", phase="awaiting_exception")
                self.emit("status", status="awaiting_exception", exception=best.exception)
                return
            self.failure = "No merchant could meet your boundaries — your agent walked away from every offer"
            self.emit("quotes", quotes=self.quotes, winner=None, preference=self.preference)
            self.emit("phase", phase="failed")
            self.emit("status", status="failed", reason=self.failure)
            return
        ranked = sorted(agreed, key=lambda d: rank_key(self.preference, self.shopper_state, d))
        self.winner = win = ranked[0]
        self.room = win.room
        label = {"best": "best match for your preferences", "cheapest": "cheapest", "fastest": "fastest delivery"}
        t = win.agreement.terms
        self.emit("quotes", quotes=self.quotes, winner=win.merchant_id, preference=self.preference)
        self.emit("trace", side="shopper", kind="think",
                  text=f"Compared {len(agreed)} agreement(s) by {label[self.preference]} → "
                       f"{win.merchant_info['name']}: {money(t.price)} {t.variant}, arrives {t.delivery_date:%a %b %-d}")
        for d in self.deals.values():
            if d is win:
                continue
            self._spawn(self._decline(d))
        win.release_gate()  # Jev → human approval or auto-execute, streamed via the winner's events

    def resolve_exception(self, accept: bool) -> None:
        if self.pending is None:
            raise ValueError("No over-budget offer is waiting for an answer")
        deal, self.pending = self.pending, None
        deal.resolve_exception(accept)
        if not accept:
            self.failure = "You declined the over-budget offer — your agent walked away"
            self.emit("phase", phase="failed")
            self.emit("status", status="failed", reason=self.failure)
        else:
            self.emit("phase", phase="negotiating")
            for d in self.deals.values():
                if d is not deal:
                    self._spawn(self._decline(d))

    async def _decline(self, deal: Deal) -> None:
        if deal.room is None:
            return
        try:
            await deal.room.post_event(f"ShopperAgent went with another merchant's offer for {self.id.upper()}.",
                                       "task", {"outcome": "declined"})
        except Exception as e:  # noqa: BLE001
            log.warning("decline event failed: %s", e)

    async def _completed(self, deal: Deal) -> None:
        if self.on_complete is not None:
            await self.on_complete(deal)

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*(d.close() for d in self.deals.values()), return_exceptions=True)
