"""Entry point: `python -m aclopi.api`.

Always one process with one uvicorn worker and no reload: each API process starts its own pool of
NetLogo workers (7 JVMs), so several uvicorn workers would multiply JVMs and memory. Settings come
from environment variables (aclopi.api.settings).

Exit codes: 0 normal stop; 3 the API could not start (pool startup failed, another instance holds
the lock). Docker's restart policy (on-failure / unless-stopped) retries in the cloud.
"""

from __future__ import annotations

import logging
import signal
import sys

import uvicorn

from aclopi import logjson
from aclopi.api.app import create_app
from aclopi.api.settings import Settings

EXIT_STARTUP_FAILURE = 3

logger = logging.getLogger("aclopi.api")


def main() -> int:
    settings = Settings.from_env()
    logjson.configure(settings.log_level)
    server: uvicorn.Server | None = None
    failed: list[BaseException] = []

    def on_fatal(exc: BaseException) -> None:
        failed.append(exc)
        if server is not None:
            server.should_exit = True

    app = create_app(settings, on_fatal=on_fatal)
    config = uvicorn.Config(
        app, host=settings.host, port=settings.port, workers=1, reload=False,
        log_config=None, access_log=False, lifespan="on",
    )
    server = uvicorn.Server(config)
    # uvicorn handles SIGINT/SIGTERM with a graceful shutdown and then re-raises the signal with
    # the previous handler; a no-op previous handler makes a normal stop end with exit code 0.
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: None)
    server.run()
    if failed or not server.started:
        logger.error("API stopped because it could not start", extra={"phase": "failed"})
        return EXIT_STARTUP_FAILURE
    return 0


if __name__ == "__main__":
    sys.exit(main())
