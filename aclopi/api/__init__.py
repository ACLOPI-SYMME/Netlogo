"""REST API (FastAPI) over the simulation WorkerPool. Run with `python -m aclopi.api`."""

from aclopi.api.app import API_VERSION, create_app
from aclopi.api.settings import Settings

__all__ = ["API_VERSION", "Settings", "create_app"]
