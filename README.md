# Pact

The transaction layer for agentic commerce. A shopper's agent and a merchant's agent
negotiate one deal inside their owners' private boundaries; Pact checks whether they are
actually authorized to execute it; a human approves the exception.

```bash
pip install uv                      # if you don't have it
uv sync
cp .env.example .env                # optional — everything runs without keys, labelled SIMULATED
uv run uvicorn pact.server:app --port 8000   # open http://localhost:8000
uv run pytest -q
```

URL options: `?pace=0.8` (default; seconds per agent step, `0.4` is snappy), `?id=deal-1842` (default room id).
Keys: `Enter` starts, `A` approves.

## Live vs simulated

The header shows one badge per sponsor integration: green **LIVE** or amber **SIMULATED**
(hover for details). Nothing mocked is ever labelled live.

| Integration | Live when | Fallback |
|---|---|---|
| **BAND** (deal room) | `BAND_HUMAN_API_KEY` (registers ShopperAgent + MerchantAgent once and caches their keys in gitignored `.env.band`) **or** `BAND_SHOPPER_AGENT_KEY` + `BAND_MERCHANT_AGENT_KEY` | In-process room, "local (simulated)". If BAND fails mid-deal the room degrades to local delivery and says so. |
| **Jev** (authority gate) | `pact/authority.py` (merchant side) exposes `check_authority`; uses `JEV_API_KEY` / `JEV_BASE_URL` | Deterministic local policy rules in `pact/gate.py`, shown as "Jev live decision service unavailable — local policy rules". |
| **ZooWork** (merchant runtime) | `pact/zoowork.py` exposes `integration_status()` | Local merchant agent on the deterministic engine. |
| **Tavily** (competitor price) | `pact/tavily.py` exposes `integration_status()` | No competitor check shown. |

Checkout and inventory reservation are always simulated (no payments).

### BAND setup (free hackathon tier — no credits needed, but a login is)

BAND authenticates every Agent API call with that agent's own key, and agents can only be
created by a logged-in human. Either:

1. **One key:** band.ai → avatar → Settings → copy your *human* API key into `.env` as
   `BAND_HUMAN_API_KEY=…`. On the first deal Pact registers `ShopperAgent` and `MerchantAgent`
   (`POST /api/v1/me/agents/register`) and writes their keys to `.env.band` (keys are shown only once).
2. **Two keys:** band.ai → Agents → New Agent → *External Agent*, twice (ShopperAgent, MerchantAgent,
   same owner so they can share a room). Put the keys in `.env` as `BAND_SHOPPER_AGENT_KEY` /
   `BAND_MERCHANT_AGENT_KEY`.

Check connectivity: `uv run python -m pact.band check` — validates both agents, opens a `#DEAL-1842`
room, sends an @mention and confirms delivery over the WebSocket.

Optional overrides: `BAND_BASE_URL` (default `https://app.band.ai/api/v1`), `BAND_WS_URL`,
`BAND_WS_TIMEOUT` (seconds before a message falls back to local delivery, default 6).

What happens on BAND per deal: the shopper agent creates a room titled `#DEAL-1842`, adds the
merchant agent, and every negotiation turn is a text message with a real @mention of the other
agent (`POST /agent/chats/{id}/messages`) carrying the public protocol payload as a ```pact JSON
block. Each agent listens on its own WebSocket (`chat_room:{id}` / `message_created`) and only acts
on messages BAND delivers to it. The Jev decision and the human approval are posted as room events
(`POST /agent/chats/{id}/events`). Private budgets, floors and inventory never enter the room.

## Demo script (≈2 min)

1. "Humans set intent and boundaries." Point at the two private columns: shopper wants black,
   ≤ $220, by Tuesday, asks for approval above $200; merchant has 2 black / 17 silver and a margin floor.
2. Start. The agents negotiate in `#DEAL-1842`: $215 black → black held at $235, silver $219 with
   free next-day → shopper takes silver if returns go to 45 days → merchant accepts.
3. "Pact checks authority." Jev gate: merchant rules PASS, shopper rules APPROVAL REQUIRED,
   decision HUMAN APPROVAL REQUIRED, because $219 is above the $200 auto-approve limit.
4. Open "Why this deal?", then press **APPROVE $219** → TRANSACTION COMPLETE.
5. "Humans define intent. Agents negotiate. Pact checks authority. Humans stay in control."

## Layout

| Path | What |
|---|---|
| `pact/protocol.py` | Wire contracts (Proposal, Counteroffer, ConditionalAccept, MerchantAccept, Agreement). Only these cross the room. |
| `pact/scenario.py` | Mocked product + private shopper/merchant state. |
| `pact/engine.py` | Deterministic negotiation logic. Decides all terms. |
| `pact/agents/` | Shopper and merchant agents. `merchant_tools.py` = the tools the ZooWork agent gets. |
| `pact/transport.py` | `Room` interface + `LocalRoom` (simulated fallback). |
| `pact/band.py` | `BandRoom`: BAND Agent API + WebSocket transport, agent bootstrap, `python -m pact.band check`. |
| `pact/gate.py` | Authority gate seam: calls `pact/authority.py` if present, else local rules; never looser than local rules. |
| `pact/deal.py` | One negotiation: room setup, agents, authority gate, AUTO_APPROVE / HUMAN_APPROVAL_REQUIRED / REJECT paths, event log. |
| `pact/server.py` | FastAPI: `POST /api/deals?pace&id`, SSE `GET /api/deals/{id}/events`, `POST /api/deals/{id}/approve`, `GET /api/integrations`. |
| `web/index.html` | The whole UI. No build step. |

### Contract for the merchant-side adapters

```python
# pact/authority.py
async def check_authority(agreement, shopper_state, merchant_state) -> AuthorityDecision | dict
#   {transaction_id, decision: AUTO_APPROVE|HUMAN_APPROVAL_REQUIRED|REJECT, merchant_policy_ok,
#    shopper_policy_ok, reason, checks: [{side, rule, ok, detail}], source: "jev"|"local", jev_raw}
def integration_status() -> dict   # {"name": "Jev", "mode": "live"|"fallback", "detail": "..."}

# pact/zoowork.py, pact/tavily.py
def integration_status() -> dict
```

SSE event types the UI renders: `message`, `trace`, `phase` (`negotiating` → `checking_authority` →
`awaiting_approval` | `complete` | `failed`), `authority`, `room` (BAND transport stats), `status`.
