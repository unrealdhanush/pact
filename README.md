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
| **Jev** (authority gate) | `JEV_API_KEY` or `TYPESAFE_API_KEY` set (see [Jev setup](#jev-setup-typesafe-ai)). `pact/authority.py` → `pact/jev.py`: one Choice decision + a Noul risk check on the BAND transcript (flags manipulation / prompt injection) | Deterministic local policy rules in `pact/gate.py`, shown as "Jev live decision service unavailable — local policy rules". |
| **ZooWork** (merchant runtime) | `ZOOWORK_API_KEY` + agent created once with `uv run python -m pact.zoowork_setup` (id in gitignored `.local/zoowork.json`; `--update` after changing its instructions/tools) | Local merchant agent on the deterministic engine; also used per turn if ZooWork errors or times out. |
| **Moss** (shopper memory) | `MOSS_PROJECT_ID` + `MOSS_PROJECT_KEY`; seed once with `uv run python -m pact.memory --seed` (indexes `pact-shopper-memory`, `pact-product-catalog`). Talk panel recall, per-intake session, BAND merchant ranking, outcome write-back | Local keyword search over the same seed memories, labelled. |
| **Tavily** (competitor price) | `TAVILY_API_KEY`: the merchant's `verify_competitor_price` tool checks the shopper's cited price live | Last good live result from `pact/data/competitor_cache.json`, labelled *cached* with its timestamp. |

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

What happens on BAND per deal: with `BAND_HUMAN_API_KEY` set, the human account creates a room
titled `#DEAL-1842` (`POST /me/chats`) and adds both agents, so the owner can watch it live in the
BAND app (without the human key, ShopperAgent creates it). Every negotiation turn is a text message
with a real @mention of the other agent (`POST /agent/chats/{id}/messages`) carrying the public
protocol payload as a ```pact JSON block (see `INTEGRATION.md`). Each agent keeps one WebSocket
(`chat_room:{id}` / `message_created`) shared across deals, only acts on messages BAND delivers to
it, and marks them `processing` → `processed`. The Jev decision and the human approval are posted
as room events (`POST /agent/chats/{id}/events`). Private budgets, floors and inventory never enter the room.

BAND quirks handled: Cloudflare rejects Python's default User-Agent (error 1010); WebSocket connects
are rate-limited (HTTP 429), hence one shared socket per agent with backoff; stored message content
rewrites mentions to `@[[agent-uuid]]`.

`.env.band` is per BAND account. Agents registered on one account can't join rooms owned by another,
so each machine either copies the `.env.band` that matches its `BAND_HUMAN_API_KEY` or deletes it and
lets Pact register a fresh pair (BAND free tier allows 20 agents).

### Jev setup (TypeSafe AI)

Keys come from [console.typesafe.ai/keys](https://console.typesafe.ai/keys). Docs: [docs.typesafe.ai](https://docs.typesafe.ai/introduction/quickstart).

| Env | Default | Meaning |
|---|---|---|
| `JEV_API_KEY` | — | TypeSafe console key, sent as `Authorization: Bearer $JEV_API_KEY` |
| `JEV_BASE_URL` | `https://api.typesafe.ai` | API **root**; the decision endpoint is `$JEV_BASE_URL/v1/systemone` |
| `JEV_MODEL` | `jev-latest` | Required by the API; pin e.g. `jev-1.13.0` for a stable demo |

One call, one Choice question whose options are exactly Pact's three decisions:

```bash
curl -X POST "$JEV_BASE_URL/v1/systemone" -H "Authorization: Bearer $JEV_API_KEY" -H "Content-Type: application/json" -d '{
  "model": "jev-latest",
  "state": {"transaction_id": "deal-1842", "terms": {"price": 219, "variant": "silver", "shipping": "free_next_day", "return_window_days": 45},
            "merchant_policy_checks": "all pass", "shopper_auto_approve_limit_usd": 200, "shopper_max_price_usd": 220},
  "questions": {
    "decision": {"type": "choice", "instructions": "May the agents execute this purchase without a human?",
      "criteria": {"AUTO_APPROVE": "Inside every bound and under the auto-approve limit",
                   "HUMAN_APPROVAL_REQUIRED": "Allowed, but exceeds a human approval threshold or needs sign-off",
                   "REJECT": "Violates a merchant or shopper boundary"}},
    "needs_human": {"type": "noul", "instructions": "Does this purchase require the shopper's human approval?"}
  }}'
# → {"model":"jev-1.13.0","answers":{"decision":{"type":"choice","choice":"HUMAN_APPROVAL_REQUIRED","confidence":…,"probabilities":{…}},
#    "needs_human":{"type":"noul","noul":…}},"usage":{…}}
```

Errors: `401` bad key, `422` invalid body, `429`/`529` retry with backoff. Pact never lets Jev loosen
the local rules (`pact/gate.py` takes the stricter decision) and falls back to them on any error or timeout.
Keys created at the jevtypesafeai.com gateway (`jv_live_…`) are a different service
(`https://jevtypesafeai.com/api/v1/decide`) and do not work at `api.typesafe.ai`.

## Demo script (≈2–3 min)

1. "Humans set intent." In the shopper panel, speak (mic button, Chrome) or type: *"Find me Sony noise-cancelling
   headphones in black, under 300, by Tuesday."* The shopper agent resolves the product and recalls the rest
   from **Moss** memory in single-digit ms: silver is fine with 45-day returns, ask before anything over $250,
   sony.com has it for $299.99. Every boundary is tagged YOU / MEMORY / DEFAULT. Say *"yes"*.
2. "The shopper finds a merchant." It searches **BAND**'s agent directory, ranks the merchant agents with Moss,
   and invites @MerchantAgent into `#DEAL-1842`.
3. The negotiation: $278 black + the sony.com price → the merchant (on **ZooWork**) verifies sony.com live with
   **Tavily** → black held at $319.99, silver price-matched at $299.99 with free next-day → shopper takes silver
   if returns go to 45 days → merchant accepts.
4. "Pact checks authority." **Jev**: merchant rules PASS, shopper rules APPROVAL REQUIRED, decision
   HUMAN APPROVAL REQUIRED ($299.99 is above the $250 limit). Press **APPROVE $299.99** → TRANSACTION COMPLETE.
5. "And it remembers." The outcome is written back to Moss; the next conversation recalls it.
6. "Humans define intent. Agents negotiate. Pact checks authority. Humans stay in control."

## Layout

| Path | What |
|---|---|
| `pact/protocol.py` | Wire contracts (Proposal, Counteroffer, ConditionalAccept, MerchantAccept, Agreement). Only these cross the room. |
| `pact/scenario.py` | Mocked product + private shopper/merchant state. |
| `pact/engine.py` | Deterministic negotiation logic. Decides all terms. |
| `pact/agents/` | Shopper and merchant agents. `zoowork_merchant.py` = ZooWork-hosted merchant (instructions + custom tools, leak guard, local fallback); `merchant_tools.py` = its tools. |
| `pact/zoowork.py`, `pact/zoowork_setup.py` | ZooWork REST client (no official Python SDK) and one-time agent setup. |
| `pact/tavily.py` | Competitor price verification (live Tavily, timestamped cached fallback). |
| `pact/memory.py`, `pact/intake.py` | Moss shopper memory (long-term index + live session + catalog) and the talk-to-your-agent intake (parse → recall → read-back with provenance). |
| `pact/discovery.py` | Shopper finds a merchant: BAND `/agent/peers` ranked by Moss. |
| `pact/authority.py`, `pact/jev.py` | Live authority check for the gate: policy facts in code + Jev decision and transcript risk; can only tighten. |
| `pact/transport.py` | `Room` interface + `LocalRoom` (simulated fallback). |
| `pact/band.py` | `BandRoom`: BAND Agent API + WebSocket transport, agent bootstrap, `python -m pact.band check`. |
| `pact/gate.py` | Authority gate seam: calls `pact/authority.py` if present, else local rules; never looser than local rules. |
| `pact/deal.py` | One negotiation: room setup, agents, authority gate, AUTO_APPROVE / HUMAN_APPROVAL_REQUIRED / REJECT paths, event log. |
| `pact/server.py` | FastAPI: `POST /api/deals?pace&id`, SSE `GET /api/deals/{id}/events`, `POST /api/deals/{id}/approve`, `GET /api/integrations`. |
| `web/index.html` | The whole UI. No build step. |

### Contract for the merchant-side adapters

```python
# pact/authority.py
async def check_authority(agreement, shopper_state, merchant_state, transcript=None) -> AuthorityDecision | dict
#   (transcript is optional: the gate passes it only if the signature accepts it)
#   {transaction_id, decision: AUTO_APPROVE|HUMAN_APPROVAL_REQUIRED|REJECT, merchant_policy_ok,
#    shopper_policy_ok, reason, checks: [{side, rule, ok, detail}], source: "jev"|"local", jev_raw}
def integration_status() -> dict   # {"name": "Jev", "mode": "live"|"fallback", "detail": "..."}
#   reads JEV_API_KEY, JEV_BASE_URL (root, default https://api.typesafe.ai → POST /v1/systemone), JEV_MODEL

# pact/zoowork.py, pact/tavily.py
def integration_status() -> dict
```

SSE event types the UI renders: `message`, `trace`, `phase` (`negotiating` → `checking_authority` →
`awaiting_approval` | `complete` | `failed`), `authority`, `room` (BAND transport stats), `status`.
