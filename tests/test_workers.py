"""Worker processes and pool (aclopi.workers): results through the queues, errors, crashes,
cross-process cloning, what-if lending, parallelism and shutdown. Rule 3, Stochastic."""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator

import psutil
import pytest

from aclopi.sim import SimulationSession
from aclopi.workers import (
    MAX_STEP_TICKS, NoFreeWorker, SessionLost, WorkerCrashed, WorkerError, WorkerPool, WorkerTimeout,
)

RULE = 3
SEEDS = (501, 502, 503, 504, 505)


@pytest.fixture(scope="module")
def pool(tmp_path_factory: pytest.TempPathFactory) -> Iterator[WorkerPool]:
    with WorkerPool(n_session=5, n_whatif=2, debug=True, work_dir=tmp_path_factory.mktemp("work")) as p:
        yield p


@pytest.fixture(scope="module")
def small_pool(tmp_path_factory: pytest.TempPathFactory) -> Iterator[WorkerPool]:
    with WorkerPool(n_session=1, n_whatif=1, debug=True, work_dir=tmp_path_factory.mktemp("work_small")) as p:
        yield p


def run_to_end(handle: Any) -> dict[str, Any]:
    """10,000 ticks in blocks of MAX_STEP_TICKS (a single request must stay short)."""
    while not handle.request("step", n=MAX_STEP_TICKS)["finished"]:
        pass
    return handle.request("kpis")


def test_pool_roles_and_priority(pool: WorkerPool) -> None:
    rows = pool.status()
    assert [r["role"] for r in rows] == ["session"] * 5 + ["whatif"] * 2
    assert all(r["state"] == "free" and r["pid"] and r["rss_mib"] for r in rows)
    session_prio = {r["priority"] for r in rows if r["role"] == "session"}
    whatif_prio = {r["priority"] for r in rows if r["role"] == "whatif"}
    if sys.platform == "win32":
        assert whatif_prio == {psutil.BELOW_NORMAL_PRIORITY_CLASS} and session_prio == {psutil.NORMAL_PRIORITY_CLASS}
    else:
        assert min(whatif_prio) > max(session_prio)  # higher nice = lower priority


def test_b_errors_keep_worker_alive(pool: WorkerPool, tmp_path: Path) -> None:
    h = pool.acquire_session("errors")
    try:
        pid = h.request("ping")["pid"]
        with pytest.raises(WorkerError) as bad:
            h.request("command", code="this-is-not-netlogo")
        assert bad.value.error_type == "NetLogoException"
        assert h.request("ping")["pid"] == pid

        with pytest.raises(WorkerError, match="call setup or import_world first"):
            h.request("step", n=1)
        h.request("setup", seed=1, rule=RULE)
        with pytest.raises(WorkerError, match=f"between 1 and {MAX_STEP_TICKS}"):
            h.request("step", n=MAX_STEP_TICKS + 1)

        corrupt = tmp_path / "corrupt_world.csv"
        corrupt.write_text("this is not an exported NetLogo world\n", encoding="utf-8")
        with pytest.raises(WorkerError):
            h.request("import_world", path=str(corrupt), delete_after=False)
        ping = h.request("ping")
        assert ping["pid"] == pid
        # import-world cleared the world before failing: the worker is alive but needs a new setup.
        assert ping["configured"] is False
        with pytest.raises(WorkerError, match="call setup or import_world first"):
            h.request("step", n=1)
        h.request("setup", seed=1, rule=RULE)
        assert h.request("step", n=10)["advanced"] == 10  # usable again
    finally:
        pool.release_session("errors")


def test_debug_ops_refused_without_debug(small_pool: WorkerPool) -> None:
    # small_pool runs in debug mode; build the refusal check on the worker directly.
    from aclopi.workers.worker import WorkerConfig, WorkerState

    state = WorkerState.__new__(WorkerState)
    state.config = WorkerConfig(slot=0, role="session", generation=0, work_dir=".", debug=False)
    with pytest.raises(PermissionError):
        state.handler("command")
    with pytest.raises(ValueError):
        state.handler("not-an-op")


def test_d_clone_between_processes(pool: WorkerPool) -> None:
    h = pool.acquire_session("clone")
    try:
        h.request("setup", seed=42, rule=RULE)
        for _ in range(3):
            h.request("step", n=1000)
        with pool.whatif_from_session("clone") as w:
            assert w.request("ping")["ticks"] == 3000
            assert w.request("events") == []  # the clone starts with an empty event buffer
            assert w.request("state") == h.request("state")
            h.request("events")
            for handle in (h, w):
                handle.request("step", n=1000)
            assert w.request("kpis") == h.request("kpis")
            assert w.request("state") == h.request("state")
            for code in ("(word EventFrameInfo)", "(word DataFrameInfo)", "random 2147483647"):
                assert w.request("report", code=code) == h.request("report", code=code)
        assert not list((pool.work_dir / "worlds").glob("*.csv"))  # world files are removed
    finally:
        pool.release_session("clone")


def test_e_whatif_is_not_queued(pool: WorkerPool) -> None:
    with pool.borrow_whatif(), pool.borrow_whatif():
        t0 = time.perf_counter()
        with pytest.raises(NoFreeWorker):
            with pool.borrow_whatif():
                pass
        assert time.perf_counter() - t0 < 0.05
    with pool.borrow_whatif():  # released again
        pass


def test_no_sixth_session(pool: WorkerPool) -> None:
    ids = [f"full{i}" for i in range(5)]
    try:
        for sid in ids:
            pool.acquire_session(sid)
        with pytest.raises(NoFreeWorker):
            pool.acquire_session("sixth")
    finally:
        for sid in ids:
            pool.release_session(sid)


@pytest.mark.slow
def test_a_kpis_through_queues_match_direct(pool: WorkerPool, tmp_path: Path) -> None:
    handles = {seed: pool.acquire_session(f"a{seed}") for seed in SEEDS}
    try:
        for seed, h in handles.items():
            h.request("setup", seed=seed, rule=RULE)
        with ThreadPoolExecutor(max_workers=len(SEEDS)) as ex:
            via_queues = dict(zip(SEEDS, ex.map(run_to_end, handles.values())))
    finally:
        for seed in SEEDS:
            pool.release_session(f"a{seed}")
    with SimulationSession("direct", results_root=tmp_path) as s:
        for seed in SEEDS:
            s.setup(seed=seed, rule=RULE)
            s.run_to_end()
            assert via_queues[seed] == s.kpis().as_dict(), f"seed {seed}"


@pytest.mark.slow
def test_f_parallel_sessions(pool: WorkerPool) -> None:
    handles = [pool.acquire_session(f"f{seed}") for seed in SEEDS]
    try:
        def prepare() -> None:
            for seed, h in zip(SEEDS, handles):
                h.request("setup", seed=seed, rule=RULE)

        prepare()
        t0 = time.perf_counter()
        for h in handles:
            run_to_end(h)
        sequential = time.perf_counter() - t0

        prepare()
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(handles)) as ex:
            list(ex.map(run_to_end, handles))
        parallel = time.perf_counter() - t0
    finally:
        for seed in SEEDS:
            pool.release_session(f"f{seed}")
    speedup = sequential / parallel
    print(f"\n5 x 10,000 ticks: sequential {sequential:.1f} s, parallel {parallel:.1f} s, speed-up {speedup:.2f}x")
    assert speedup > 1.3


def test_c_crash_detected_and_restarted(small_pool: WorkerPool) -> None:
    h = small_pool.acquire_session("crash")
    h.request("setup", seed=7, rule=RULE)
    old_pid = h.pid
    result: dict[str, Any] = {}

    def pending() -> None:
        t0 = time.monotonic()
        try:
            h.request("command", code="wait 30")  # timeout 10 s
            result["outcome"] = "no error"
        except Exception as exc:  # noqa: BLE001
            result["outcome"] = exc
        result["seconds"] = time.monotonic() - t0

    t = threading.Thread(target=pending)
    t.start()
    time.sleep(1.0)
    psutil.Process(old_pid).kill()
    t.join(15)
    assert isinstance(result["outcome"], WorkerCrashed)
    assert result["seconds"] < 5  # well within the 10 s timeout
    with pytest.raises(SessionLost):
        small_pool.session("crash")
    assert "crash" in small_pool.lost_sessions()
    assert small_pool.wait_until_free(0, timeout_s=180)
    row = small_pool.status()[0]
    assert row["pid"] != old_pid and row["restarts"] == 1
    new = small_pool.acquire_session("after-crash")
    assert new.request("ping")["generation"] == 1
    small_pool.release_session("after-crash")
    small_pool.release_session("crash")


def test_c_timeout_treated_as_hung(small_pool: WorkerPool) -> None:
    h = small_pool.acquire_session("hung")
    h.request("setup", seed=7, rule=RULE)
    restarts = small_pool.status()[0]["restarts"]
    t0 = time.monotonic()
    with pytest.raises(WorkerTimeout):
        h.request("command", timeout=2.0, code="wait 20")
    assert time.monotonic() - t0 < 4
    assert small_pool.wait_until_free(0, timeout_s=180)
    assert "unresponsive" in small_pool.lost_sessions()["hung"]
    assert small_pool.status()[0]["restarts"] == restarts + 1
    small_pool.release_session("hung")


def test_g_shutdown_leaves_no_processes(small_pool: WorkerPool) -> None:
    pids = set(small_pool.spawned_pids)
    assert pids
    small_pool.shutdown()
    time.sleep(0.5)
    assert not [p for p in pids if psutil.pid_exists(p) and psutil.Process(p).status() != psutil.STATUS_ZOMBIE]
    children = {c.pid for c in psutil.Process().children(recursive=True)}
    assert not children & pids
    assert all(r["state"] == "stopped" for r in small_pool.status())
