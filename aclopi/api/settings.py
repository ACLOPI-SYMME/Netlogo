"""API settings, read from environment variables (see README, section API)."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from aclopi.workers.pool import DEFAULT_JVM_ARGS, default_work_dir


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name, "").strip()
    return int(value) if value else default


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name, "").strip()
    return float(value) if value else default


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8000
    n_session_workers: int = 5
    n_whatif_workers: int = 2
    session_idle_timeout_s: float = 1800.0
    startup_timeout_s: float = 300.0
    timeout_scale: float = 1.0
    work_dir: Path = field(default_factory=default_work_dir)
    jvm_args: tuple[str, ...] = DEFAULT_JVM_ARGS
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        jvm_args = tuple(shlex.split(env.get("ACLOPI_JVM_ARGS", ""))) or DEFAULT_JVM_ARGS
        work_dir = env.get("ACLOPI_WORK_DIR", "").strip()
        return cls(
            host=env.get("ACLOPI_API_HOST", "").strip() or "0.0.0.0",
            port=_int(env, "ACLOPI_API_PORT", 8000),
            n_session_workers=_int(env, "ACLOPI_N_SESSION_WORKERS", 5),
            n_whatif_workers=_int(env, "ACLOPI_N_WHATIF_WORKERS", 2),
            session_idle_timeout_s=_float(env, "ACLOPI_SESSION_IDLE_TIMEOUT_S", 1800.0),
            startup_timeout_s=_float(env, "ACLOPI_STARTUP_TIMEOUT_S", 300.0),
            timeout_scale=_float(env, "ACLOPI_TIMEOUT_SCALE", 1.0),
            work_dir=Path(work_dir) if work_dir else default_work_dir(),
            jvm_args=jvm_args,
            log_level=env.get("ACLOPI_LOG_LEVEL", "").strip().upper() or "INFO",
        )
