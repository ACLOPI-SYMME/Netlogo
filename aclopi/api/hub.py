"""WebSocket fan-out of a session's messages (L5.3). Message formats: docs/websocket.md.

Every message is encoded once and shared by all the session's clients. Each client has its own
bounded queue and its own sender task, so publishing never waits for a client:

- queue full: the queued messages are dropped and the client is marked for resync; its sender
  then sends "resync" and a fresh "snapshot" built from the API's cache (no worker call), so the
  client gets the latest state and the recent events it missed;
- a send that does not complete within SEND_TIMEOUT_S closes that client only;
- "heartbeat" when nothing was sent for HEARTBEAT_S (browsers cannot see protocol pings).

Snapshots are built synchronously in the event loop from the cache that every published message
updates first, so a client never receives a message older than its snapshot.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any

WS_QUEUE = 32
SEND_TIMEOUT_S = 10.0
HEARTBEAT_S = 5.0

# Close codes (WebSocket application range 4000-4999, plus 1001 going away)
WS_CLOSE = {
    "session_not_found": 4404,
    "session_deleted": 4404,
    "session_lost": 4410,
    "session_expired": 4410,
    "platform_starting": 4503,
    "server_shutdown": 1001,
}


def encode(message: dict[str, Any], raw: dict[str, str] | None = None) -> str:
    """JSON text of a message; raw values (already JSON text, e.g. platform-state) are inserted as is."""
    text = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
    if raw:
        extra = "".join(f',"{key}":{value}' for key, value in raw.items() if value is not None)
        text = text[:-1] + extra + "}"
    return text


class Subscriber:
    def __init__(self, maxsize: int = WS_QUEUE) -> None:
        self.maxsize = maxsize
        self.items: deque[str] = deque()
        self.wake = asyncio.Event()
        self.resync_reason: str | None = None
        self.dropped = 0  # since the last resync
        self.total_dropped = 0
        self.resyncs = 0
        self.close_with: tuple[str, str] | None = None  # (code, reason)

    def offer(self, text: str) -> None:
        if self.close_with is not None:
            return
        if len(self.items) >= self.maxsize:
            self.dropped += len(self.items) + 1
            self.total_dropped += len(self.items) + 1
            self.items.clear()
            self.resync_reason = self.resync_reason or "client_too_slow"
        else:
            self.items.append(text)
        self.wake.set()

    def request_resync(self, reason: str) -> None:
        self.items.clear()
        self.resync_reason = reason
        self.wake.set()

    def request_close(self, code: str, reason: str) -> None:
        self.close_with = (code, reason)
        self.items.clear()
        self.wake.set()


class SessionHub:
    def __init__(self, session_id: str, queue_size: int = WS_QUEUE) -> None:
        self.session_id = session_id
        self.queue_size = queue_size
        self.subscribers: set[Subscriber] = set()
        self.seq = 0
        self.closed: tuple[str, str] | None = None
        # statistics (bench / health)
        self.published = 0
        self.published_bytes = 0
        self.bytes_by_type: dict[str, list[int]] = {}

    def __len__(self) -> int:
        return len(self.subscribers)

    def subscribe(self) -> Subscriber:
        sub = Subscriber(self.queue_size)
        self.subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self.subscribers.discard(sub)

    def publish(self, message: dict[str, Any], raw: dict[str, str] | None = None) -> str:
        self.seq += 1
        message["seq"] = self.seq
        text = encode(message, raw)
        self.published += 1
        self.published_bytes += len(text)
        stats = self.bytes_by_type.setdefault(message.get("type", "?"), [0, 0])
        stats[0] += 1
        stats[1] += len(text)
        for sub in self.subscribers:
            sub.offer(text)
        return text

    def resync_all(self, reason: str) -> None:
        for sub in self.subscribers:
            sub.request_resync(reason)

    def close_all(self, code: str, reason: str) -> None:
        self.closed = (code, reason)
        for sub in self.subscribers:
            sub.request_close(code, reason)


def closed_message(code: str, reason: str) -> str:
    return encode({"type": "closed", "code": code, "reason": reason})


def heartbeat_message() -> str:
    return encode({"type": "heartbeat", "server_time": round(time.time(), 3)})
