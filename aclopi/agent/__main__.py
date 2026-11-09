"""`python -m aclopi.agent`: the agent service on ACLOPI_AGENT_HOST:ACLOPI_AGENT_PORT (0.0.0.0:8100).

Before starting it loads ACLOPI_AGENT_ENV_FILE (default: .env.agent at the repo root, not in git) if it
exists; variables already set in the environment win.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from aclopi import logjson
from aclopi.agent.service import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    load_dotenv(os.environ.get("ACLOPI_AGENT_ENV_FILE") or REPO_ROOT / ".env.agent", override=False)
    logjson.configure(os.environ.get("ACLOPI_LOG_LEVEL", "INFO"), static={"service": "agent"})
    uvicorn.run(create_app(), host=os.environ.get("ACLOPI_AGENT_HOST", "0.0.0.0"),
                port=int(os.environ.get("ACLOPI_AGENT_PORT", "8100")), log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
