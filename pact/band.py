"""BAND transport: each deal is a real BAND chat room.

The human account owns the room (so it can be watched live at app.band.ai);
the shopper and merchant are separate BAND remote agents, each posting with its
own key. Agents receive messages only via BAND: each polls its own queue
(`/messages/next`) and marks every message processing → processed, so BAND
holds the authoritative, auditable transcript.

BAND messages carry text + mentions only, so the structured Pact payload rides
along as a fenced ```pact block after the human-readable text.
"""
import asyncio
import json
import os
import re
import time
from pathlib import Path

from band_rest import AsyncRestClient, ChatMessageRequest, ParticipantRequest
from band_rest.types.chat_message_request_mentions_item import ChatMessageRequestMentionsItem
from band_rest.human_api_chats.types.create_my_chat_room_request_chat import CreateMyChatRoomRequestChat
from pydantic import BaseModel

from .protocol import RoomMessage
from .transport import Handler

STATE_FILE = Path(__file__).resolve().parent.parent / ".local" / "band.json"
AGENTS = {
    "ShopperAgent": "Pact shopper agent: negotiates purchases on behalf of a human buyer within their private budget "
                    "and preferences.",
    "MerchantAgent": "Pact merchant agent (Aria Audio, runs on ZooWork): negotiates price, shipping and returns "
                     "within merchant margin and discount authority.",
}
POLL_S = 0.4
_BLOCK = re.compile(r"\n*```pact\n(.*?)\n```\s*$", re.S)


def human_client() -> AsyncRestClient:
    key = os.environ.get("BAND_API_KEY")
    if not key:
        raise RuntimeError("BAND_API_KEY is not set")
    return AsyncRestClient(api_key=key, base_url=os.environ.get("BAND_REST_URL"), timeout=20)


def load_band_agents() -> dict | None:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else None


def encode(text: str, payload: dict | None) -> str:
    return f"{text}\n\n```pact\n{json.dumps(payload, separators=(',', ':'))}\n```" if payload else text


def decode(content: str) -> tuple[str, dict | None]:
    m = _BLOCK.search(content)
    if not m:
        return content, None
    return content[:m.start()].rstrip(), json.loads(m.group(1))


class BandRoom:
    transport_name = "BAND"

    def __init__(self, room_id: str, chat_id: str, agents: dict, clients: dict[str, AsyncRestClient]):
        self.id = room_id
        self.chat_id = chat_id
        self.history: list[RoomMessage] = []
        self._agents = agents  # name -> {agent_id, api_key}
        self._clients = clients  # name -> agent-scoped REST client
        self._observers: list[Handler] = []
        self._tasks: set[asyncio.Task] = set()
        self._stopped = False

    @classmethod
    async def create(cls, room_id: str, title: str) -> "BandRoom":
        agents = load_band_agents()
        if not agents or not all(n in agents for n in AGENTS):
            raise RuntimeError("BAND agents not registered — run `python -m pact.band_setup`")
        human = human_client()
        chat = await human.human_api_chats.create_my_chat_room(chat=CreateMyChatRoomRequestChat(title=title))
        chat_id = chat.data.id
        for name in AGENTS:
            await human.human_api_participants.add_my_chat_participant(
                chat_id, participant=ParticipantRequest(participant_id=agents[name]["agent_id"], role="member"))
        clients = {n: AsyncRestClient(api_key=agents[n]["api_key"], base_url=os.environ.get("BAND_REST_URL"),
                                      timeout=20) for n in AGENTS}
        return cls(room_id, chat_id, agents, clients)

    # Room protocol ------------------------------------------------------
    def subscribe(self, handler: Handler, as_participant: str | None = None) -> None:
        if as_participant is None:
            self._observers.append(handler)  # UI mirror: sees what BAND accepted
        else:
            self._spawn(self._receive_loop(as_participant, handler))

    async def post(self, sender, text, payload=None, mentions=None) -> RoomMessage:
        body = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        mention_items = [ChatMessageRequestMentionsItem(id=self._agents[m]["agent_id"], name=m)
                         for m in (mentions or []) if m in self._agents]
        res = await self._clients[sender].agent_api_messages.create_agent_chat_message(
            self.chat_id, message=ChatMessageRequest(content=encode(text, body), mentions=mention_items))
        msg = RoomMessage(id=res.data.id, room=self.id, sender=sender, mentions=mentions or [], text=text,
                          payload=body, ts=time.time())
        self.history.append(msg)
        for h in self._observers:
            self._spawn(h(msg))
        return msg

    def close(self) -> None:
        self._stopped = True

    # internals ----------------------------------------------------------
    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _receive_loop(self, name: str, handler: Handler) -> None:
        api = self._clients[name].agent_api_messages
        while not self._stopped:
            try:
                nxt = await api.get_agent_next_message(self.chat_id)
            except Exception:
                await asyncio.sleep(1)
                continue
            if not nxt or not nxt.data:
                await asyncio.sleep(POLL_S)
                continue
            m = nxt.data
            await api.mark_agent_message_processing(self.chat_id, m.id)
            text, payload = decode(m.content)
            sender = next((n for n, a in self._agents.items() if a["agent_id"] == m.sender_id),
                          m.sender_name or m.sender_id)
            try:
                await handler(RoomMessage(id=m.id, room=self.id, sender=sender, mentions=[name], text=text,
                                          payload=payload, ts=time.time()))
                await api.mark_agent_message_processed(self.chat_id, m.id)
            except Exception as e:
                await api.mark_agent_message_failed(self.chat_id, m.id, error=str(e)[:200])
