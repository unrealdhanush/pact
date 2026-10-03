import asyncio
import json

import pytest

from pact import band
from pact.band import BandConfig, BandError, BandRoom, decode_content, encode_content
from pact.deal import Deal

KEYS = {"skey": ("sid-1", "ShopperAgent", "sunny/shopper-agent"), "mkey": ("mid-2", "MerchantAgent", "sunny/merchant-agent")}


class FakeBand:
    """Just enough of the BAND Agent + Human API to drive a deal."""

    def __init__(self, ws: bool = True, fail_messages: bool = False):
        self.calls: list[tuple[str, str, str, dict | None]] = []
        self.room: BandRoom | None = None
        self.ws = ws
        self.fail_messages = fail_messages
        self.n = 0

    async def __call__(self, method, url, key, body):
        path = url.split("/api/v1", 1)[1]
        self.calls.append((method, path, key, body))
        if path == "/agent/me":
            i, name, handle = KEYS[key]
            return {"data": {"id": i, "name": name, "handle": handle}}
        if path == "/agent/chats":
            return {"data": {"id": "chat-42", "title": body["chat"]["title"]}}
        if path.endswith("/participants"):
            return {"data": {"id": body["participant"]["participant_id"], "role": "member"}}
        if path.endswith("/messages"):
            if self.fail_messages:
                raise BandError("POST /messages → 503 shedding")
            self.n += 1
            mid = f"msg-{self.n}"
            if self.ws and self.room:
                frame = [None, None, "chat_room:chat-42", "message_created",
                         {"id": mid, "content": body["message"]["content"], "message_type": "text",
                          "metadata": {"mentions": body["message"]["mentions"]}}]
                # deliver before the REST response returns, like a fast socket
                self.room._handle_frame(frame)
            return {"data": {"id": mid, "success": True}}
        if path.endswith("/events"):
            return {"data": {"id": "ev", "success": True}}
        if path == "/me/agents/register":
            name = body["agent"]["name"]
            return {"data": {"agent": {"id": name.lower()}, "credentials": {"api_key": f"key-{name}"}}}
        raise AssertionError(f"unexpected {method} {path}")


CFG = BandConfig(shopper_key="skey", merchant_key="mkey", ws_timeout=0.05)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for k in ("BAND_SHOPPER_AGENT_KEY", "BAND_MERCHANT_AGENT_KEY", "BAND_API_KEY", "BAND_HUMAN_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_content_roundtrip_maps_mentions_and_payload():
    room = BandRoom("deal-1842", CFG)
    room.identities["MerchantAgent"].handle = "sunny/merchant-agent"
    content = encode_content("@MerchantAgent can you do $215?", {"kind": "proposal", "x": 1}, room.identities)
    assert content.startswith("@sunny/merchant-agent can you do $215?")
    assert "```pact\n" in content
    assert decode_content(content, room.identities) == ("@MerchantAgent can you do $215?", {"kind": "proposal", "x": 1})


async def run_deal(fake: FakeBand) -> Deal:
    room = await BandRoom.create("deal-1842", CFG, request=fake, connect_ws=False)
    fake.room = room
    deal = Deal(pace=0, deal_id="deal-1842")
    deal.room = room
    await deal.run()
    for _ in range(300):
        if deal.status != "negotiating":
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.15)
    return deal


async def test_live_band_room_carries_the_whole_negotiation():
    fake = FakeBand(ws=True)
    deal = await run_deal(fake)
    assert deal.status == "awaiting_approval"
    assert deal.room.transport_name == "BAND (live)"

    create = next(c for c in fake.calls if c[1] == "/agent/chats")
    assert create[3] == {"chat": {"title": "#DEAL-1842"}} and create[2] == "skey"
    part = next(c for c in fake.calls if c[1].endswith("/participants"))
    assert part[3]["participant"]["participant_id"] == "mid-2"

    sends = [c for c in fake.calls if c[1].endswith("/messages")]
    assert len(sends) == 5 and deal.room.stats["ws_delivered"] == 5 and deal.room.stats["local_delivered"] == 0
    for method, path, key, body in sends:
        m = body["message"]
        target = m["mentions"][0]["id"]
        assert target == ("mid-2" if key == "skey" else "sid-1")  # each agent posts with its own key, mentions the other
        assert m["content"].startswith("@sunny/")
        for secret in ("$220", "$205", "$168", "17 units", "13%", "max_price", "unit_cost"):
            assert secret not in m["content"]

    events = [c for c in fake.calls if c[1].endswith("/events")]
    assert events and "HUMAN_APPROVAL_REQUIRED" in events[0][3]["event"]["content"]
    deal.approve()
    await asyncio.sleep(0.02)
    assert "Approved by the shopper's human" in [c for c in fake.calls if c[1].endswith("/events")][-1][3]["event"]["content"]


async def test_missing_socket_delivery_falls_back_locally_and_is_counted():
    deal = await run_deal(FakeBand(ws=False))
    assert deal.status == "awaiting_approval"
    assert deal.room.stats["ws_delivered"] == 0 and deal.room.stats["local_delivered"] == 5


async def test_band_outage_mid_deal_degrades_without_stalling():
    deal = await run_deal(FakeBand(fail_messages=True))
    assert deal.status == "awaiting_approval"
    assert deal.room.transport_name == "local (BAND failed — simulated)"
    assert "503" in deal.room.status()["error"]


async def test_setup_failure_uses_labelled_local_room():
    async def down(method, url, key, body):
        raise BandError("unreachable")
    deal = Deal(pace=0, band=CFG)
    orig = BandRoom.create
    BandRoom.create = classmethod(lambda cls, i, c: orig.__func__(cls, i, c, request=down, connect_ws=False))
    try:
        await deal.setup()
    finally:
        BandRoom.create = orig
    assert deal.room.transport_name == "local (BAND failed — simulated)"
    assert "unreachable" in deal.room.status()["error"]


async def test_bootstrap_registers_two_agents_with_human_key(monkeypatch, tmp_path):
    monkeypatch.setenv("BAND_HUMAN_API_KEY", "human-key")
    fake = FakeBand()
    cfg = await band.bootstrap_agents(request=fake, cache=tmp_path / ".env.band")
    assert (cfg.shopper_key, cfg.merchant_key) == ("key-ShopperAgent", "key-MerchantAgent")
    regs = [c for c in fake.calls if c[1] == "/me/agents/register"]
    assert [c[3]["agent"]["name"] for c in regs] == ["ShopperAgent", "MerchantAgent"]
    assert all(c[2] == "human-key" for c in regs)
    cached = (tmp_path / ".env.band").read_text()
    assert "BAND_SHOPPER_AGENT_KEY=key-ShopperAgent" in cached
    # second call reuses keys instead of registering more agents
    assert await band.bootstrap_agents(request=fake, cache=tmp_path / ".env.band") == cfg
    assert len([c for c in fake.calls if c[1] == "/me/agents/register"]) == 2


def test_status_labels():
    assert band.integration_status()["mode"] == "fallback"


def test_ws_frame_for_other_room_is_ignored():
    room = BandRoom("deal-1842", CFG)
    room.chat_id = "chat-42"
    room._handle_frame([None, None, "chat_room:other", "message_created", {"id": "x", "content": "hi"}])
    assert room._early == {}
    json.dumps(room.status())
