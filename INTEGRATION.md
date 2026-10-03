# Plugging a shopper agent into Pact

The merchant side (ZooWork merchant agent, BAND room, Jev gate, UI) is done. `pact/agents/shopper.py`
is a deterministic stand-in shopper so the flow runs end to end. A real shopper agent replaces it by
speaking the protocol below over BAND.

## Identity and room

- The shopper speaks as the BAND agent **`ShopperAgent`**; the merchant is **`MerchantAgent`**.
  Both are registered under Dhanush's BAND account; their agent keys live in gitignored `.env.band`
  (`BAND_SHOPPER_AGENT_KEY`, `BAND_MERCHANT_AGENT_KEY`). Never commit it. `uv run python -m pact.band check` tests them.
- Each deal is one BAND chat room owned by the human account, with both agents as members.
  Today the Pact server creates it in `Deal.setup()` (`pact/deal.py`) via `BandRoom.create`.

## Message format

BAND messages carry only text and mentions, so every Pact message is:

````
@MerchantAgent <human-readable text>

```pact
{"kind": "proposal", ...}
```
````

- Always @mention the other agent (BAND only routes mentioned messages).
- The JSON block must validate against the models in `pact/protocol.py`. `encode_content()`/`decode_content()` in `pact/band.py` do this.
- Never put private constraints (budget ceiling, thresholds) in the text. Only proposals and terms go into the room.

## Sequence

| Step | Sender | `kind` | Notes |
|---|---|---|---|
| 1 | Shopper | `proposal` | `requested_price`, `preferred_variant`, `acceptable_variants`, `delivery_deadline` (ISO date), `minimum_return_days`, optional `competitor_claim: {retailer, price}` (e.g. `{"retailer": "sony.com", "price": 299.99}`); the merchant verifies it with Tavily |
| 2 | Merchant | `counteroffer` | `offers[]`: each `{price, variant, shipping, delivery_date, return_window_days}`. All are inside merchant authority. `competitor_check` = Tavily result (`verified`, `found_price`, `source_url`, `source`: live/cache) |
| 3 | Shopper | `conditional_accept` | Picks one `offer`; `conditions` = term changes it needs (e.g. `{"return_window_days": 45}`), or `{}` to accept as-is |
| 4 | Merchant | `merchant_accept` or `rejection` | `terms` = final offer |
| 5 | Shopper | `agreement` | `terms`, `list_price`, `shopper_savings`. **This triggers the Jev authority gate** (server-side). |

The gate then returns `AUTO_APPROVE` (executes), `HUMAN_APPROVAL_REQUIRED` (UI shows *Approve $X*) or `REJECT`.

## Two ways to bring the shopper in

1. **In-process (simplest):** replace the logic in `pact/agents/shopper.py`. Keep the class shape
   (`start()`, `handle(payload)`, `self.room.post(...)`, `await self.on_agreement(agreement)`), and BAND,
   ZooWork, Jev and the UI all keep working unchanged.
2. **Separate process (e.g. BAND SDK / another framework):** connect as `ShopperAgent` with its key from
   `.env.band`, poll or subscribe for messages that mention it, and follow the sequence above.
   The Pact server still creates the room, runs the merchant and the gate, and mirrors the transcript to the UI.
   **Not wired yet:** the server currently always starts its stand-in shopper, and only shows messages it posted
   itself. This option needs a `PACT_SHOPPER=external` mode (skip the stand-in, watch the BAND room for the
   external shopper's messages, run the gate on its `agreement`). Small change; ask before relying on it.
