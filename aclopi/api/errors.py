"""API errors and their HTTP mapping.

Body of every error except 422: {"code": str, "detail": str, "session_id": str | null}.
422 keeps FastAPI's standard validation body ({"detail": [...]}).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aclopi.workers.protocol import WorkerError

logger = logging.getLogger(__name__)


class ApiError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, detail: str, session_id: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.session_id = session_id


class SessionNotFound(ApiError):
    status_code, code = 404, "session_not_found"


class RunNotFound(ApiError):
    status_code, code = 404, "run_not_found"


class ProductSetNotFound(ApiError):
    status_code, code = 404, "product_set_not_found"


class SessionGone(ApiError):
    """The session was lost (worker crash or hang) or closed for inactivity."""

    status_code = 410

    def __init__(self, detail: str, session_id: str | None, code: str) -> None:
        super().__init__(detail, session_id)
        self.code = code


class PlatformStarting(ApiError):
    status_code, code = 503, "platform_starting"


class NoWorkerAvailable(ApiError):
    status_code, code = 503, "no_free_worker"


class WorkerUnavailable(ApiError):
    status_code, code = 503, "worker_unavailable"


class GatewayTimeout(ApiError):
    status_code, code = 504, "worker_timeout"


class SimulationError(ApiError):
    status_code, code = 500, "simulation_error"


class InvalidRunState(ApiError):
    """The request is not allowed in the session's run state (e.g. step while running)."""

    status_code, code = 409, "invalid_run_state"


class FastRunLimit(ApiError):
    status_code, code = 503, "fast_run_limit"


class Rule4Required(ApiError):
    """What-if needs a session with rule 4 (the decision is forced with platform-set-next-machine)."""

    status_code, code = 409, "rule4_required"


class InvalidOption(ApiError):
    """A what-if option is not valid for the decision (unknown product or machine, machine not capable...)."""

    status_code, code = 422, "invalid_option"


class ScenariosUnavailable(ApiError):
    """POST /sessions with a scenario other than S0: scenarios are not available on the platform
    (docs/scenarios.md); the code stays in aclopi.sim.scenarios for Línea A's experiments."""

    status_code, code = 422, "scenarios_unavailable"


class Unauthorized(ApiError):
    """Missing or wrong Authorization: Bearer token (ACLOPI_AGENT_TOKEN)."""

    status_code, code = 401, "unauthorized"


class AgentUnavailable(ApiError):
    """A fast run with a deciding strategy needs the agent, and it is down."""

    status_code, code = 503, "agent_unavailable"


class DecisionNotPending(ApiError):
    """The product has no pending decision for that seq (finished, not in a machine, other seq)."""

    status_code, code = 409, "decision_not_pending"


ERROR_DESCRIPTIONS = {
    401: "Missing or wrong Authorization: Bearer token (unauthorized), when ACLOPI_AGENT_TOKEN is set",
    404: "Unknown session (session_not_found)",
    409: "Not allowed in the session's run state (invalid_run_state), e.g. step while running; what-if: "
         "rule4_required or decision_not_pending",
    410: "Session lost because its worker crashed or hung (session_lost), or closed for inactivity (session_expired)",
    500: "Error inside NetLogo or the worker (simulation_error)",
    503: "Platform starting (platform_starting), no free worker (no_free_worker), worker unavailable "
         "(worker_unavailable), too many fast runs (fast_run_limit) or agent down (agent_unavailable)",
    504: "The worker did not answer in time (worker_timeout); it is restarted and the session is lost",
}


def responses(*codes: int) -> dict[int | str, dict[str, object]]:
    """OpenAPI 'responses' for a route: the given error codes with the ErrorBody schema."""
    from aclopi.api.models import ErrorBody

    return {code: {"model": ErrorBody, "description": ERROR_DESCRIPTIONS[code]} for code in codes}


def _body(exc: ApiError) -> dict[str, str | None]:
    return {"code": exc.code, "detail": exc.detail, "session_id": exc.session_id}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        level = logging.ERROR if exc.status_code >= 500 and exc.status_code != 503 else logging.WARNING
        if exc.status_code == 409:
            level = logging.INFO
        logger.log(level, "%s %s -> %d %s: %s", request.method, request.url.path, exc.status_code, exc.code, exc.detail,
                   extra={"session_id": exc.session_id})
        return JSONResponse(_body(exc), status_code=exc.status_code)

    @app.exception_handler(WorkerError)
    async def _worker_error(request: Request, exc: WorkerError) -> JSONResponse:
        return await _api_error(request, SimulationError(str(exc)))
