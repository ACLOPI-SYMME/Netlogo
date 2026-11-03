"""What-if of a pending decision (L5.4). Documentation for Línea A: docs/whatif.md.

    POST /sessions/{id}/what-if {product, seq, options: [2 machines], max_ticks, budget_ms}

1. skipped "already-used" if this session already ran a what-if for (product, seq);
2. borrow a what-if worker without queueing: skipped "no-free-worker" if none is free;
3. session worker, between blocks (the run is not stopped): validate both options
   (platform-check-next-machine), measure the load of the two machines and export ONE snapshot;
   entry-beyond-cap: the estimated entry (own remaining operation + travel, or the machine's load)
   of BOTH options is beyond max_ticks. For now only recorded (would_skip_entry_beyond_cap); it
   skips the what-if only with ACLOPI_WHATIF_SKIP_BEYOND_CAP=1;
4. the options run one after the other on the borrowed worker, the one with the earlier
   estimated entry first; the first one's stop tick is the comparison window of the second, which
   is pruned there if its product has not entered yet (aclopi.sim.whatif);
5. the whole request is bounded by the request's budget_ms (default 10 s, 2-15 s; the agent sets it
   from its decision deadline): what is ready is returned with status "timeout".
"""

from __future__ import annotations

import logging
import statistics
import time
from pathlib import Path
from typing import Any

from aclopi.api.errors import ApiError, DecisionNotPending, InvalidOption, Rule4Required
from aclopi.workers.protocol import NoFreeWorker, WorkerCrashed, WorkerError, WorkerTimeout

logger = logging.getLogger(__name__)

NOT_PENDING = {"product-finished", "stale-seq", "not-in-machine", "seq-mismatch"}
OPTION_TIMEOUT_MARGIN_S = 5.0  # request timeout of whatif_option beyond the deadline (import + final reads)


def _stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    s = sorted(values)
    return {"mean": round(statistics.fmean(s), 1), "p95": round(s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))], 1),
            "max": round(s[-1], 1), "n": len(s)}


class WhatIfMetrics:
    """Per-session counters and timings of what-ifs (plan, section 3.4)."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {
            "requests": 0, "ok": 0, "timeout": 0, "error": 0, "invalid": 0,
            "would_skip_entry_beyond_cap": 0, "options_run": 0, "entered": 0, "cap_reached": 0,
            "stalled": 0, "pruned": 0, "options_timed_out": 0,
        }
        self.skipped: dict[str, int] = {"no-free-worker": 0, "already-used": 0, "entry-beyond-cap": 0}
        self.series: dict[str, list[float]] = {k: [] for k in (
            "duration_ms", "export_ms", "import_ms", "advance_ms", "ticks_to_entry", "ticks_simulated")}

    def as_dict(self) -> dict[str, Any]:
        return {**self.counts, "skipped": dict(self.skipped),
                **{k: _stats(v) for k, v in self.series.items()}}


def _skipped(reason: str, t0: float, **extra: Any) -> dict[str, Any]:
    return {"status": "skipped", "skipped_reason": reason, "options": [], "window_tick": None, "run_order": [],
            "timings_ms": {"export": None, "import": None, "advance": None, "total": round(1000 * (time.perf_counter() - t0), 1)},
            **extra}


async def run_whatif(registry: Any, settings: Any, session_id: str, product: int, seq: int,
                     options: list[str], max_ticks: int, budget_ms: int = 10000) -> dict[str, Any]:
    t0 = time.perf_counter()
    record = registry.get(session_id)
    registry._ensure_active(record)
    metrics: WhatIfMetrics = record.whatif_metrics
    metrics.counts["requests"] += 1
    if int(record.parameters.get("rule", 0)) != 4:
        metrics.counts["invalid"] += 1
        raise Rule4Required("what-if needs a session with rule 4 (AI agent)", session_id)
    key = (int(product), int(seq))
    if key in record.whatif_used:
        metrics.skipped["already-used"] += 1
        return _skipped("already-used", t0)
    try:
        borrow = registry.pool.borrow_whatif()
        whatif = borrow.__enter__()
    except NoFreeWorker:
        metrics.skipped["no-free-worker"] += 1
        return _skipped("no-free-worker", t0)
    path: Path | None = None
    try:
        record, snap = await registry.call(
            session_id, "whatif_snapshot", product=product, seq=seq, options=options,
            max_ticks=max_ticks, skip_beyond_cap=settings.whatif_skip_beyond_cap)
        if not snap["valid"]:
            metrics.counts["invalid"] += 1
            bad = {m: r for m, r in snap["reasons"].items() if r != "ok"}
            detail = f"invalid what-if options: {bad}"
            if "rule4-not-active" in bad.values():
                raise Rule4Required(detail, session_id)
            if any(r in NOT_PENDING for r in bad.values()):
                raise DecisionNotPending(detail, session_id)
            raise InvalidOption(detail, session_id)
        estimate = {"would_skip_entry_beyond_cap": bool(snap["beyond_cap"]), "loads": snap["loads"],
                      "estimated_entry_ticks": snap["estimated_entry_ticks"]}
        if snap["beyond_cap"]:
            metrics.counts["would_skip_entry_beyond_cap"] += 1
        if snap.get("path") is None:  # skipped by the entry-beyond-cap criterion (enforced)
            metrics.skipped["entry-beyond-cap"] += 1
            return _skipped("entry-beyond-cap", t0, snapshot_tick=snap["tick"], **estimate)
        path = Path(snap["path"])
        record.whatif_used.add(key)
        deadline = time.time() + budget_ms / 1000.0 - (time.perf_counter() - t0)
        order = sorted(options, key=lambda m: (snap["estimated_entry"][m], options.index(m)))
        info = {"session_id": session_id, "snapshot_tick": snap["tick"], "product": product, "seq": seq,
                "options": options, "max_ticks": max_ticks, "budget_ms": budget_ms}
        results: dict[str, dict[str, Any]] = {}
        window: int | None = None
        status = "ok"
        for machine in order:
            remaining = deadline - time.time()
            if remaining <= 0:
                results[machine] = {"machine": machine, "skipped": True, "timed_out": True, "stop_reason": "timeout"}
                status = "timeout"
                continue
            try:
                r = await registry.run(
                    whatif.request, "whatif_option", timeout=remaining + OPTION_TIMEOUT_MARGIN_S,
                    path=str(path), product=product, seq=seq, machine=machine, max_ticks=max_ticks,
                    window_tick=window, deadline=deadline, stall_ticks=settings.whatif_stall_ticks,
                    chunk_ticks=settings.whatif_chunk_ticks, diag_dir=str(settings.whatif_diag_dir), info=info)
            except (WorkerTimeout, WorkerCrashed, WorkerError) as exc:
                logger.error("What-if option %s failed: %s", machine, exc, extra={"session_id": session_id})
                r = {"machine": machine, "stop_reason": "error", "error": str(exc)[:500],
                     "timed_out": isinstance(exc, WorkerTimeout)}
                status = "timeout" if isinstance(exc, WorkerTimeout) else "error"
            r["skipped"] = False
            if r.get("error") is None and window is None:
                window = r["stop_tick"]
            if r.get("timed_out") and status == "ok":
                status = "timeout"
            results[machine] = r
    finally:
        borrow.__exit__(None, None, None)
        if path is not None:
            path.unlink(missing_ok=True)

    opts = [results[m] for m in options]
    export_ms = float(snap.get("export_ms") or 0.0)
    import_ms = sum(float(o.get("import_ms") or 0.0) for o in opts)
    advance_ms = sum(float(o.get("advance_ms") or 0.0) for o in opts)
    total_ms = round(1000 * (time.perf_counter() - t0), 1)
    for o in opts:
        o["duration_ms"] = round(float(o.get("import_ms") or 0.0) + float(o.get("advance_ms") or 0.0), 1)
    _record(metrics, status, opts, export_ms, import_ms, advance_ms, total_ms)
    return {
        "status": status,
        "skipped_reason": None,
        "snapshot_tick": snap["tick"],
        "snapshot_time": snap["time"],
        "operation": snap["operation"],
        "window_tick": window if len(opts) > 1 else None,
        "run_order": order,
        "timings_ms": {"export": export_ms, "import": round(import_ms, 1), "advance": round(advance_ms, 1),
                       "total": total_ms},
        "options": opts,
        **estimate,
    }


def _record(m: WhatIfMetrics, status: str, opts: list[dict[str, Any]], export_ms: float, import_ms: float,
            advance_ms: float, total_ms: float) -> None:
    m.counts[status] = m.counts.get(status, 0) + 1
    m.series["duration_ms"].append(total_ms)
    m.series["export_ms"].append(export_ms)
    m.series["import_ms"].append(import_ms)
    m.series["advance_ms"].append(advance_ms)
    for o in opts:
        if o.get("skipped") or o.get("stop_reason") == "error":
            continue
        m.counts["options_run"] += 1
        for flag, counter in (("entered", "entered"), ("cap_reached", "cap_reached"), ("stalled", "stalled"),
                              ("pruned", "pruned"), ("timed_out", "options_timed_out")):
            if o.get(flag):
                m.counts[counter] += 1
        m.series["ticks_simulated"].append(float(o.get("ticks_simulated") or 0))
        if o.get("entered"):
            m.series["ticks_to_entry"].append(float(o["entry_tick"] - (o["stop_tick"] - o["ticks_simulated"])))


__all__ = ["ApiError", "WhatIfMetrics", "run_whatif"]
