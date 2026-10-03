import asyncio
from typing import Callable

from ..protocol import RoomMessage, payload_adapter
from ..transport import Room

# trace(side, kind, text): private reasoning/tool calls shown only on the owner's panel.
Trace = Callable[[str, str, str], None]


class Agent:
    name: str
    side: str

    def __init__(self, room: Room, trace: Trace, pace: float = 1.2):
        self.room = room
        self._trace = trace
        self.pace = pace
        self.reasons: list[str] = []  # surfaced in "Why this deal?"
        room.subscribe(self._dispatch)

    def think(self, text: str) -> None:
        self._trace(self.side, "think", text)

    def tool(self, text: str) -> None:
        self._trace(self.side, "tool", text)

    async def pause(self, factor: float = 1.0) -> None:
        await asyncio.sleep(self.pace * factor)

    async def _dispatch(self, msg: RoomMessage) -> None:
        if msg.sender == self.name or self.name not in msg.mentions or not msg.payload:
            return
        await self.handle(payload_adapter.validate_python(msg.payload))

    async def handle(self, payload) -> None:
        raise NotImplementedError
