# Pact

The transaction layer for agentic commerce. A shopper's agent and a merchant's agent
negotiate one deal inside their owners' private boundaries, then stop for human approval.

```bash
uv sync
uv run uvicorn pact.server:app --reload --port 8000   # open http://localhost:8000
uv run pytest -q
```

`?pace=0.4` on the page URL speeds up the agents (default 1.2s per step).

### Live services

```bash
cp .env.example .env                    # fill in keys
uv run python -m pact.band_setup        # once: registers ShopperAgent + MerchantAgent on BAND (.local/band.json)
uv run python -m pact.zoowork_setup     # once: creates + starts the ZooWork merchant agent (.local/zoowork.json)
uv run python -m pact.zoowork_setup --update   # after changing its instructions/tools
```

Demo: Sony WH-1000XM5. The shopper cites sony.com at $299.99; the merchant verifies it live with **Tavily**
(falls back to the committed, timestamped `pact/data/competitor_cache.json`) and price-matches silver.

Flow: shopper agent ⇄ **BAND room** ⇄ merchant agent (**ZooWork**) → agreement → **authority gate (Jev)** →
AUTO_APPROVE executes / HUMAN_APPROVAL_REQUIRED waits for the Approve click / REJECT stops.
The gate computes hard policy checks in code; Jev makes one typed decision plus a risk check and can
only make the outcome stricter. Every fallback (no ZooWork agent, ZooWork error, no Jev key) is labelled in the UI.

## Layout

| Path | What |
|---|---|
| `pact/protocol.py` | Wire contracts (Proposal, Counteroffer, ConditionalAccept, MerchantAccept, Agreement). Only these cross the room. |
| `pact/scenario.py` | Mocked product + private shopper/merchant state. |
| `pact/engine.py` | Deterministic negotiation logic. Decides all terms. |
| `pact/agents/` | Shopper and merchant agents. `zoowork_merchant.py` = ZooWork-hosted merchant (instructions + custom tools), falls back to the local `merchant.py`. |
| `pact/zoowork.py` | ZooWork REST client (no official Python SDK). |
| `pact/tavily.py` | Competitor price verification (live Tavily, cached fallback). |
| `pact/band.py` | BAND room transport (`BandRoom`); `band_setup.py` registers the agents. |
| `pact/jev.py` | Authority gate: policy checks + Jev decision → AUTO_APPROVE / HUMAN_APPROVAL_REQUIRED / REJECT. |
| `pact/transport.py` | `Room` interface + `LocalRoom` (offline fallback). |
| `pact/deal.py` | One negotiation: room + agents + event log + approval gate. |
| `pact/server.py` | FastAPI: `POST /api/deals`, SSE `GET /api/deals/{id}/events`, `POST /api/deals/{id}/approve`. |
| `web/index.html` | The whole UI. No build step. |

## Integration seams

- **BAND**: `BandRoom` (`pact/band.py`) is used by default; `PACT_TRANSPORT=local` forces the in-process room.
- **ZooWork**: host the merchant agent there with `MerchantTools` methods as its tools; the engine
  stays the source of truth for terms so the agent can't exceed its authority.
- **Tavily**: `verify_competitor_price` tool; the engine only price-matches verified prices.

## Honest labels

Inventory, margins and checkout are mocked locally. Execution is marked `simulated` in the API and UI.
