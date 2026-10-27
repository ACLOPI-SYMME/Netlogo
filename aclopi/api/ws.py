"""WebSocket /ws/sessions/{id}: snapshot first, then the session's messages (docs/websocket.md).

One sender task per client drains that client's queue (hub.Subscriber); a receiver task only
watches for the disconnect (clients send nothing: control goes through HTTP). Disconnecting
never affects the run.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from aclopi.api.errors import ApiError, SessionGone, SessionNotFound
from aclopi.api.hub import HEARTBEAT_S, SEND_TIMEOUT_S, WS_CLOSE, Subscriber, closed_message, encode, heartbeat_message
from aclopi.logjson import session_id_var

logger = logging.getLogger(__name__)


async def _close(websocket: WebSocket, code: str, reason: str) -> None:
    try:
        await asyncio.wait_for(websocket.send_text(closed_message(code, reason)), SEND_TIMEOUT_S)
        await websocket.close(code=WS_CLOSE.get(code, 1000), reason=code)
    except Exception:  # noqa: BLE001 - the client may already be gone
        pass


async def stream_session(websocket: WebSocket, runtime: Any, session_id: str) -> None:
    session_id_var.set(session_id)
    await websocket.accept()
    registry = runtime.registry
    if registry is None or runtime.phase == "starting":
        await _close(websocket, "platform_starting", "plataforma iniciando")
        return
    try:
        record = registry.get(session_id, touch=False)
        if record.status != "active":
            raise registry._gone(record)
        await registry.refresh_cache(session_id)
    except SessionNotFound as exc:
        await _close(websocket, "session_not_found", exc.detail)
        return
    except SessionGone as exc:
        await _close(websocket, exc.code, exc.detail)
        return
    except ApiError as exc:
        await _close(websocket, exc.code, exc.detail)
        return
    if record.hub.closed is not None:
        await _close(websocket, *record.hub.closed)
        return

    # Subscribe and build the snapshot without awaiting in between: every later message is newer.
    sub = record.hub.subscribe()
    first = registry.snapshot_text(record)
    logger.info("WebSocket client connected (%d watching)", len(record.hub))
    sender = asyncio.create_task(_sender(websocket, sub, first, lambda: registry.snapshot_text(record)))
    receiver = asyncio.create_task(_receiver(websocket))
    try:
        done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        record.hub.unsubscribe(sub)
        for task in (sender, receiver):
            task.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)
        logger.info("WebSocket client disconnected (dropped %d, resyncs %d, %d still watching)",
                    sub.total_dropped, sub.resyncs, len(record.hub))


async def _send(websocket: WebSocket, text: str) -> None:
    await asyncio.wait_for(websocket.send_text(text), SEND_TIMEOUT_S)


async def _sender(websocket: WebSocket, sub: Subscriber, first: str, snapshot: Any) -> None:
    try:
        await _send(websocket, first)
        while True:
            if sub.close_with is not None:
                await _close(websocket, *sub.close_with)
                return
            if sub.resync_reason is not None:
                # Build the snapshot and clear the queue together, then send.
                reason, dropped = sub.resync_reason, sub.dropped
                sub.resync_reason, sub.dropped = None, 0
                sub.items.clear()
                sub.resyncs += 1
                text = snapshot()
                await _send(websocket, encode({"type": "resync", "reason": reason, "dropped": dropped}))
                await _send(websocket, text)
                continue
            if sub.items:
                await _send(websocket, sub.items.popleft())
                continue
            sub.wake.clear()
            try:
                await asyncio.wait_for(sub.wake.wait(), HEARTBEAT_S)
            except asyncio.TimeoutError:
                await _send(websocket, heartbeat_message())
    except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError, ConnectionError) as exc:
        logger.info("WebSocket client dropped: %s", type(exc).__name__)


async def _receiver(websocket: WebSocket) -> None:
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
    except (WebSocketDisconnect, RuntimeError):
        return
