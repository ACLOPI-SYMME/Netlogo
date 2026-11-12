"""Test helper: the API in a background thread (real uvicorn, real worker pool, real HTTP/WebSocket)."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from aclopi.api import Settings, create_app
from aclopi.api.app import default_pool_factory
from aclopi.workers.pool import WorkerPool


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ApiServer:
    """The API in a background thread, plus what was observed while the pool was starting."""

    def __init__(self, settings: Settings, warm: bool) -> None:
        def factory(s: Settings) -> WorkerPool:
            pool = default_pool_factory(s)
            pool.warm = warm
            return pool

        self.fatal: list[BaseException] = []
        self.app = create_app(settings, pool_factory=factory, on_fatal=self.fatal.append)
        self.url = f"http://127.0.0.1:{settings.port}"
        self.ws_url = f"ws://127.0.0.1:{settings.port}"
        config = uvicorn.Config(self.app, host="127.0.0.1", port=settings.port, log_config=None,
                                access_log=False, lifespan="on", ws="websockets-sansio",
                                ws_ping_interval=10.0, ws_ping_timeout=10.0,
                                # without it, an open connection (a browser's WebSocket, a keep-alive) makes the
                                # shutdown wait for ever, and the lifespan never shuts the worker pool down
                                timeout_graceful_shutdown=10)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, name="api-server", daemon=True)
        self.startup: dict[str, Any] = {}

    def start(self, timeout_s: float = 600.0) -> None:
        t0 = time.monotonic()
        self.thread.start()
        with httpx.Client(base_url=self.url, timeout=10) as client:
            while True:  # first answer of /health/live
                try:
                    live = client.get("/health/live")
                    break
                except httpx.TransportError:
                    assert time.monotonic() - t0 < 30, "API did not answer"
                    time.sleep(0.05)
            self.startup["first_answer_s"] = time.monotonic() - t0
            self.startup["live"] = live.status_code
            health = client.get("/health").json()
            self.startup["health_status"] = health["status"]
            self.startup["ready_code"] = client.get("/health/ready").status_code
            create = client.post("/sessions", json={"seed": 1, "rule": 3})
            self.startup["create_code"] = create.status_code
            self.startup["create_body"] = create.json()
            statuses = {health["status"]}
            while True:
                health = client.get("/health").json()
                statuses.add(health["status"])
                if health["status"] == "ready":
                    break
                assert not self.fatal, f"pool failed to start: {self.fatal}"
                assert time.monotonic() - t0 < timeout_s, "platform not ready"
                time.sleep(0.25)
            self.startup["ready_s"] = time.monotonic() - t0
            self.startup["statuses"] = statuses
            self.startup["ready_health"] = health
            self.startup["ready_code_after"] = client.get("/health/ready").status_code
            self.startup["live_after"] = client.get("/health/live").status_code

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(120)
        pool = self.runtime.pool
        if self.thread.is_alive() and pool is not None:
            # The server did not stop: shut the pool down here. Its workers are not daemon processes, so a
            # pool left running would keep this process from exiting (it joins them at exit).
            pool.shutdown()

    @property
    def runtime(self) -> Any:
        return self.app.state.runtime


def start_server(tmp: Path, n_session: int, n_whatif: int, warm: bool, idle_s: float, **settings: Any) -> ApiServer:
    s = Settings(host="127.0.0.1", port=free_port(), n_session_workers=n_session, n_whatif_workers=n_whatif,
                 session_idle_timeout_s=idle_s, work_dir=tmp, **settings)
    server = ApiServer(s, warm=warm)
    server.start()
    return server


def wait_session_workers_free(url: str, timeout_s: float = 180.0) -> None:
    """Between tests: every session worker free (e.g. after a restart) and no active session."""
    deadline = time.monotonic() + timeout_s
    with httpx.Client(base_url=url, timeout=30) as c:
        for s in c.get("/sessions").json():
            if s["status"] == "active":
                c.delete(f"/sessions/{s['session_id']}")
        while time.monotonic() < deadline:
            workers = c.get("/health").json()["workers"]
            if all(w["state"] == "free" and w["ready"] for w in workers if w["role"] == "session"):
                return
            time.sleep(0.25)
    raise AssertionError("session workers did not become free")
