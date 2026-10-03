"""Shopper memory on Moss (semantic search runtime).

Two persistent Moss indexes, loaded into memory for sub-10 ms queries:
  - `pact-shopper-memory`: what the shopper's agent knows about its human (durable
    preferences + purchase history). Each document's `text` is embedded and searched;
    its `payload` is the structured boundary it implies, e.g. {"approval_required_above": 250}.
  - `pact-product-catalog`: resolves "Sony noise-cancelling headphones" to a product.
Each intake conversation is also a Moss session (short-term context): turns are indexed
as they arrive and queried locally.

After a deal completes, the outcome is written back to the memory index, so the next
conversation recalls it.

If Moss is unreachable, the same seed documents are searched with a local keyword scorer
and every result says so (mode="fallback").

    uv run python -m pact.memory --seed     # create/refresh both indexes (once)
"""
import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field

log = logging.getLogger("pact.memory")

MEMORY_INDEX = "pact-shopper-memory"
CATALOG_INDEX = "pact-product-catalog"
MODEL = "moss-minilm"

SEED_MEMORY = [
    {"id": "pref-colour", "kind": "preference",
     "text": "My favourite colour for headphones is black, but silver is fine as long as I get a "
             "45-day return window.",
     "payload": {"preferred_variant": "black", "fallback_variants": ["silver"], "fallback_return_days": 45}},
    {"id": "pref-approval", "kind": "preference",
     "text": "Always ask me before you buy anything that costs more than $250.",
     "payload": {"approval_required_above": 250}},
    {"id": "pref-returns", "kind": "preference",
     "text": "For electronics I need at least a 30-day return window.",
     "payload": {"minimum_return_days": 30}},
    {"id": "pref-budget", "kind": "preference",
     "text": "My usual budget for a good pair of headphones is about $300.",
     "payload": {"max_price": 300}},
    {"id": "watch-sony-xm5", "kind": "research",
     "text": "Price watch: the Sony WH-1000XM5 is listed at $299.99 on sony.com.",
     "payload": {"competitor_retailer": "sony.com", "competitor_price": 299.99}},
    {"id": "history-bose", "kind": "history",
     "text": "Returned Bose QuietComfort headphones last year because they got uncomfortable after an hour; "
             "a long return window matters.",
     "payload": {}},
]

SEED_CATALOG = [
    {"id": "sony-wh1000xm5", "text": "Sony WH-1000XM5 wireless noise-cancelling over-ear headphones, "
     "industry-leading ANC for flights and commuting, 30-hour battery, black or silver.",
     "payload": {"product_id": "sony-wh1000xm5", "name": "Sony WH-1000XM5", "carried": True}},
    {"id": "sony-wf1000xm5", "text": "Sony WF-1000XM5 true wireless noise-cancelling earbuds, compact in-ear.",
     "payload": {"product_id": "sony-wf1000xm5", "name": "Sony WF-1000XM5", "carried": False}},
    {"id": "bose-qc-ultra", "text": "Bose QuietComfort Ultra headphones, over-ear noise cancelling, spatial audio.",
     "payload": {"product_id": "bose-qc-ultra", "name": "Bose QuietComfort Ultra", "carried": False}},
    {"id": "sennheiser-m4", "text": "Sennheiser Momentum 4 wireless over-ear headphones, 60-hour battery.",
     "payload": {"product_id": "sennheiser-m4", "name": "Sennheiser Momentum 4", "carried": False}},
    {"id": "airpods-max", "text": "Apple AirPods Max over-ear headphones with active noise cancellation.",
     "payload": {"product_id": "airpods-max", "name": "Apple AirPods Max", "carried": False}},
]


@dataclass
class Recall:
    id: str
    text: str
    score: float
    payload: dict = field(default_factory=dict)
    kind: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "score": round(self.score, 3), "kind": self.kind,
                "payload": self.payload}


def _docs(seed: list[dict]):
    from moss import DocumentInfo
    return [DocumentInfo(id=d["id"], text=d["text"], metadata={"kind": d.get("kind", "product")},
                         payload=json.dumps(d["payload"])) for d in seed]


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


class ShopperMemory:
    """Long-term memory + catalog on Moss, with a labelled local fallback."""

    def __init__(self):
        self.mode = "fallback"
        self.detail = "not loaded"
        self.client = None
        self._extra: list[dict] = []  # outcomes remembered while in fallback mode
        self._lock = asyncio.Lock()
        self._loaded = False

    # ---------------------------------------------------------------- lifecycle
    async def load(self) -> None:
        async with self._lock:
            if self._loaded:
                return
            pid, key = os.environ.get("MOSS_PROJECT_ID"), os.environ.get("MOSS_PROJECT_KEY")
            if not (pid and key):
                self.mode, self.detail = "fallback", "no MOSS_PROJECT_ID/KEY — local keyword memory (simulated)"
                self._loaded = True
                return
            try:
                from moss import MossClient
                self.client = MossClient(pid, key)
                names = {getattr(i, "name", i) for i in await self.client.list_indexes()}
                for name, seed in ((MEMORY_INDEX, SEED_MEMORY), (CATALOG_INDEX, SEED_CATALOG)):
                    if name not in names:
                        await self.client.create_index(name, _docs(seed), MODEL)
                    await self.client.load_index(name)
                self.mode, self.detail = "live", f"Moss indexes {MEMORY_INDEX} + {CATALOG_INDEX} loaded in-process"
            except Exception as e:  # noqa: BLE001 - never block the demo on Moss
                log.warning("Moss unavailable: %s", e)
                self.client = None
                self.mode, self.detail = "fallback", f"Moss unavailable ({type(e).__name__}) — local keyword memory"
            self._loaded = True

    def status(self) -> dict:
        return {"name": "Moss", "mode": self.mode, "detail": self.detail}

    # ---------------------------------------------------------------- queries
    async def recall(self, query: str, top_k: int = 3) -> tuple[list[Recall], float]:
        """Semantic recall from long-term memory. Returns (results, milliseconds)."""
        return await self._query(MEMORY_INDEX, SEED_MEMORY + self._extra, query, top_k)

    async def resolve_product(self, utterance: str) -> tuple[Recall | None, float]:
        hits, ms = await self._query(CATALOG_INDEX, SEED_CATALOG, utterance, 1)
        return (hits[0] if hits else None), ms

    async def _query(self, index: str, seed: list[dict], query: str, top_k: int) -> tuple[list[Recall], float]:
        await self.load()
        t0 = time.perf_counter()
        if self.client is not None:
            try:
                from moss import QueryOptions
                res = await self.client.query(index, query, QueryOptions(top_k=top_k, alpha=0.7))
                hits = [Recall(id=d.id, text=d.text, score=float(d.score or 0),
                               payload=json.loads(d.payload) if getattr(d, "payload", None) else {},
                               kind=(d.metadata or {}).get("kind", "") if getattr(d, "metadata", None) else "")
                        for d in res.docs]
                return hits, (time.perf_counter() - t0) * 1000
            except Exception as e:  # noqa: BLE001
                log.warning("Moss query failed, using local memory: %s", e)
                self.mode, self.detail = "fallback", f"Moss query failed ({type(e).__name__}) — local keyword memory"
        q = _words(query)
        scored = sorted(((len(q & _words(d["text"])) / (len(q) or 1), d) for d in seed), key=lambda x: -x[0])
        hits = [Recall(id=d["id"], text=d["text"], score=s, payload=d["payload"], kind=d.get("kind", ""))
                for s, d in scored[:top_k] if s > 0]
        return hits, (time.perf_counter() - t0) * 1000

    # ---------------------------------------------------------------- sessions + write-back
    async def open_session(self, name: str):
        """Short-term Moss session for one intake conversation (None in fallback mode)."""
        await self.load()
        if self.client is None:
            return None
        try:
            return await self.client.session(index_name=name, model_id=MODEL)
        except Exception as e:  # noqa: BLE001
            log.warning("Moss session failed: %s", e)
            return None

    async def remember(self, doc_id: str, text: str, payload: dict, kind: str = "history") -> str:
        """Write a new memory (e.g. a deal outcome). Returns where it was stored."""
        await self.load()
        if self.client is not None:
            try:
                from moss import DocumentInfo, MutationOptions
                await self.client.add_docs(MEMORY_INDEX, [DocumentInfo(
                    id=doc_id, text=text, metadata={"kind": kind}, payload=json.dumps(payload))],
                    MutationOptions(upsert=True))
                await self.client.load_index(MEMORY_INDEX)  # refresh the in-process copy
                return "moss"
            except Exception as e:  # noqa: BLE001
                log.warning("Moss write failed: %s", e)
        self._extra = [d for d in self._extra if d["id"] != doc_id] + [
            {"id": doc_id, "kind": kind, "text": text, "payload": payload}]
        return "local"


memory = ShopperMemory()


def integration_status() -> dict:
    return memory.status() if memory._loaded else (
        {"name": "Moss", "mode": "live", "detail": "Moss credentials set — indexes load on first use"}
        if os.environ.get("MOSS_PROJECT_ID") and os.environ.get("MOSS_PROJECT_KEY")
        else {"name": "Moss", "mode": "fallback", "detail": "no MOSS_PROJECT_ID/KEY — local keyword memory (simulated)"})


async def _seed() -> None:
    """Rebuild both indexes from the seed documents (drops remembered outcomes)."""
    from moss import MossClient
    client = MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])
    names = {getattr(i, "name", i) for i in await client.list_indexes()}
    for name, seed in ((MEMORY_INDEX, SEED_MEMORY), (CATALOG_INDEX, SEED_CATALOG)):
        if name in names:
            await client.delete_index(name)
        await client.create_index(name, _docs(seed), MODEL)
        print(f"seeded {name} ({len(seed)} docs)")


if __name__ == "__main__":
    import pact  # noqa: F401  (loads .env)
    if "--seed" in sys.argv:
        asyncio.run(_seed())
