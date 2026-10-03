# Presenting Pact

Run `uv sync`, then `uv run uvicorn pact.server:app --port 8017` and open http://127.0.0.1:8017.

The frontend uses system fonts, local product renders, and a locally bundled map library; it has no font download or frontend build step. The backend and negotiation contracts are unchanged.

## One-minute preset demo

1. Open the landing page, click **Try Pact**, and point to shopper budget / approval threshold and merchant margin floor. Additional rules expand from each agent card.
2. Click **Find a deal** (or Enter). “The shopper asks. Merchants negotiate inside their private boundaries.”
3. Follow the transcript and the horizontal price trail. The preset compares two merchants; the selected offer may be black from SoundHub rather than silver from Aria. Explain the actual selected offer shown.
4. At the authority gate, point to merchant rules passing and the shopper's approval threshold. “An agreement is not authority to spend.”
5. Click **Approve** (or A). Show completion and the simulated checkout disclosure.
6. Click **Find another deal** to replay.

For a custom-intent demo, type a request in the shopper panel, send it, and pick a product or confirm the agent's read-back. The preset button is the quickest presentation path.

`?pace=0.4` accelerates the demo; default is 0.8 seconds per step. Spoken replies are off by default; `?voice=1` enables them. Microphone input depends on browser support and permission; typed input is always available.

All integration badges preserve their real live/simulated status. No keys are required for the local fallback demo. Checkout never takes payment. Live sponsor services require the existing setup in README.md; their availability has not been verified by the local demo checks.

At narrow widths the panels stack; the negotiation transcript scrolls within its panel. Private reasoning and evaluated rules expand on demand. Connection interruptions show a reconnect notice; failed startup and approvals expose retry controls.

The overview and workspace use separate URL views (`/` and `/#workspace`). Switching between them preserves an ongoing deal; refreshing the browser starts a fresh frontend session. Connections are available from the header disclosure. The approval screen has a **Review negotiation** control for the full transcript.

The shopper's **Budget** and **Ask me above** fields are editable before negotiation. Click **Save limits** before starting; limits lock while a deal is active and unlock for the next deal. A zero approval threshold asks for approval on every purchase. Invalid or negative limits are rejected before changing any saved boundaries.

Use **Sony XM5**, **Momentum 4**, or **Bose Ultra** to switch preset products. Their original AI-generated 3D-style renders are illustrative product visuals, not interactive 3D models or official manufacturer photos. The existing catalog and merchant economics still determine offers.

After checkout, the delivery card follows the backend's simulated tracking events. The courier moves along an embedded real route from South San Francisco through Mission Bay to the Presidio. **Replay route** previews the journey without changing the order status or dates; **Stop preview** returns to the actual tracking stage. Zoom controls and **Show full delivery route** let you inspect the map.

Leaflet is bundled locally. OpenStreetMap supplies tiles when available; if tiles cannot load, a labeled route outline still shows the same road geometry, courier, stops, and progress. No geolocation, carrier feed, or route API is used. The map stays mounted across tracking updates, respects reduced motion, and resizes with the workspace.

## Second act: the return (≈30 s)

After tracking reaches **Delivered**, click **Start a return** and send the prefilled reason
(“They're uncomfortable after an hour — I'd like a refund”). In the same BAND deal room:
the merchant offers an exchange + $15 goodwill (cheapest for the store); the shopper says the same
model won't fix comfort and asks for a refund or store credit with ≥ $30 bonus; the merchant picks
store credit + $30 (cheaper than a refund, inside its $30 goodwill authority). Jev: non-cash
resolution → **your call**. Click **Accept** → simulated return label, posted to the BAND room, and
remembered by Moss. Line: “Same protocol, same room — before and after the purchase.”
