"""OriginVerifyMiddleware (aclopi/api/origin.py): CloudFront requests need the secret header; others pass."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from aclopi.api.origin import OriginVerifyMiddleware

SECRET = "s3cret-value"
CF = {"X-Amz-Cf-Id": "abc123"}


def make_client(secret: str | None) -> TestClient:
    app = FastAPI()

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.websocket("/ws/sessions/{sid}")
    async def ws(websocket: WebSocket, sid: str) -> None:
        await websocket.accept()
        await websocket.send_json({"sid": sid})
        await websocket.close()

    app.add_middleware(OriginVerifyMiddleware, secret=secret)
    return TestClient(app)


def test_cloudfront_request_with_right_header_passes() -> None:
    r = make_client(SECRET).get("/health/ready", headers={**CF, "X-Origin-Verify": SECRET})
    assert r.status_code == 200


@pytest.mark.parametrize("headers", [CF, {**CF, "X-Origin-Verify": "wrong"}])
def test_cloudfront_request_without_right_header_is_rejected(headers: dict[str, str]) -> None:
    r = make_client(SECRET).get("/health/ready", headers=headers)
    assert r.status_code == 403


def test_internal_request_without_cloudfront_passes() -> None:
    # The agent on the Docker network and health checks on localhost do not go through CloudFront.
    assert make_client(SECRET).get("/health/ready").status_code == 200


def test_check_off_without_secret() -> None:
    assert make_client(None).get("/health/ready", headers=CF).status_code == 200


def test_websocket_through_cloudfront() -> None:
    client = make_client(SECRET)
    with client.websocket_connect("/ws/sessions/s1", headers={**CF, "X-Origin-Verify": SECRET}) as ws:
        assert ws.receive_json() == {"sid": "s1"}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/sessions/s1", headers=CF) as ws:
            ws.receive_json()
