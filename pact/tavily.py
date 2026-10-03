"""Competitor price verification via Tavily.

Used only when a shopper cites a competitor price. A live Tavily search over
the competitor's site looks for the claimed price; if Tavily is unavailable the
last live result (committed in data/competitor_cache.json) is used and labelled
as cached with its timestamp.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel

TAVILY_URL = "https://api.tavily.com/search"
CACHE_FILE = Path(__file__).resolve().parent / "data" / "competitor_cache.json"
TOLERANCE = 0.50  # dollars
CACHE_MAX_AGE_H = 24  # a cached confirmation older than this doesn't stand in for an inconclusive search
_PRICE = re.compile(r"\$\s?(\d{2,4}(?:,\d{3})*(?:\.\d{2})?)")


class CompetitorCheck(BaseModel):
    retailer: str
    claimed_price: float
    verified: bool
    found_price: float | None = None
    source_url: str | None = None
    source_title: str | None = None
    checked_at: str
    source: str  # "tavily" | "cache" | "unavailable"


def _domain(retailer: str) -> str | None:
    r = retailer.lower().strip()
    return r if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", r) else None


def _model_token(product: str) -> str:
    """'Sony WH-1000XM5' -> 'wh1000xm5': the model number a result must mention."""
    return re.sub(r"[^a-z0-9]", "", product.split()[-1].lower())


def _about(res: dict, product: str) -> bool:
    token = _model_token(product)
    return any(token in re.sub(r"[^a-z0-9]", "", res.get(f, "").lower()) for f in ("url", "title", "content"))


def _match(results: list[dict], claimed: float, product: str) -> tuple[float, dict] | None:
    for res in results:
        if not _about(res, product):
            continue
        text = f"{res.get('title', '')} {res.get('content', '')}"
        for raw in _PRICE.findall(text):
            price = float(raw.replace(",", ""))
            if abs(price - claimed) <= TOLERANCE:
                return price, res
    return None


def _cache_key(product: str, retailer: str) -> str:
    return f"{product.lower()}|{retailer.lower()}"


def _load_cache() -> dict:
    return json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}


def _age_hours(iso: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600
    except ValueError:
        return float("inf")


def _from_cache(product: str, retailer: str, claimed: float, why: str) -> CompetitorCheck:
    hit = _load_cache().get(_cache_key(product, retailer))
    if hit:
        found = hit.get("found_price")
        return CompetitorCheck(retailer=retailer, claimed_price=claimed,
                               verified=found is not None and abs(found - claimed) <= TOLERANCE,
                               found_price=found, source_url=hit.get("source_url"),
                               source_title=hit.get("source_title"), checked_at=hit["checked_at"], source="cache")
    return CompetitorCheck(retailer=retailer, claimed_price=claimed, verified=False,
                           checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           source="unavailable", source_title=why)


def _queries(product: str, retailer: str) -> list[dict]:
    """Search variants, most reliable first (measured: advanced depth on the retailer domain)."""
    domain = _domain(retailer)
    scope = {"include_domains": [domain]} if domain else {}
    return [
        {"query": f"{product} price", "search_depth": "advanced", **scope},
        {"query": f"buy {product} price", "search_depth": "basic", **scope},
        {"query": f"{product} price {retailer}", "search_depth": "basic"},
    ]


async def verify_competitor_price(product: str, retailer: str, claimed: float) -> CompetitorCheck:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return _from_cache(product, retailer, claimed, "Tavily not configured")
    results: list[dict] = []
    hit = None
    try:
        async with httpx.AsyncClient(timeout=12) as http:
            for body in _queries(product, retailer):  # stop at the first query that finds the price
                res = await http.post(TAVILY_URL, headers={"Authorization": f"Bearer {key}"},
                                      json={**body, "max_results": 5})
                res.raise_for_status()
                results = res.json().get("results", [])
                if hit := _match(results, claimed, product):
                    break
    except (httpx.HTTPError, ValueError) as e:
        return _from_cache(product, retailer, claimed, f"Tavily error: {type(e).__name__}")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if hit is None:
        # A search miss is weak evidence; reuse a recent confirmed result, labelled as cached.
        cached = _from_cache(product, retailer, claimed, "live search inconclusive")
        if cached.verified and _age_hours(cached.checked_at) <= CACHE_MAX_AGE_H:
            return cached.model_copy(update={"source_title": f"{cached.source_title} (live search inconclusive)"})
    check = CompetitorCheck(
        retailer=retailer, claimed_price=claimed, verified=hit is not None,
        found_price=hit[0] if hit else None,
        source_url=(hit[1] if hit else (results[0] if results else {})).get("url"),
        source_title=(hit[1] if hit else (results[0] if results else {})).get("title"),
        checked_at=now, source="tavily",
    )
    if check.verified:  # keep the last good live result as the offline fallback
        cache = _load_cache()
        cache[_cache_key(product, retailer)] = check.model_dump(exclude={"verified", "claimed_price", "source"})
        CACHE_FILE.parent.mkdir(exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, indent=2))
    return check


def integration_status() -> dict:
    cached = _load_cache()
    if os.environ.get("TAVILY_API_KEY"):
        return {"name": "Tavily", "mode": "live",
                "detail": "Verifies the shopper's competitor price live; cached result if Tavily fails"}
    when = next(iter(cached.values()), {}).get("checked_at", "never")
    return {"name": "Tavily", "mode": "fallback", "detail": f"No TAVILY_API_KEY — cached competitor data ({when})"}
