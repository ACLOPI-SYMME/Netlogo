"""WebSocket fan-out (aclopi.api.hub / ws._sender) with a fake socket: slow-client handling."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aclopi.api import hub as hub_module
from aclopi.api.hub import SessionHub, encode
from aclopi.api.ws import _sender


class FakeSocket:
    """send_text blocks while `blocked` is clear (a client that does not read)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.blocked = asyncio.Event()
        self.blocked.set()
        self.closed_with: int | None = None

    async def send_text(self, text: str) -> None:
        await self.blocked.wait()
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_with = code


def test_encode_inserts_raw_json() -> None:
    text = encode({"type": "tick", "seq": 1}, raw={"state": '{"tick":5,"products":[]}'})
    assert json.loads(text) == {"type": "tick", "seq": 1, "state": {"tick": 5, "products": []}}


def test_slow_client_gets_resync_and_does_not_block_others() -> None:
    async def scenario() -> tuple[FakeSocket, FakeSocket, int]:
        hub = SessionHub("s", queue_size=8)
        fast_ws, slow_ws = FakeSocket(), FakeSocket()
        fast_sub, slow_sub = hub.subscribe(), hub.subscribe()
        state = {"tick": 0}

        def snapshot() -> str:
            return encode({"type": "snapshot", "seq": hub.seq, "tick": state["tick"]})

        tasks = [asyncio.create_task(_sender(ws, sub, snapshot(), snapshot))
                 for ws, sub in ((fast_ws, fast_sub), (slow_ws, slow_sub))]
        await asyncio.sleep(0.01)
        slow_ws.blocked.clear()  # the slow client stops reading
        for tick in range(1, 101):
            state["tick"] = tick
            hub.publish({"type": "tick", "tick": tick})  # never waits for a client
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        dropped = slow_sub.total_dropped
        slow_ws.blocked.set()  # it reads again
        await asyncio.sleep(0.05)
        hub.close_all("session_deleted", "bye")
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        return fast_ws, slow_ws, dropped

    fast_ws, slow_ws, dropped = asyncio.run(scenario())
    fast_ticks = [m["tick"] for m in fast_ws.sent if m["type"] == "tick"]
    assert fast_ticks == list(range(1, 101))  # the fast client got everything, in order
    assert dropped > 0
    kinds = [m["type"] for m in slow_ws.sent]
    assert "resync" in kinds
    i = kinds.index("resync")
    assert slow_ws.sent[i]["reason"] == "client_too_slow" and slow_ws.sent[i]["dropped"] > 0
    assert kinds[i + 1] == "snapshot"
    after = [m["tick"] for m in slow_ws.sent[i + 2:] if m["type"] == "tick"]
    assert all(t > slow_ws.sent[i + 1]["tick"] for t in after)  # nothing older than the snapshot
    assert slow_ws.sent[-1]["type"] == "closed" and slow_ws.closed_with == hub_module.WS_CLOSE["session_deleted"]


def test_heartbeat_when_idle(monkeypatch: Any) -> None:
    monkeypatch.setattr("aclopi.api.ws.HEARTBEAT_S", 0.05)

    async def scenario() -> FakeSocket:
        hub = SessionHub("s")
        ws, sub = FakeSocket(), hub.subscribe()
        task = asyncio.create_task(_sender(ws, sub, encode({"type": "snapshot"}), lambda: ""))
        await asyncio.sleep(0.18)
        hub.close_all("session_expired", "idle")
        await asyncio.wait_for(task, 5)
        return ws

    ws = asyncio.run(scenario())
    kinds = [m["type"] for m in ws.sent]
    assert kinds[0] == "snapshot" and kinds.count("heartbeat") >= 2 and kinds[-1] == "closed"
    assert ws.closed_with == 4410
