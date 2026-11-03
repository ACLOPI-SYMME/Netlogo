"""`python -m aclopi.agent_mock`: the mock agent on ACLOPI_MOCK_HOST:ACLOPI_MOCK_PORT (0.0.0.0:8100)."""

from __future__ import annotations

import os
import sys

import uvicorn

from aclopi import logjson
from aclopi.agent_mock.app import create_mock_app


def main() -> int:
    logjson.configure(os.environ.get("ACLOPI_LOG_LEVEL", "INFO"), static={"service": "agent-mock"})
    uvicorn.run(create_mock_app(), host=os.environ.get("ACLOPI_MOCK_HOST", "0.0.0.0"),
                port=int(os.environ.get("ACLOPI_MOCK_PORT", "8100")), log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
