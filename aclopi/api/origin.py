"""CloudFront origin check (cloud deployment, infra/README.md).

In AWS the only way in is CloudFront: the instance's security group accepts port 80 only from CloudFront's
address list. That list is shared by every CloudFront distribution, so our distribution adds a secret header
(X-Origin-Verify) and this middleware rejects CloudFront requests that do not carry it.

Rule: a request that comes through CloudFront (it carries X-Amz-Cf-Id, which CloudFront always adds) must carry
the right X-Origin-Verify. Requests without X-Amz-Cf-Id are not touched: they can only come from inside the
instance (the agent on the Docker network, health checks on localhost), because the security group blocks the
rest. Without ACLOPI_ORIGIN_VERIFY (local runs) the middleware does nothing.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

logger = logging.getLogger(__name__)

CF_ID_HEADER = b"x-amz-cf-id"
VERIFY_HEADER = b"x-origin-verify"


class OriginVerifyMiddleware:
    """Pure ASGI middleware: covers HTTP and WebSocket requests."""

    def __init__(self, app: Any, secret: str | None) -> None:
        self.app = app
        self.secret = secret.encode() if secret else None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if self.secret is None or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        if CF_ID_HEADER in headers and not hmac.compare_digest(headers.get(VERIFY_HEADER, b""), self.secret):
            logger.warning("Rejected a CloudFront request without the right X-Origin-Verify: %s", scope.get("path"))
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"detail":"forbidden"}'})
            return
        await self.app(scope, receive, send)
