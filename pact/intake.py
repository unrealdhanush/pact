"""Shopper intake: the human talks (voice or text) to their shopper agent.

Each turn: parse what the human said explicitly, index the turn into a Moss session
(short-term context), recall anything left unsaid from Moss long-term memory, resolve
the product against the Moss catalog, and produce a read-back. Every boundary records
where it came from ("you", "memory", "default"), so the UI can show it.
"""
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from .engine import money
from .memory import memory
from . import scenario
from .scenario import ShopperState, next_weekday

COLOURS = ("black", "silver", "white", "blue", "midnight", "gray", "grey", "beige", "pink")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_NUMWORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
             "eighty": 80, "ninety": 90}
YES = re.compile(r"^\s*(yes|yeah|yep|sure|ok(ay)?|go( ahead)?|do it|negotiate|start|sounds good|confirm)\b", re.I)

# Which memory to recall for each boundary the human didn't state.
RECALL_QUERIES = {
    "preferred_variant": "which colour do I like for headphones, and what colours are acceptable",
    "approval_required_above": "when should you ask me before buying something",
    "minimum_return_days": "how long a return window do I need",
    "max_price": "what is my budget for headphones",
    "competitor_price": "have I seen this product cheaper at another store",
}


def _spoken_numbers(text: str) -> str:
    """'three hundred' -> '300', 'two fifty' -> '250' (speech-to-text often spells numbers)."""
    def repl(m):
        a, b = _NUMWORDS[m.group(1).lower()], m.group(3)
        return str(a * 100 + (_NUMWORDS.get(b.lower(), 0) if b else 0))
    text = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine) (hundred )?(?:and )?"
                  r"(ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)?\b(?=\s*(dollars|bucks|\b))",
                  lambda m: repl(m) if (m.group(2) or m.group(3)) else m.group(0), text, flags=re.I)
    return text


def parse(utterance: str, today: date | None = None) -> dict:
    """Explicit boundaries in what the human said. Only what is clearly stated."""
    today = today or date.today()
    text = _spoken_numbers(utterance)
    low = text.lower()
    out: dict = {}

    m = re.search(r"ask me\b[^$\d]*?(?:over|above|more than|anything over)\s*\$?\s*(\d+(?:\.\d+)?)", low)
    if m:
        out["approval_required_above"] = float(m.group(1))
        low = low[:m.start()] + low[m.end():]
    m = re.search(r"(?:under|below|max(?:imum)?|up to|budget(?: of| is)?|no more than|less than|at most)"
                  r"\s*\$?\s*(\d+(?:\.\d+)?)", low) or re.search(r"\$\s*(\d+(?:\.\d+)?)", low)
    if m:
        out["max_price"] = float(m.group(1))
    m = re.search(r"(\d+)[- ]day return", low)
    if m:
        out["minimum_return_days"] = int(m.group(1))

    colours = [c for c in re.findall(r"\b(" + "|".join(COLOURS) + r")\b", low)]
    if colours:
        fallback = [c for c in colours[1:] if re.search(rf"\b{c}\b[^.]*\b(fine|ok|okay|works|also|too)\b", low)
                    or re.search(rf"\bor {c}\b", low)]
        out["preferred_variant"] = colours[0]
        if fallback:
            out["fallback_variants"] = sorted(set(fallback) - {colours[0]})

    if "tomorrow" in low:
        out["delivery_deadline"] = today + timedelta(days=1)
    else:
        m = re.search(r"\b(" + "|".join(WEEKDAYS) + r")\b", low)
        if m:
            out["delivery_deadline"] = next_weekday(today, WEEKDAYS.index(m.group(1)))
    return out


@dataclass
class Boundary:
    value: object
    source: str  # "you" | "memory" | "default"
    memory_id: str | None = None
    memory_text: str | None = None

    def as_dict(self) -> dict:
        v = self.value.isoformat() if hasattr(self.value, "isoformat") else self.value
        return {"value": v, "source": self.source, "memory_id": self.memory_id, "memory_text": self.memory_text}


@dataclass
class Intake:
    id: str = field(default_factory=lambda: f"intake-{uuid.uuid4().hex[:6]}")
    turns: list[str] = field(default_factory=list)
    fields: dict[str, Boundary] = field(default_factory=dict)
    product: dict | None = None
    options: list[dict] = field(default_factory=list)
    recalled: list[dict] = field(default_factory=list)
    confirmed: bool = False
    session: object = None
    timings: dict[str, float] = field(default_factory=dict)

    async def turn(self, text: str) -> dict:
        text = text.strip()
        self.turns.append(text)
        if self.product and YES.match(text):
            self.confirmed = True
            return self.view("Great — finding a merchant agent and starting the negotiation.")

        if self.session is None:
            self.session = await memory.open_session(f"pact-{self.id}")
        if self.session is not None:  # short-term context: this conversation, indexed as it happens
            from moss import DocumentInfo
            await self.session.add_docs([DocumentInfo(id=f"turn-{len(self.turns)}", text=text)])

        for k, v in parse(text).items():  # what the human says always wins
            self.fields[k] = Boundary(v, "you")

        if self.product is None:
            hits, ms = await memory.search_catalog(text, top_k=5)
            self.timings["catalog_ms"] = round(ms, 1)
            self.options = [self._card(h) for h in hits]
            # top 3 the merchant can actually negotiate, best match first; default selection = first
            carried = [o for o in self.options if o["carried"]][:3]
            self.options = carried + [o for o in self.options if not o["carried"]][:1]
            if carried:  # default to the best match that can plausibly fit the budget
                budget = self.fields["max_price"].value if "max_price" in self.fields else None
                fits = [o for o in carried if budget is None or o.get("list_price", 0) * 0.9 <= budget]
                self.product = (fits or carried)[0]
            elif self.options:
                self.product = self.options[0]

        await self._recall_missing()
        return self.view(self.readback())

    def _card(self, hit) -> dict:
        p = hit.payload
        card = {**p, "score": round(hit.score, 3), "match": hit.text}
        if p.get("carried") and p.get("product_id") in scenario.CATALOG:
            prod = scenario.product(p["product_id"])
            card.update(list_price=prod.list_price, variants=list(prod.variants), specs=prod.specs)
        return card

    async def choose(self, product_id: str, max_price: float | None = None) -> dict:
        """The human picks one of the options (and optionally sets their max price)."""
        pick = next((o for o in self.options if o.get("product_id") == product_id and o.get("carried")), None)
        if pick is None:
            raise ValueError("not one of the negotiable options")
        self.product = pick
        if max_price is not None:
            self.fields["max_price"] = Boundary(float(max_price), "you")
        return self.view(self.readback())

    async def _recall_missing(self) -> None:
        recalled_ms = []
        for name, query in RECALL_QUERIES.items():
            already = name in self.fields and (name != "preferred_variant" or "fallback_variants" in self.fields)
            if already:
                continue
            hits, ms = await memory.recall(query, top_k=3)
            recalled_ms.append(ms)
            key = "competitor_price" if name == "competitor_price" else name
            hit = next((h for h in hits if key in h.payload), None)
            if not hit:
                continue
            if not any(r["id"] == hit.id for r in self.recalled):
                self.recalled.append({**hit.as_dict(), "ms": round(ms, 1)})
            for k, v in hit.payload.items():
                if k not in self.fields:
                    self.fields[k] = Boundary(v, "memory", hit.id, hit.text)
        # context worth surfacing even if it sets no boundary (e.g. past returns)
        hits, ms = await memory.recall(" ".join(self.turns[-1:]) + " headphones comfort returns", top_k=4)
        recalled_ms.append(ms)
        for h in hits:
            if h.kind == "history" and not any(r["id"] == h.id for r in self.recalled):
                self.recalled.append({**h.as_dict(), "ms": round(ms, 1)})
        if recalled_ms:
            self.timings["recall_ms"] = round(sum(recalled_ms) / len(recalled_ms), 1)

    def readback(self) -> str:
        f = self.fields
        if not self.product:
            return "Which product should I look for?"
        if not self.product.get("carried"):
            return (f"I found the {self.product['name']}, but no merchant agent I can reach sells it today. "
                    f"Want me to look for the Sony WH-1000XM5 instead?")
        def val(k, default=None):
            return f[k].value if k in f else default
        others = [o["name"] for o in self.options if o["carried"] and o is not self.product]
        lead = (f"I found {len(others) + 1} options; the closest match is the " if others else "")
        parts = [f"{lead}{self.product['name']}"]
        if "preferred_variant" in f:
            parts[0] += f" in {val('preferred_variant')}"
        if "max_price" in f:
            parts.append(f"up to {money(val('max_price'))}")
        if "delivery_deadline" in f:
            d = val("delivery_deadline")
            parts.append(f"delivered by {d:%A}" if hasattr(d, "strftime") else f"delivered by {d}")
        said = ", ".join(parts) + "."
        mem = []
        if f.get("fallback_variants") and f["fallback_variants"].source == "memory":
            mem.append(f"{' or '.join(val('fallback_variants'))} is fine if I get "
                       f"{val('fallback_return_days', 45)}-day returns")
        if "approval_required_above" in f and f["approval_required_above"].source == "memory":
            mem.append(f"I'll ask you before anything over {money(val('approval_required_above'))}")
        if ("competitor_price" in f and f["competitor_price"].source == "memory"
                and val("competitor_product_id") in (None, self.product.get("product_id"))):
            mem.append(f"you've seen it at {val('competitor_retailer')} for {money(val('competitor_price'))}, "
                       f"so I'll use that as leverage")
        remembered = (" From what I remember: " + "; ".join(mem) + ".") if mem else ""
        ask = ("Pick one and set your max price, or say yes to go with the "
               f"{self.product['name']}." if others else "Shall I find a merchant and negotiate?")
        return f"Got it: {said}{remembered} {ask}"

    def shopper_state(self) -> ShopperState:
        s = ShopperState()
        for k, b in self.fields.items():
            if hasattr(s, k):
                setattr(s, k, b.value)
        # open below the ceiling, never above a known competitor price
        s.target_price = math.floor(s.max_price * 0.93)
        if s.competitor_price:
            s.target_price = min(s.target_price, math.floor(s.competitor_price * 0.93))
        return s

    def view(self, reply: str) -> dict:
        return {
            "intake_id": self.id, "reply": reply, "turns": self.turns, "confirmed": self.confirmed,
            "product": self.product, "options": self.options, "fields": {k: b.as_dict() for k, b in self.fields.items()},
            "recalled": self.recalled, "timings": self.timings, "memory": memory.status(),
            "session": bool(self.session),
        }


class IntakeStore:
    def __init__(self):
        self.items: dict[str, Intake] = {}

    def get_or_new(self, intake_id: str | None) -> Intake:
        if intake_id and intake_id in self.items:
            return self.items[intake_id]
        it = Intake()
        self.items[it.id] = it
        return it
