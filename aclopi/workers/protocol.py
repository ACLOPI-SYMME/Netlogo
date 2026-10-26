"""Message protocol between the main process and the simulation workers.

Every simulation lives in its own worker process (NetLogo only works from the main thread of a
Python process, see docs/known-issues.md). The main process talks to a worker through two
multiprocessing queues:

- requests (main -> worker):  {"id": int, "op": str, "args": dict}
- outbox   (worker -> main):  responses and unsolicited messages, distinguished by "type":
    {"type": "response", "id": int, "ok": True,  "result": ..., "elapsed_ms": float}
    {"type": "response", "id": int, "ok": False, "error": {"type": str, "message": str}, "elapsed_ms": float}
    {"type": "push", "event": str, "data": ...}      # e.g. "ready", later live state/events (L5.3)

Only plain data travels: dict, list, str, int, float, bool, None.

RULE FOR EVERY OPERATION (L5.1, L5.2, L5.3 must respect it)
-------------------------------------------------------------
A request must never take more than a few seconds. A worker is single-threaded: while it runs a
request it cannot answer anything else, so the main process cannot tell "busy" from "hung".
Therefore each operation has its own timeout (OP_TIMEOUTS_S, step_timeout_s) and a request that
exceeds it is treated as a hung worker: the request fails with WorkerTimeout, the worker is killed
and restarted, and its session is marked as lost.

- step accepts at most MAX_STEP_TICKS ticks per request; larger values are rejected.
- Long runs (fast mode, L5.3) are executed by the worker itself, in blocks inside its own loop,
  reporting progress through the outbox as "push" messages, never as one long request.

Diagnostic operations ("command", "report") run arbitrary NetLogo code. They exist only for tests
and diagnostics, are refused unless the pool is created with debug=True, and must NEVER be exposed
by the API.
"""

from __future__ import annotations

from typing import Any

# Operations available to every client.
OPS = (
    "ping", "setup", "step", "state", "events", "layout", "kpis", "reset",
    "export_world", "import_world", "shutdown",
)
# Diagnostic operations: only with debug=True; never exposed by the API.
DEBUG_OPS = ("command", "report")

MAX_STEP_TICKS = 2000

# Expected duration is well below these limits; exceeding one means the worker is hung.
OP_TIMEOUTS_S: dict[str, float] = {
    "ping": 5.0,
    "setup": 30.0,
    "state": 10.0,
    "events": 10.0,
    "layout": 10.0,
    "kpis": 10.0,
    "reset": 30.0,
    "export_world": 15.0,
    "import_world": 30.0,
    "shutdown": 15.0,
    "command": 10.0,
    "report": 10.0,
}
STEP_BASE_TIMEOUT_S = 5.0
# ~0.3-0.5 ms/tick measured in L4b; x10 margin for 7 workers sharing 4 vCPUs.
STEP_TIMEOUT_PER_TICK_S = 0.005


def step_timeout_s(n: int) -> float:
    return STEP_BASE_TIMEOUT_S + STEP_TIMEOUT_PER_TICK_S * max(int(n), 0)


def default_timeout_s(op: str, args: dict[str, Any]) -> float:
    if op == "step":
        return step_timeout_s(args.get("n", 0))
    return OP_TIMEOUTS_S.get(op, 10.0)


def request_message(request_id: int, op: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"id": request_id, "op": op, "args": args}


def ok_response(request_id: int, result: Any, elapsed_ms: float) -> dict[str, Any]:
    return {"type": "response", "id": request_id, "ok": True, "result": result, "elapsed_ms": round(elapsed_ms, 3)}


def error_response(request_id: int, exc: BaseException, elapsed_ms: float) -> dict[str, Any]:
    return {
        "type": "response",
        "id": request_id,
        "ok": False,
        "error": {"type": type(exc).__name__, "message": str(exc)[:4000]},
        "elapsed_ms": round(elapsed_ms, 3),
    }


def push_message(event: str, data: Any) -> dict[str, Any]:
    return {"type": "push", "event": event, "data": data}


# ----- exceptions raised on the main-process side -----

class WorkerError(Exception):
    """An operation failed inside the worker; the worker is still alive."""

    def __init__(self, op: str, error_type: str, message: str) -> None:
        super().__init__(f"{op} failed in worker: {error_type}: {message}")
        self.op = op
        self.error_type = error_type
        self.message = message


class WorkerTimeout(Exception):
    """No response within the timeout; the worker is treated as hung and restarted."""


class WorkerCrashed(Exception):
    """The worker process died (or was killed) before answering."""


class NoFreeWorker(Exception):
    """No worker of the requested role is free (what-if requests are not queued)."""


class SessionLost(Exception):
    """The worker that held this session died or was restarted; its state is gone."""
