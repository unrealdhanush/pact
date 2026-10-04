import asyncio
import importlib
from datetime import date
import json
import re
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.band")  # BAND agent keys auto-registered by pact.band

from . import band, gate  # noqa: E402  (after load_dotenv so adapters see the keys)
from .deal import DealStore, _jsonable  # noqa: E402
from .engine import money  # noqa: E402
from .intake import IntakeStore  # noqa: E402
from .memory import memory  # noqa: E402
from . import shared  # noqa: E402
from .scenario import MerchantState, Product, ShopperState, merchant_state, product  # noqa: E402

WEB = ROOT / "web"
DEAL_ID = re.compile(r"^deal-\d{4}$")

app = FastAPI(title="Pact")
app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")
store = DealStore()
intakes = IntakeStore()


@app.on_event("startup")
async def _warm_memory():
    asyncio.create_task(memory.load())  # Moss indexes load in the background (~10 s), queries are then in-process

# Adapters owned by the merchant side; reported as fallback until they exist.
OPTIONAL_ADAPTERS = {
    "ZooWork": ("pact.zoowork", "local merchant agent — deterministic engine (simulated)"),
    "Tavily": ("pact.tavily", "no live competitor check — not integrated yet"),
    "Moss": ("pact.memory", "no shopper memory — local keyword fallback (simulated)"),
}


def integrations() -> list[dict]:
    out = [band.integration_status(), shared.status()]
    for name, (module, fallback) in OPTIONAL_ADAPTERS.items():
        try:
            status = importlib.import_module(module).integration_status()
        except Exception:  # noqa: BLE001 - missing or broken adapter is a fallback, never a crash
            status = {"name": name, "mode": "fallback", "detail": fallback}
        out.append(status)
    out.insert(2, gate.integration_status())
    return out


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/scenario")
def scenario(product_id: str = "sony-wh1000xm5"):
    try:
        selected = product(product_id)
        merchant = merchant_state(product_id)
    except KeyError:
        raise HTTPException(422, "unknown demo product") from None
    return {"product": asdict(selected), "shopper": _jsonable(asdict(ShopperState())),
            "merchant": _jsonable(asdict(merchant))}


@app.get("/api/integrations")
def get_integrations():
    return integrations()


@app.get("/api/market/{product_id}")
async def market(product_id: str):
    """Live prices across major retailers (Tavily) next to the Pact merchant agents that can negotiate."""
    from . import scenario
    from .tavily import market_prices
    if product_id not in scenario.CATALOG:
        raise HTTPException(404, "unknown product")
    p = scenario.product(product_id)
    data = await market_prices(product_id, p.name, p.search, p.match, p.list_price)
    agents = [{"name": m["name"], "band_agent": m["band_agent"],
               "shelf_price": scenario.merchant_state(product_id, mid).list_price}
              for mid, m in scenario.MERCHANTS.items()]
    return {**data, "agents": agents}


@app.post("/api/intake")
async def intake(body: dict):
    """One turn of the human talking (voice transcript or text) to their shopper agent."""
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(422, "text is required")
    it = await intakes.get(body.get("intake_id")) or intakes.get_or_new(None)
    view = await it.turn(text)
    await intakes.save(it)
    return view


@app.post("/api/intake/{intake_id}/choose")
async def choose_product(intake_id: str, body: dict):
    """The human picks a product card and (optionally) their max price."""
    it = await intakes.get(intake_id)
    if it is None:
        raise HTTPException(404, "unknown intake")
    try:
        view = await it.choose(str(body.get("product_id", "")), body.get("max_price"),
                               body.get("approval_required_above"))
    except ValueError as e:
        raise HTTPException(409, str(e))
    await intakes.save(it)
    return view


async def _remember_outcome(deal) -> None:
    """Moss write-back: the next conversation recalls how this deal ended."""
    t = deal.agreement.terms
    note = (f"Bought the {deal.product.name} in {t.variant} for {money(t.price)} with "
            f"{'free next-day delivery' if t.shipping == 'free_next_day' else 'standard shipping'} and "
            f"{t.return_window_days}-day returns on {date.today():%b %d} "
            f"(Pact {deal.id}).")
    if t.variant != deal.shopper_state.preferred_variant:
        note += (f" Accepted {t.variant} instead of {deal.shopper_state.preferred_variant} "
                 f"for the {t.return_window_days}-day return window.")
    where = await memory.remember(f"outcome-{deal.id}", note, {"last_purchase": {
        "product": deal.product.name, "variant": t.variant, "price": t.price}})
    deal.emit("memory", stored=where, text=note)


@app.post("/api/deals")
async def create_deal(pace: float = 1.2, id: str | None = None, intake: str | None = None,
                      shop: int = 1, prefer: str = "best", prio: str | None = None):
    """shop=1: the shopper negotiates with every merchant in parallel and keeps the best by `prefer`
    (best | cheapest | fastest). shop=0: a single merchant (Aria Audio)."""
    if id is not None and not DEAL_ID.match(id):
        raise HTTPException(422, "id must look like deal-1842")
    shopper_state, on_complete, product_id = None, None, "sony-wh1000xm5"
    if intake:
        it = await intakes.get(intake)
        if it is None or not it.product or not it.product.get("carried"):
            raise HTTPException(409, "intake is not ready: no product this merchant carries")
        shopper_state, on_complete, product_id = it.shopper_state(), _remember_outcome, it.product["product_id"]
    if prio is not None:  # the human's explicit "what matters most" overrides memory
        from .scenario import ShopperState as _SS
        shopper_state = shopper_state or _SS()
        shopper_state.priorities = [p for p in prio.split(",") if p in ("price", "colour", "speed", "returns")]
    deal = await store.create(pace=pace, deal_id=id, shopper_state=shopper_state, on_complete=on_complete,
                              product_id=product_id, shop_around=bool(shop), preference=prefer)
    shared.attach(deal, _apply)  # serverless: mirror to Redis, take actions queued by other instances
    return {**deal.snapshot(), "integrations": integrations(),
            "intake": intakes.items[intake].view("")["fields"] if intake else None}


def _get(deal_id: str):
    deal = store.deals.get(deal_id)
    if not deal:
        raise HTTPException(404, "Unknown deal")
    return deal


@app.get("/api/deals/{deal_id}")
async def get_deal(deal_id: str):
    deal = store.deals.get(deal_id)
    if deal:
        return {**deal.snapshot(), "events": deal.events}
    snap = await shared.snapshot(deal_id) if shared.enabled() else None
    if snap is None:
        raise HTTPException(404, "Unknown deal")
    return snap


@app.get("/api/deals/{deal_id}/events")
async def deal_events(deal_id: str):
    deal = store.deals.get(deal_id)
    if deal is None:
        if not (shared.enabled() and await shared.exists(deal_id)):
            raise HTTPException(404, "Unknown deal")

        async def relay():  # another instance runs this deal: stream its mirrored events from Redis
            sent, idle = 0, 0.0
            while True:
                batch = await shared.events_from(deal_id, sent)
                for e in batch:
                    yield f"data: {json.dumps(e, default=str)}\n\n"
                sent += len(batch)
                idle = 0.0 if batch else idle + shared.POLL_S
                if idle >= 15:
                    yield ": keepalive\n\n"
                    idle = 0.0
                await asyncio.sleep(shared.POLL_S)
        return StreamingResponse(relay(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def stream():
        q = deal.listen()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            deal.unlisten(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _apply(deal, a: dict):
    """Apply one human action to a deal running on this instance."""
    kind = a["action"]
    if kind == "approve":
        return deal.approve()
    if kind == "exception":
        deal.resolve_exception(bool(a.get("accept")))
        return {"ok": True}
    if kind == "return":
        target = getattr(deal, "winner", None) or deal
        target.on_return = _remember_return
        await deal.start_return(a.get("reason") or "They're uncomfortable after an hour")
        return {"ok": True}
    if kind == "return_approve":
        return deal.approve_return()
    if kind == "dropoff":
        return deal.choose_dropoff(str(a.get("location_id", "")))
    if kind == "dropped":
        deal.mark_dropped()
        return {"ok": True}
    raise ValueError(f"unknown action {kind}")


async def _act(deal_id: str, action: str, **data):
    """Run locally if this instance owns the deal; otherwise queue it for the owner (serverless)."""
    deal = store.deals.get(deal_id)
    try:
        if deal is not None:
            return await _apply(deal, {"action": action, **data})
        if shared.enabled() and await shared.exists(deal_id):
            await shared.queue_action(deal_id, action, **data)
            return {"ok": True, "queued": True}
    except ValueError as e:
        raise HTTPException(409, str(e))
    raise HTTPException(404, "Unknown deal")


@app.post("/api/deals/{deal_id}/exception")
async def answer_exception(deal_id: str, body: dict):
    """The human answers an over-budget offer their agent escalated: {"accept": true|false}."""
    return await _act(deal_id, "exception", accept=bool(body.get("accept")))


@app.post("/api/deals/{deal_id}/return")
async def start_return(deal_id: str, body: dict):
    """Post-purchase: the human asks their agent to return the order. {"reason": "..."}"""
    return await _act(deal_id, "return", reason=str(body.get("reason") or "").strip())


@app.post("/api/deals/{deal_id}/return/approve")
async def approve_return(deal_id: str):
    return await _act(deal_id, "return_approve")


@app.post("/api/deals/{deal_id}/return/dropoff")
async def return_dropoff(deal_id: str, body: dict):
    """The human picks a drop-off location; the carrier label arrives as an event (simulated)."""
    return await _act(deal_id, "dropoff", location_id=str(body.get("location_id", "")))


@app.post("/api/deals/{deal_id}/return/dropped")
async def return_dropped(deal_id: str):
    return await _act(deal_id, "dropped")


async def _remember_return(deal) -> None:
    rs, t = deal.return_state, deal.return_state["terms"]
    note = (f"Returned the {deal.product.name} ({rs['reason']}). Took "
            + (f"a full refund." if t["resolution"] == "refund" else
               f"{money(t['amount'] + t['goodwill_credit'])} store credit instead of a refund.")
            + f" Comfort matters — prefer models with a long return window.")
    where = await memory.remember(f"return-{deal.id}", note, {"returned": deal.product.name})
    deal.emit("memory", stored=where, text=note)


@app.post("/api/deals/{deal_id}/approve")
async def approve(deal_id: str):  # async: Deal.approve schedules BAND events on the running loop
    return await _act(deal_id, "approve")
