# Pact

The transaction layer for agentic commerce. A shopper's agent and a merchant's agent
negotiate one deal inside their owners' private boundaries, then stop for human approval.

```bash
uv sync
uv run uvicorn pact.server:app --reload --port 8000   # open http://localhost:8000
uv run pytest -q
```

`?pace=0.4` on the page URL speeds up the agents (default 1.2s per step).

## Layout

| Path | What |
|---|---|
| `pact/protocol.py` | Wire contracts (Proposal, Counteroffer, ConditionalAccept, MerchantAccept, Agreement). Only these cross the room. |
| `pact/scenario.py` | Mocked product + private shopper/merchant state. |
| `pact/engine.py` | Deterministic negotiation logic. Decides all terms. |
| `pact/agents/` | Shopper and merchant agents. `merchant_tools.py` = the tools the ZooWork agent gets. |
| `pact/transport.py` | `Room` interface + `LocalRoom`. **BAND plugs in here.** |
| `pact/deal.py` | One negotiation: room + agents + event log + approval gate. |
| `pact/server.py` | FastAPI: `POST /api/deals`, SSE `GET /api/deals/{id}/events`, `POST /api/deals/{id}/approve`. |
| `web/index.html` | The whole UI. No build step. |

## Integration seams

- **BAND**: implement `BandRoom` with the same `post`/`subscribe` as `LocalRoom`; swap it in `Deal.__init__`.
  The UI's transport chip turns green when the transport name isn't "simulated".
- **ZooWork**: host the merchant agent there with `MerchantTools` methods as its tools; the engine
  stays the source of truth for terms so the agent can't exceed its authority.
- **Tavily**: one competitor-price check in the merchant's proposal handler, cached fallback with timestamp.

## Honest labels

Inventory, margins and checkout are mocked locally. Execution is marked `simulated` in the API and UI.
