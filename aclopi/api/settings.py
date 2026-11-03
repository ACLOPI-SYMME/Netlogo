"""API settings, read from environment variables (see README, section API)."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from aclopi.workers.pool import DEFAULT_JVM_ARGS, REPO_ROOT, default_work_dir


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
    # Continuous runs and WebSocket (L5.3)
    max_fast_runs: int = 1
    live_update_ms: float = 100.0
    fast_block_ticks: int = 1000
    fast_yield: float = 0.0
    ws_queue: int = 32
    # What-if (L5.4)
    whatif_stall_ticks: int = 300
    whatif_chunk_ticks: int = 150
    whatif_skip_beyond_cap: bool = False
    # Agent (L5.5): service URL, shared token (never logged), timeouts
    agent_url: str | None = None
    agent_token: str | None = None
    agent_decide_timeout_s: float = 2.0
    agent_health_interval_s: float = 30.0
    fast_decision_timeout_s: float = 90.0
    whatif_diag_dir: Path = field(default_factory=lambda: REPO_ROOT / "results" / "whatif_diagnostics")

    def run_options(self) -> dict[str, float | int]:
        return {"live_update_s": self.live_update_ms / 1000.0, "fast_block_ticks": self.fast_block_ticks,
                "fast_yield": self.fast_yield}

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
            max_fast_runs=_int(env, "ACLOPI_MAX_FAST_RUNS", 1),
            live_update_ms=_float(env, "ACLOPI_LIVE_UPDATE_MS", 100.0),
            fast_block_ticks=_int(env, "ACLOPI_FAST_BLOCK_TICKS", 1000),
            fast_yield=_float(env, "ACLOPI_FAST_YIELD", 0.0),
            ws_queue=_int(env, "ACLOPI_WS_QUEUE", 32),
            whatif_stall_ticks=_int(env, "ACLOPI_WHATIF_STALL_TICKS", 300),
            whatif_chunk_ticks=_int(env, "ACLOPI_WHATIF_CHUNK_TICKS", 150),
            whatif_skip_beyond_cap=env.get("ACLOPI_WHATIF_SKIP_BEYOND_CAP", "").strip() in ("1", "true", "yes"),
            agent_url=env.get("ACLOPI_AGENT_URL", "").strip().rstrip("/") or None,
            agent_token=env.get("ACLOPI_AGENT_TOKEN", "").strip() or None,
            agent_decide_timeout_s=_float(env, "ACLOPI_AGENT_DECIDE_TIMEOUT_S", 2.0),
            agent_health_interval_s=_float(env, "ACLOPI_AGENT_HEALTH_INTERVAL_S", 30.0),
            fast_decision_timeout_s=_float(env, "ACLOPI_FAST_DECISION_TIMEOUT_S", 90.0),
            whatif_diag_dir=Path(env["ACLOPI_WHATIF_DIAG_DIR"]) if env.get("ACLOPI_WHATIF_DIAG_DIR", "").strip()
            else REPO_ROOT / "results" / "whatif_diagnostics",
        )
