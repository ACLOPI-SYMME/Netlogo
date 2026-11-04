"""`python -m aclopi.agent`: the agent service on ACLOPI_AGENT_HOST:ACLOPI_AGENT_PORT (0.0.0.0:8100)."""

from __future__ import annotations

import os
import sys

import uvicorn

from aclopi import logjson
from aclopi.agent.service import create_app


def main() -> int:
    logjson.configure(os.environ.get("ACLOPI_LOG_LEVEL", "INFO"), static={"service": "agent"})
    uvicorn.run(create_app(), host=os.environ.get("ACLOPI_AGENT_HOST", "0.0.0.0"),
                port=int(os.environ.get("ACLOPI_AGENT_PORT", "8100")), log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
