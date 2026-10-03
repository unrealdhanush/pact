import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from .deal import DealStore, _jsonable
from .scenario import MerchantState, Product, ShopperState

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Pact")
store = DealStore()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/scenario")
def scenario():
    return {"product": asdict(Product()), "shopper": _jsonable(asdict(ShopperState())),
            "merchant": _jsonable(asdict(MerchantState()))}


@app.post("/api/deals")
async def create_deal(pace: float = 1.2):
    return (await store.create(pace=pace)).snapshot()


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
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            deal.unlisten(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/deals/{deal_id}/approve")
def approve(deal_id: str):
    try:
        return _get(deal_id).approve()
    except ValueError as e:
        raise HTTPException(409, str(e))
