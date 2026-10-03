"""Negotiation room transport.

`Room` is the seam where BAND plugs in: agents only ever call `post` and
`subscribe`. `LocalRoom` is the in-process implementation used for development
and as the demo fallback.
"""
import asyncio
import time
import uuid
from typing import Awaitable, Callable, Protocol

from pydantic import BaseModel

from .protocol import RoomMessage

Handler = Callable[[RoomMessage], Awaitable[None]]


class Room(Protocol):
    id: str
    transport_name: str

    def subscribe(self, handler: Handler) -> None: ...

    async def post(self, sender: str, text: str, payload: BaseModel | None = None,
                   mentions: list[str] | None = None) -> RoomMessage: ...


class LocalRoom:
    transport_name = "local (simulated)"

    def __init__(self, room_id: str, fallback_reason: str = ""):
        self.id = room_id
        self.fallback_reason = fallback_reason
        if fallback_reason:
            self.transport_name = "local (BAND failed — simulated)"
        self.history: list[RoomMessage] = []
        self.events: list[dict] = []
        self._handlers: list[Handler] = []
        self._tasks: set[asyncio.Task] = set()

    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    async def post(self, sender, text, payload=None, mentions=None) -> RoomMessage:
        msg = RoomMessage(
            id=uuid.uuid4().hex[:8], room=self.id, sender=sender, mentions=mentions or [],
            text=text, payload=payload.model_dump(mode="json") if payload else None, ts=time.time(),
        )
        self.history.append(msg)
        for h in self._handlers:
            # Dispatch asynchronously so a handler's reply never nests inside post().
            task = asyncio.create_task(h(msg))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return msg

    async def post_event(self, content: str, message_type: str = "task", metadata: dict | None = None,
                         sender: str = "ShopperAgent") -> None:
        self.events.append({"content": content, "message_type": message_type, "metadata": metadata or {},
                            "sender": sender})

    def status(self) -> dict:
        return {"transport": self.transport_name, "chat_id": None, "title": f"#{self.id.upper()}",
                "live": False, "error": self.fallback_reason, "posted": len(self.history),
                "events": len(self.events)}

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
