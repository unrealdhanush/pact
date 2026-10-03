"""Post-approval return logistics: drop-off options, carrier labels, return tracking.

In production these come from the carriers' location and label APIs (UPS / USPS / FedEx
locators and shipping APIs). Here the drop-off points are real places from OpenStreetMap
near the delivery address (fetched once, embedded below); labels and scans are simulated
and always labelled as such.
"""
import hashlib
import math
import urllib.parse
from datetime import date, timedelta

DELIVERY_ADDRESS = {"name": "Walt Disney Family Museum", "address": "104 Montgomery St, San Francisco",
                    "lat": 37.8013, "lng": -122.4587}

# Real locations near the delivery address (OpenStreetMap, © OpenStreetMap contributors).
DROP_OFFS = [
    {"id": "presidio-po", "name": "Presidio Post Office", "carrier": "USPS", "address": "558 Presidio Boulevard",
     "lat": 37.79853, "lng": -122.45141, "hours": "Mon–Fri 9:30–1:30, 2:00–4:00", "osm": "node/13753050454"},
    {"id": "ups-marina", "name": "The UPS Store", "carrier": "UPS", "address": "Marina district (street not listed)",
     "lat": 37.80016, "lng": -122.44062, "hours": None, "osm": "node/416783966"},
    {"id": "marina-po", "name": "Marina Station", "carrier": "USPS", "address": "2055 Lombard Street",
     "lat": 37.79979, "lng": -122.4352, "hours": None, "osm": "node/358855358"},
    {"id": "geary-po", "name": "Post Office", "carrier": "USPS", "address": "3245 Geary Boulevard",
     "lat": 37.7813, "lng": -122.45383, "hours": None, "osm": "way/273583476"},
]

RETURN_STAGES = ["label_created", "dropped_off", "credit_issued", "in_transit", "received"]
STAGE_LABEL = {"label_created": "Label created", "dropped_off": "Dropped off", "credit_issued": "Credit issued",
               "in_transit": "In transit", "received": "Received by the store"}


def _km(a_lat, a_lng, b_lat, b_lng) -> float:
    r, p = 6371, math.radians
    h = (math.sin(p(b_lat - a_lat) / 2) ** 2
         + math.cos(p(a_lat)) * math.cos(p(b_lat)) * math.sin(p(b_lng - a_lng) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(h))


def map_links(loc: dict) -> dict:
    q = urllib.parse.quote(f"{loc['name']}, {loc['address']}" if "not listed" not in loc["address"] else loc["name"])
    ll = f"{loc['lat']},{loc['lng']}"
    return {"apple": f"https://maps.apple.com/?q={q}&ll={ll}&daddr={ll}",
            "google": f"https://www.google.com/maps/dir/?api=1&destination={ll}"}


def drop_off_options() -> list[dict]:
    a = DELIVERY_ADDRESS
    out = []
    for loc in DROP_OFFS:
        km = _km(a["lat"], a["lng"], loc["lat"], loc["lng"])
        out.append({**loc, "km": round(km, 1), "mi": round(km * 0.621, 1), "links": map_links(loc)})
    return sorted(out, key=lambda x: x["km"])


def details(order_id: str, rma: str, terms: dict, product: str, merchant: str) -> dict:
    """What the customer needs after the return is approved."""
    credit = terms["amount"] + terms.get("goodwill_credit", 0)
    what = (f"{_money(credit)} store credit ({_money(terms['amount'])} + {_money(terms['goodwill_credit'])} bonus)"
            if terms["resolution"] == "store_credit" else f"Refund of {_money(terms['amount'])} to your card")
    return {
        "rma": rma, "order_id": order_id, "product": product, "merchant": merchant,
        "you_get": what, "when": "Issued as soon as the carrier scans your package — no waiting for the warehouse.",
        "drop_by": (date.today() + timedelta(days=14)).isoformat(),
        "steps": ["Pack the headphones, case and cable — any box or padded bag works.",
                  "Pick a drop-off below; the label is issued for that carrier.",
                  "Show the QR code at the counter. No printer needed.",
                  "Keep the drop-off receipt until the credit shows up."],
        "delivery_address": DELIVERY_ADDRESS,
        "options": drop_off_options(),
        "simulated": True,
    }


def label_for(rma: str, loc: dict) -> dict:
    """A carrier-specific return label (simulated tracking number in the carrier's format)."""
    digits = str(int(hashlib.sha256(f"{rma}{loc['id']}".encode()).hexdigest(), 16))
    if loc["carrier"] == "UPS":
        tracking = "1Z" + hashlib.sha256(rma.encode()).hexdigest()[:6].upper() + "90" + digits[:8]
    else:
        tracking = "9202 " + " ".join(digits[i:i + 4] for i in range(0, 16, 4))
    return {"carrier": loc["carrier"], "tracking": tracking, "location": loc,
            "qr": f"PACT-RETURN|{rma}|{loc['carrier']}|{tracking.replace(' ', '')}", "simulated": True}


def _money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")
