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

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.band")  # BAND agent keys auto-registered by pact.band

from . import band, gate  # noqa: E402  (after load_dotenv so adapters see the keys)
from .deal import DealStore, _jsonable  # noqa: E402
from .engine import money  # noqa: E402
from .intake import IntakeStore  # noqa: E402
from .memory import memory  # noqa: E402
from .scenario import MerchantState, Product, ShopperState  # noqa: E402

WEB = ROOT / "web"
DEAL_ID = re.compile(r"^deal-\d{4}$")

app = FastAPI(title="Pact")
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
    out = [band.integration_status()]
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
def scenario():
    return {"product": asdict(Product()), "shopper": _jsonable(asdict(ShopperState())),
            "merchant": _jsonable(asdict(MerchantState()))}


@app.get("/api/integrations")
def get_integrations():
    return integrations()


@app.post("/api/intake")
async def intake(body: dict):
    """One turn of the human talking (voice transcript or text) to their shopper agent."""
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(422, "text is required")
    return await intakes.get_or_new(body.get("intake_id")).turn(text)


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
async def create_deal(pace: float = 1.2, id: str | None = None, intake: str | None = None):
    if id is not None and not DEAL_ID.match(id):
        raise HTTPException(422, "id must look like deal-1842")
    shopper_state, on_complete = None, None
    if intake:
        it = intakes.items.get(intake)
        if it is None or not it.product or not it.product.get("carried"):
            raise HTTPException(409, "intake is not ready: no product this merchant carries")
        shopper_state, on_complete = it.shopper_state(), _remember_outcome
    deal = await store.create(pace=pace, deal_id=id, shopper_state=shopper_state, on_complete=on_complete)
    return {**deal.snapshot(), "integrations": integrations(),
            "intake": intakes.items[intake].view("")["fields"] if intake else None}


def _get(deal_id: str):
    deal = store.deals.get(deal_id)
    if not deal:
        raise HTTPException(404, "Unknown deal")
    return deal


@app.get("/api/deals/{deal_id}")
def get_deal(deal_id: str):
    deal = _get(deal_id)
    return {**deal.snapshot(), "events": deal.events}


@app.get("/api/deals/{deal_id}/events")
async def deal_events(deal_id: str):
    deal = _get(deal_id)

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


@app.post("/api/deals/{deal_id}/approve")
async def approve(deal_id: str):  # async: Deal.approve schedules BAND events on the running loop
    try:
        return _get(deal_id).approve()
    except ValueError as e:
        raise HTTPException(409, str(e))
