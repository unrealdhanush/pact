"""BAND transport: one BAND chat room per deal, one BAND identity per agent.

Each agent authenticates with its own agent API key. Messages are posted over
the Agent REST API with real @mentions and are delivered back to the
mentioned agent over BAND's Phoenix WebSocket (`chat_room:{id}` /
`message_created`). If a message is not delivered over the socket within
`ws_timeout`, it is delivered in-process and counted as a local fallback,
which the UI shows.

Only public protocol payloads are ever posted. They are appended to the
message as a fenced ```pact JSON block so the receiving agent can parse them.

Docs: https://docs.band.ai/api/agent-api , https://docs.band.ai/websocket/overview
"""
import asyncio
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from .protocol import RoomMessage
from .transport import Handler

log = logging.getLogger("pact.band")

AGENT_NAMES = ("ShopperAgent", "MerchantAgent")
PAYLOAD_RE = re.compile(r"\n*```pact\n(.*?)\n```\s*$", re.S)
Request = Callable[[str, str, str, dict | None], Awaitable[dict]]


@dataclass
class BandConfig:
    shopper_key: str
    merchant_key: str
    base_url: str = "https://app.band.ai/api/v1"
    ws_url: str = "wss://app.band.ai/api/v1/socket/websocket"
    ws_timeout: float = 6.0

    @classmethod
    def from_env(cls) -> "BandConfig | None":
        s, m = os.getenv("BAND_SHOPPER_AGENT_KEY", ""), os.getenv("BAND_MERCHANT_AGENT_KEY", "")
        if not (s and m):
            return None
        return cls(
            shopper_key=s, merchant_key=m,
            base_url=os.getenv("BAND_BASE_URL", cls.base_url).rstrip("/"),
            ws_url=os.getenv("BAND_WS_URL", cls.ws_url),
            ws_timeout=float(os.getenv("BAND_WS_TIMEOUT", cls.ws_timeout)),
        )


class BandError(RuntimeError):
    pass


async def urllib_request(method: str, url: str, key: str, body: dict | None) -> dict:
    def call() -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "X-API-Key": key, "Content-Type": "application/json", "Accept": "application/json",
            # Cloudflare in front of BAND rejects Python-urllib's default UA (error 1010).
            "User-Agent": "pact/0.1 (+https://github.com/unrealdhanush/pact)"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise BandError(f"{method} {urllib.parse.urlparse(url).path} → {e.code} "
                            f"{e.read()[:300].decode(errors='replace')}") from None
        except urllib.error.URLError as e:
            raise BandError(f"{method} {url} unreachable: {e.reason}") from None
        return json.loads(raw) if raw else {}
    return await asyncio.to_thread(call)


@dataclass
class Identity:
    name: str  # Pact-side name, e.g. "MerchantAgent"
    key: str
    id: str = ""
    handle: str = ""
    band_name: str = ""

    @property
    def tag(self) -> str:
        return self.handle or self.band_name or self.name


@dataclass
class _Pending:
    msg: RoomMessage
    delivered: asyncio.Event = field(default_factory=asyncio.Event)


def _data(resp: dict) -> dict:
    return resp.get("data", resp) if isinstance(resp, dict) else {}


def encode_content(text: str, payload: dict | None, identities: dict[str, Identity]) -> str:
    for ident in identities.values():
        text = text.replace(f"@{ident.name}", f"@{ident.tag}")
    if payload is not None:
        text += "\n\n```pact\n" + json.dumps(payload, separators=(",", ":")) + "\n```"
    return text


def decode_content(content: str, identities: dict[str, Identity]) -> tuple[str, dict | None]:
    payload = None
    m = PAYLOAD_RE.search(content)
    if m:
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            payload = None
        content = content[: m.start()]
    for ident in identities.values():
        content = content.replace(f"@{ident.tag}", f"@{ident.name}")
    return content.strip(), payload


class BandRoom:
    def __init__(self, deal_id: str, config: BandConfig, request: Request | None = None):
        self.id = deal_id
        self.title = f"#{deal_id.upper()}"
        self.config = config
        self.chat_id = ""
        self.transport_name = "BAND (connecting)"
        self.history: list[RoomMessage] = []
        self.stats = {"posted": 0, "events": 0, "ws_delivered": 0, "local_delivered": 0, "ws_connected": 0}
        self.on_status: Callable[[dict], None] | None = None
        self.degraded = False
        self.last_error = ""
        self._request = request or urllib_request
        self._handlers: list[Handler] = []
        self._tasks: set[asyncio.Task] = set()
        self._pending: dict[str, _Pending] = {}
        self._seen: set[str] = set()
        self._early: dict[str, dict] = {}
        self._sockets: list[Any] = []
        self.identities = {
            "ShopperAgent": Identity("ShopperAgent", config.shopper_key),
            "MerchantAgent": Identity("MerchantAgent", config.merchant_key),
        }

    # ------------------------------------------------------------ setup
    async def _call(self, method: str, path: str, sender: str, body: dict | None = None) -> dict:
        return await self._request(method, f"{self.config.base_url}{path}", self.identities[sender].key, body)

    @classmethod
    async def create(cls, deal_id: str, config: BandConfig, request: Request | None = None,
                     connect_ws: bool = True) -> "BandRoom":
        room = cls(deal_id, config, request)
        for name, ident in room.identities.items():
            me = _data(await room._call("GET", "/agent/me", name))
            ident.id = str(me.get("id", ""))
            ident.handle = me.get("handle") or ""
            ident.band_name = me.get("name") or ""
            if not ident.id:
                raise BandError(f"/agent/me for {name} returned no id")
        chat = _data(await room._call("POST", "/agent/chats", "ShopperAgent", {"chat": {"title": room.title}}))
        room.chat_id = str(chat.get("id", ""))
        if not room.chat_id:
            raise BandError("POST /agent/chats returned no room id")
        await room._call("POST", f"/agent/chats/{room.chat_id}/participants", "ShopperAgent",
                         {"participant": {"participant_id": room.identities["MerchantAgent"].id, "role": "member"}})
        room.transport_name = "BAND (live)"
        if connect_ws:
            await room._connect_sockets()
        return room

    async def _connect_sockets(self) -> None:
        try:
            from websockets.asyncio.client import connect
        except ImportError:  # pragma: no cover
            self.transport_name = "BAND (live post · local delivery)"
            return
        results = await asyncio.gather(*(self._open_socket(connect, i) for i in self.identities.values()),
                                       return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        for f in failures:
            log.warning("BAND websocket failed: %s", f)
        if failures:
            self.transport_name = "BAND (live post · local delivery)"
        self._status()

    async def _open_socket(self, connect, ident: Identity) -> None:
        url = f"{self.config.ws_url}?{urllib.parse.urlencode({'api_key': ident.key, 'vsn': '2.0.0'})}"
        ws = await asyncio.wait_for(connect(url, open_timeout=8), 10)
        topic = f"chat_room:{self.chat_id}"
        await ws.send(json.dumps(["1", "1", topic, "phx_join", {}]))
        deadline = time.monotonic() + 8
        while True:
            frame = json.loads(await asyncio.wait_for(ws.recv(), max(0.1, deadline - time.monotonic())))
            if frame[2] == topic and frame[3] == "phx_reply" and frame[1] == "1":
                if frame[4].get("status") != "ok":
                    await ws.close()
                    raise BandError(f"join {topic} as {ident.name}: {frame[4].get('response')}")
                break
            self._handle_frame(frame)
        self._sockets.append(ws)
        self.stats["ws_connected"] += 1
        self._spawn(self._reader(ws, ident))
        self._spawn(self._heartbeat(ws))

    async def _heartbeat(self, ws) -> None:
        ref = 100
        while True:
            await asyncio.sleep(25)
            ref += 1
            await ws.send(json.dumps([None, str(ref), "phoenix", "heartbeat", {}]))

    async def _reader(self, ws, ident: Identity) -> None:
        try:
            async for raw in ws:
                try:
                    self._handle_frame(json.loads(raw))
                except Exception as e:  # noqa: BLE001
                    log.warning("bad BAND frame for %s: %s", ident.name, e)
        except Exception as e:  # noqa: BLE001
            log.warning("BAND socket for %s closed: %s", ident.name, e)

    # ------------------------------------------------------------ delivery
    def _handle_frame(self, frame: list) -> None:
        _, _, topic, event, payload = frame
        if event != "message_created" or topic != f"chat_room:{self.chat_id}":
            return
        band_id = str(payload.get("id", ""))
        pending = self._pending.get(band_id)
        if pending is None:
            # The socket can beat the REST response that tells us this id.
            self._early[band_id] = payload
            return
        if pending.delivered.is_set():
            return
        text, parsed = decode_content(payload.get("content", ""), self.identities)
        msg = pending.msg
        if parsed is not None:
            msg = msg.model_copy(update={"payload": parsed})
        pending.msg = msg
        pending.delivered.set()
        self.stats["ws_delivered"] += 1
        self._dispatch(msg)

    def _dispatch(self, msg: RoomMessage) -> None:
        if msg.id in self._seen:
            return
        self._seen.add(msg.id)
        self._status()
        for h in self._handlers:
            self._spawn(h(msg))

    async def _await_delivery(self, band_id: str) -> None:
        pending = self._pending[band_id]
        try:
            await asyncio.wait_for(pending.delivered.wait(), self.config.ws_timeout)
        except asyncio.TimeoutError:
            pending.delivered.set()
            self.stats["local_delivered"] += 1
            self._dispatch(pending.msg)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _status(self) -> None:
        if self.on_status:
            self.on_status(self.status())

    def status(self) -> dict:
        return {"transport": self.transport_name, "chat_id": self.chat_id, "title": self.title,
                "live": not self.degraded, "error": self.last_error, **self.stats}

    # ------------------------------------------------------------ Room interface
    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    async def post(self, sender: str, text: str, payload: BaseModel | None = None,
                   mentions: list[str] | None = None) -> RoomMessage:
        mentions = mentions or []
        body_payload = payload.model_dump(mode="json") if payload else None
        content = encode_content(text, body_payload, self.identities)
        targets = [self.identities[m] for m in mentions if m in self.identities and m != sender]
        resp: dict = {}
        if self.degraded or not targets:
            if not targets:
                log.warning("BAND text messages need an @mention of another participant; delivering locally")
        else:
            try:
                resp = _data(await self._call("POST", f"/agent/chats/{self.chat_id}/messages", sender, {"message": {
                    "content": content,
                    "mentions": [{"id": t.id, "handle": t.handle, "name": t.band_name or t.name}
                                 if t.handle else {"id": t.id, "name": t.band_name or t.name} for t in targets],
                }}))
            except BandError as e:
                self.degrade(str(e))
        band_id = str(resp.get("id") or f"local-{len(self.history)}")
        msg = RoomMessage(id=band_id, room=self.id, sender=sender, mentions=mentions, text=text,
                          payload=body_payload, ts=time.time())
        self.history.append(msg)
        if not resp.get("id"):
            self.stats["local_delivered"] += 1
            self._dispatch(msg)
            return msg
        self.stats["posted"] += 1
        self._pending[band_id] = _Pending(msg)
        early = self._early.pop(band_id, None)
        if early is not None:
            self._handle_frame([None, None, f"chat_room:{self.chat_id}", "message_created", early])
        self._spawn(self._await_delivery(band_id))
        return msg

    async def post_event(self, content: str, message_type: str = "task", metadata: dict | None = None,
                         sender: str = "ShopperAgent") -> None:
        if self.degraded:
            return
        body: dict = {"content": content, "message_type": message_type}
        if metadata:
            body["metadata"] = metadata
        try:
            await self._call("POST", f"/agent/chats/{self.chat_id}/events", sender, {"event": body})
        except BandError as e:
            log.warning("BAND event failed: %s", e)
            self.last_error = str(e)
            return
        self.stats["events"] += 1
        self._status()

    def degrade(self, reason: str) -> None:
        log.warning("BAND degraded to local delivery: %s", reason)
        self.degraded = True
        self.last_error = reason
        self.transport_name = "local (BAND failed — simulated)"
        self._status()

    async def close(self) -> None:
        for ws in self._sockets:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        for t in list(self._tasks):
            t.cancel()


AGENT_CACHE = Path(__file__).resolve().parent.parent / ".env.band"  # gitignored via .env.*
AGENT_SPECS = {
    "ShopperAgent": ("BAND_SHOPPER_AGENT_KEY", "Pact shopper agent: negotiates purchases inside its human's private bounds."),
    "MerchantAgent": ("BAND_MERCHANT_AGENT_KEY", "Pact merchant agent: makes offers inside the store's private margin and inventory policy."),
}


def human_key() -> str:
    return os.getenv("BAND_HUMAN_API_KEY") or os.getenv("BAND_API_KEY") or ""


async def bootstrap_agents(request: Request | None = None, cache: Path = AGENT_CACHE) -> BandConfig | None:
    """Register ShopperAgent + MerchantAgent as BAND external agents once, using the
    human's API key (`POST /me/agents/register`), and cache their agent keys in `.env.band`."""
    cfg = BandConfig.from_env()
    if cfg:
        return cfg
    key = human_key()
    if not key:
        return None
    request = request or urllib_request
    base = os.getenv("BAND_BASE_URL", BandConfig.base_url).rstrip("/")
    lines = []
    for name, (env, description) in AGENT_SPECS.items():
        if os.getenv(env):
            continue
        resp = _data(await request("POST", f"{base}/me/agents/register", key,
                                   {"agent": {"name": name, "description": description}}))
        agent_key = (resp.get("credentials") or {}).get("api_key")
        if not agent_key:
            raise BandError(f"register {name}: no api_key in response")
        os.environ[env] = agent_key
        lines.append(f"{env}={agent_key}  # BAND agent id {(resp.get('agent') or {}).get('id', '?')}")
    if lines:
        with cache.open("a") as f:
            f.write("# Auto-registered by pact.band — BAND shows agent keys only once.\n" + "\n".join(lines) + "\n")
    return BandConfig.from_env()


def integration_status() -> dict:
    cfg = BandConfig.from_env()
    if cfg:
        return {"name": "BAND", "mode": "live", "detail": f"Agent API {cfg.base_url} · WebSocket delivery"}
    if human_key():
        return {"name": "BAND", "mode": "live",
                "detail": "Human key set — ShopperAgent/MerchantAgent register on first deal"}
    return {"name": "BAND", "mode": "fallback",
            "detail": "No BAND keys — in-process room (simulated). Set BAND_HUMAN_API_KEY or both agent keys."}


async def _check() -> int:
    """`python -m pact.band check`: register/validate agents, open #DEAL-1842, ping the merchant."""
    cfg = await bootstrap_agents()
    if not cfg:
        print("No BAND credentials. Set BAND_HUMAN_API_KEY, or BAND_SHOPPER_AGENT_KEY + BAND_MERCHANT_AGENT_KEY.")
        return 1
    room = await BandRoom.create("deal-1842", cfg)
    got = asyncio.Event()
    room.subscribe(lambda m: asyncio.sleep(0, got.set()))
    for n, i in room.identities.items():
        print(f"{n}: id={i.id} handle={i.handle or '-'} band_name={i.band_name or '-'}")
    print(f"room {room.title} chat_id={room.chat_id} transport={room.transport_name}")
    await room.post("ShopperAgent", "@MerchantAgent Pact connectivity check.", None, ["MerchantAgent"])
    await asyncio.sleep(cfg.ws_timeout + 0.5)
    print("stats", room.stats)
    await room.close()
    return 0 if room.stats["ws_delivered"] else 2


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    load_dotenv(AGENT_CACHE)
    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:] != ["check"]:
        print("usage: python -m pact.band check")
        raise SystemExit(64)
    raise SystemExit(asyncio.run(_check()))
