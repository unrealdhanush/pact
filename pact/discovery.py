"""Merchant discovery: the shopper agent searches BAND's peer directory for a merchant
agent that sells the product, ranks candidates by their descriptions with Moss, and
invites the best match into the deal room."""
import logging

from .band import BandConfig, urllib_request
from .memory import rank

log = logging.getLogger("pact.discovery")
RUNNABLE = {"MerchantAgent"}  # merchant agents this Pact server actually operates


async def discover_merchant(product: str, config: BandConfig) -> dict:
    """Returns {candidates: [{name, handle, description, score}], chosen, ms, ranker} (raises on BAND errors)."""
    resp = await urllib_request("GET", f"{config.base_url}/agent/peers", config.shopper_key, None)
    peers = [p for p in resp.get("data", []) if p.get("type") == "Agent" and p.get("name") != "ShopperAgent"]
    texts = {p["name"]: f"{p['name']}: {p.get('description') or ''}" for p in peers}
    ranked, ms, ranker = await rank(texts, f"merchant that sells {product} headphones and audio") if texts else ([], 0, "none")
    by_name = {p["name"]: p for p in peers}
    candidates = [{"name": n, "handle": by_name[n].get("handle"), "description": by_name[n].get("description"),
                   "score": round(s, 3)} for n, s in ranked]
    chosen = next((c for c in candidates if c["name"] in RUNNABLE), None)
    if candidates and chosen and candidates[0]["name"] != chosen["name"]:
        log.warning("top-ranked merchant %s is not operated here; using %s", candidates[0]["name"], chosen["name"])
    return {"candidates": candidates, "chosen": chosen, "ms": round(ms, 1), "ranker": ranker}
