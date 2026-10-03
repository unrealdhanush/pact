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
from typing import Awaitable, Callable

from pydantic import BaseModel

from .protocol import RoomMessage
from .transport import Handler

log = logging.getLogger("pact.band")

AGENT_NAMES = ("ShopperAgent", "MerchantAgent")
# BAND sits behind Cloudflare, which rejects the default Python-urllib signature (error 1010).
USER_AGENT = "pact-agents/0.1 (+https://github.com/unrealdhanush/pact)"
PAYLOAD_RE = re.compile(r"\n*```pact\n(.*?)\n```\s*$", re.S)
Request = Callable[[str, str, str, dict | None], Awaitable[dict]]


@dataclass
class BandConfig:
    shopper_key: str
    merchant_key: str
    base_url: str = "https://app.band.ai/api/v1"
    ws_url: str = "wss://app.band.ai/api/v1/socket/websocket"
    ws_timeout: float = 6.0
    human_key: str = ""  # optional; when set, deal rooms are created by (and visible to) the human account

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
            human_key=human_key(),
        )


class BandError(RuntimeError):
    pass


async def urllib_request(method: str, url: str, key: str, body: dict | None) -> dict:
    def call() -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "X-API-Key": key, "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise BandError(f"{method} {urllib.parse.urlparse(url).path} → {e.code} "
                            f"{e.read()[:300].decode(errors='replace')}") from None
        except (TimeoutError, OSError) as e:  # read timeouts aren't URLError; degrade like any BAND failure
            if isinstance(e, urllib.error.URLError):
                raise BandError(f"{method} {url} unreachable: {e.reason}") from None
            raise BandError(f"{method} {urllib.parse.urlparse(url).path} timed out ({type(e).__name__})") from None
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
        if ident.id:
            content = content.replace(f"@[[{ident.id}]]", f"@{ident.name}")  # BAND's stored mention token
    return content.strip(), payload


class AgentSocket:
    """One persistent BAND WebSocket per agent key, shared by every deal room.

    BAND rate-limits WebSocket connects (HTTP 429), so rooms join/leave topics on
    a long-lived connection instead of opening sockets per deal.
    """
    pool: dict[tuple[str, str], "AgentSocket"] = {}

    def __init__(self, ws_url: str, key: str, name: str):
        self.ws_url, self.key, self.name = ws_url, key, name
        self.ws = None
        self.rooms: dict[str, tuple["BandRoom", Identity]] = {}
        self._replies: dict[str, asyncio.Future] = {}
        self._ref = 0
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    @classmethod
    def get(cls, ws_url: str, ident: Identity) -> "AgentSocket":
        sock = cls.pool.get((ws_url, ident.key))
        if sock is None:
            sock = cls.pool[(ws_url, ident.key)] = cls(ws_url, ident.key, ident.name)
        return sock

    def _next_ref(self) -> str:
        self._ref += 1
        return str(self._ref)

    async def _ensure(self) -> None:
        if self.ws is not None:
            return
        from websockets.asyncio.client import connect
        from websockets.exceptions import InvalidStatus
        url = f"{self.ws_url}?{urllib.parse.urlencode({'api_key': self.key, 'vsn': '2.0.0'})}"
        delay = 1.0
        for attempt in range(4):
            try:
                self.ws = await asyncio.wait_for(connect(url, open_timeout=8, user_agent_header=USER_AGENT), 10)
                break
            except InvalidStatus as e:
                if e.response.status_code != 429 or attempt == 3:
                    raise
                log.warning("BAND websocket 429 for %s; retrying in %.0fs", self.name, delay)
                await asyncio.sleep(delay)
                delay *= 2
        for coro in (self._reader(self.ws), self._heartbeat(self.ws)):
            t = asyncio.create_task(coro)
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

    async def join(self, topic: str, room: "BandRoom", ident: Identity) -> None:
        async with self._lock:
            await self._ensure()
            self.rooms[topic] = (room, ident)
            ref = self._next_ref()
            fut = asyncio.get_running_loop().create_future()
            self._replies[ref] = fut
            await self.ws.send(json.dumps([ref, ref, topic, "phx_join", {}]))
        reply = await asyncio.wait_for(fut, 8)
        if reply.get("status") != "ok":
            self.rooms.pop(topic, None)
            raise BandError(f"join {topic} as {ident.name}: {reply.get('response')}")

    async def leave(self, topic: str) -> None:
        if self.rooms.pop(topic, None) and self.ws is not None:
            try:
                ref = self._next_ref()
                await self.ws.send(json.dumps([ref, ref, topic, "phx_leave", {}]))
            except Exception:  # noqa: BLE001
                pass

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(25)
            await ws.send(json.dumps([None, self._next_ref(), "phoenix", "heartbeat", {}]))

    async def _reader(self, ws) -> None:
        try:
            async for raw in ws:
                try:
                    frame = json.loads(raw)
                    _, ref, topic, event, payload = frame
                    if event == "phx_reply" and ref in self._replies:
                        self._replies.pop(ref).set_result(payload)
                    elif topic in self.rooms:
                        room, ident = self.rooms[topic]
                        room._handle_frame(frame, ident)
                except Exception as e:  # noqa: BLE001
                    log.warning("bad BAND frame for %s: %s", self.name, e)
        except Exception as e:  # noqa: BLE001
            log.warning("BAND socket for %s closed: %s", self.name, e)
        finally:
            if self.ws is ws:
                self.ws = None
            for room, _ in list(self.rooms.values()):
                room.stats["ws_connected"] = max(0, room.stats.get("ws_connected", 1) - 1)
            self.rooms.clear()


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
        self.owner = ""
        self.degraded = False
        self.last_error = ""
        self._request = request or urllib_request
        self._handlers: list[Handler] = []
        self._tasks: set[asyncio.Task] = set()
        self._pending: dict[str, _Pending] = {}
        self._seen: set[str] = set()
        self._early: dict[str, dict] = {}
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
        if config.human_key:
            # Human-owned room (INTEGRATION.md): the owner can watch the deal live in the BAND app.
            human = lambda method, path, body: room._request(method, f"{config.base_url}{path}", config.human_key, body)
            chat = _data(await human("POST", "/me/chats", {"chat": {"title": room.title}}))
            room.chat_id = str(chat.get("id", ""))
            if not room.chat_id:
                raise BandError("POST /me/chats returned no room id")
            for ident in room.identities.values():
                await human("POST", f"/me/chats/{room.chat_id}/participants",
                            {"participant": {"participant_id": ident.id, "role": "member"}})
            room.owner = "human"
        else:
            chat = _data(await room._call("POST", "/agent/chats", "ShopperAgent", {"chat": {"title": room.title}}))
            room.chat_id = str(chat.get("id", ""))
            if not room.chat_id:
                raise BandError("POST /agent/chats returned no room id")
            await room._call("POST", f"/agent/chats/{room.chat_id}/participants", "ShopperAgent",
                             {"participant": {"participant_id": room.identities["MerchantAgent"].id, "role": "member"}})
            room.owner = "ShopperAgent"
        room.transport_name = "BAND (live)"
        if connect_ws:
            await room._connect_sockets()
        return room

    async def _connect_sockets(self) -> None:
        topic = f"chat_room:{self.chat_id}"
        results = await asyncio.gather(
            *(AgentSocket.get(self.config.ws_url, i).join(topic, self, i) for i in self.identities.values()),
            return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        for f in failures:
            log.warning("BAND websocket failed: %s", f)
            self.last_error = f"WebSocket: {f}"
        self.stats["ws_connected"] = len(results) - len(failures)
        if failures:
            self.transport_name = "BAND (live post · local delivery)"
        self._status()

    # ------------------------------------------------------------ delivery
    def _handle_frame(self, frame: list, receiver: Identity | None = None) -> None:
        _, _, topic, event, payload = frame
        if event != "message_created" or topic != f"chat_room:{self.chat_id}":
            return
        band_id = str(payload.get("id", ""))
        pending = self._pending.get(band_id)
        if pending is None:
            # The socket can beat the REST response that tells us this id.
            self._early[band_id] = (payload, receiver)
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
        if receiver is not None:
            self._spawn(self._ack(band_id, receiver))

    async def _ack(self, band_id: str, receiver: Identity) -> None:
        """Run BAND's processing lifecycle so delivered messages don't sit as pending."""
        base = f"/agent/chats/{self.chat_id}/messages/{band_id}"
        try:
            await self._call("POST", f"{base}/processing", receiver.name, {})
            await self._call("POST", f"{base}/processed", receiver.name, {})
            self.stats["acked"] = self.stats.get("acked", 0) + 1
        except BandError as e:
            log.warning("BAND ack for %s failed: %s", band_id, e)

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
                "live": not self.degraded, "error": self.last_error, "owner": self.owner, **self.stats}

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
            self._handle_frame([None, None, f"chat_room:{self.chat_id}", "message_created", early[0]], early[1])
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
        topic = f"chat_room:{self.chat_id}"
        for ident in self.identities.values():
            sock = AgentSocket.pool.get((self.config.ws_url, ident.key))
            if sock:
                await sock.leave(topic)
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
    if not key or os.getenv("VERCEL"):  # never self-register agents on serverless; use env agent keys
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
            cache.chmod(0o600)
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
