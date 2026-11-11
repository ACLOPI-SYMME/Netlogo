"""Makespan of a product list in a given entry order, for the "Optimize order" button (docs/sequencing.md).

    heuristic_order(products) -> [indices]   the heuristic order (largest_first), pure
    simulate_list(session, products, strategy, mode, seed, max_ticks, on_progress, details=False)
        -> {"makespan_ticks", "makespan_time", "all_done", "cancelled", "ticks", "wall_s"[, "details"]}

strategy: rule1 | rule2 | rule3 (the model's own rules) or b1 | b1b (rule 4 decided here, in the
worker: compute_candidates on the session's state and aclopi.agent.strategies, no HTTP). Reading the
state and answering use no random numbers, so b1 / b1b give the same run as through the platform.
The session is set up again (its previous run is lost) with the list, the seed and the mode.
It advances in pieces of at most CHUNK_TICKS ticks (fewer when the model is slow, so that a piece takes
about CHUNK_S of wall time), and stops when the list is done, at max_ticks or when on_progress returns
False (cancelled; all_done False). on_progress(ticks, done, total) is called at least every
CHUNK_TICKS ticks and at the end.

details=True adds "details" (None if the list is not done), from the products' records at the end
(ProductCreationTime, ProductRealStart / ProductRealCompletion / Machine.Used, read in one platform-local
reporter: no random numbers) and the entry rule of the model (aclopi.agent.sequencing_context):
    products        per index of the list: type, entry_tick (created), start_tick (O8 starts on M1), end_tick
    last            index of the product that finished last
    occupancy       % of the makespan each machine was processing
    m1_idle         intervals [from, to] (ticks) in which M1 was not processing, and their total
    entry_windows   entry checks of Go until the last product was created: created, or missed because
                    the entry zone was occupied (zone_busy) or the plant had wip_max products (wip_full)
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aclopi.agent.sequencing import largest_first
from aclopi.agent.sequencing_context import entry_checks, parse_model_rules
from aclopi.agent.strategies import DecisionContext, decide
from aclopi.sim.candidates import candidates_for_session, read_model_static
from aclopi.sim.decisions import clear_decision_log, clear_decisions, pending_decisions, run_until_decision, set_next_machine
from aclopi.sim.kpis import list_kpis
from aclopi.sim.session import SimulationSession

logger = logging.getLogger(__name__)

STRATEGIES = {"rule1": 1, "rule2": 2, "rule3": 3, "b1": 4, "b1b": 4}
DEFAULT_PRIORITY = 80  # products without a priority (it only labels the product: no effect on the run)
CHUNK_TICKS = 1000
CHUNK_S = 1.0
MIN_CHUNK_TICKS = 50
LIST_DONE = ('platform-local [ -> product-list? and products-created >= length product-list '
             'and not any? products with [Product.State != "death"] ]')

DETAILS_REPORTER = ("platform-local [ -> json-any map [p -> [(list who ProductType ProductCreationTime ProductRealStart "
                    "ProductRealCompletion Machine.Used)] of p] sort products ]")

Progress = Callable[[int, int, int], Any]


def compute_details(rows: list[list[Any]], rules: dict[str, Any], makespan_time: float,
                    tick_time: float = 0.31) -> dict[str, Any]:
    """details of a finished list (pure). rows: [who, type, created, starts, completions, machines] per
    product in creation order (= list order); rules: entry and time_step of the model (parse_model_rules)."""
    def tk(t: float) -> int:
        return int(round(t / tick_time))

    products = [{"index": i, "type": str(r[1]), "entry_tick": tk(float(r[2])), "start_tick": tk(float(r[3][0])),
                 "end_tick": tk(float(r[4][-1]))} for i, r in enumerate(rows)]
    last = max(range(len(rows)), key=lambda i: (float(rows[i][4][-1]), -i))
    busy: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        for s, c, m in zip(r[3], r[4], r[5]):
            busy.setdefault(str(m), []).append((float(s), float(c)))
    occupancy = {m: round(100 * sum(c - s for s, c in iv) / makespan_time, 1) for m, iv in sorted(busy.items())}
    idle, t = [], 0.0
    for s, c in sorted(busy.get("M1", [])):
        if s > t:
            idle.append([tk(t), tk(s)])
        t = max(t, c)
    if t < makespan_time:
        idle.append([tk(t), tk(makespan_time)])
    idle = [iv for iv in idle if iv[1] > iv[0]]
    created = [float(r[2]) for r in rows]
    ends = [float(r[4][-1]) for r in rows]
    created_at = {round(c, 2) for c in created}
    count = len(rows)
    while (checks := entry_checks(rules, count))[-1] < max(created):
        count *= 2
    windows = {"checks": 0, "created": 0, "zone_busy": 0, "wip_full": 0}
    for c in checks:
        if c > max(created):
            break
        windows["checks"] += 1
        if round(c, 2) in created_at:
            windows["created"] += 1
        elif sum(1 for a, e in zip(created, ends) if a < c and e >= c) >= int(rules["entry"]["wip_max"]):
            windows["wip_full"] += 1
        else:
            windows["zone_busy"] += 1
    return {"products": products, "last": last, "occupancy": occupancy,
            "m1_idle": {"intervals": idle, "total_ticks": sum(b - a for a, b in idle)}, "entry_windows": windows}


def heuristic_order(products: Sequence[Any]) -> list[int]:
    """The heuristic entry order of a list (0-based indices): largest_first of aclopi.agent.sequencing,
    the "heuristic" of POST /sequence/propose. Pure: no NetLogo, no LLM."""
    return largest_first(products)


@lru_cache(maxsize=4)
def _rules(model_path: Path) -> dict[str, Any]:
    return parse_model_rules(Path(model_path).read_text(encoding="utf-8"))


def _item(p: Any) -> tuple[str, int]:
    if isinstance(p, Mapping):
        priority = p.get("priority")
        return str(p["type"]), DEFAULT_PRIORITY if priority is None else int(priority)
    if isinstance(p, str):
        return p, DEFAULT_PRIORITY
    return str(p[0]), DEFAULT_PRIORITY if len(p) < 2 or p[1] is None else int(p[1])


def _answer_requests(session: SimulationSession, strategy: str, static: Any) -> None:
    for req in pending_decisions(session):
        cands = candidates_for_session(session, req.who, req.seq, static).as_dict()
        if cands["valid"] and cands["candidates"]:  # otherwise the model applies rule 3
            decision = decide(DecisionContext(None, req.who, req.seq, strategy, "fast", cands))
            set_next_machine(session, req.who, decision.machine, req.seq)
    clear_decisions(session)


def simulate_list(session: SimulationSession, products: Sequence[Any], strategy: str = "b1b",
                  mode: str = "Deterministic", seed: int = 42, max_ticks: int = 200_000,
                  on_progress: Progress | None = None, details: bool = False) -> dict[str, Any]:
    """products: [{"type", "priority"?}] or [(type, priority)] in entry order."""
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}, got {strategy!r}")
    items = [_item(p) for p in products]
    rule = STRATEGIES[strategy]
    start = time.perf_counter()
    session.setup(seed, rule, modeling_type=mode, horizon_ticks=int(max_ticks), product_list=items)
    static = read_model_static(session) if rule == 4 else None
    total, chunk, ticks, reported, cancelled = len(items), CHUNK_TICKS, 0, 0, False
    while True:
        t0 = time.perf_counter()
        n = max(1, min(chunk, reported + CHUNK_TICKS - ticks))  # a report at most every CHUNK_TICKS
        if rule == 4:
            r = run_until_decision(session, n)
            _answer_requests(session, strategy, static)
            clear_decision_log(session)
            session._command("platform-clear-events")  # nobody reads them: keep the buffers empty
            ticks, advanced, finished = r.ticks, r.advanced, r.finished
            all_done = bool(session._report(LIST_DONE))
        else:
            r2, all_done = session.step_product_list(n)
            session._command("platform-clear-events")
            ticks, advanced, finished = r2.ticks, r2.advanced, r2.finished
        elapsed = time.perf_counter() - t0
        if advanced > 0 and elapsed > 0:  # next piece: about CHUNK_S of wall time, at most CHUNK_TICKS
            chunk = max(MIN_CHUNK_TICKS, min(CHUNK_TICKS, int(advanced / elapsed * CHUNK_S)))
        end = finished or all_done
        if end or ticks - reported >= CHUNK_TICKS // 2:
            reported = ticks
            if on_progress is not None and on_progress(ticks, session.finished_products(), total) is False and not end:
                cancelled = True
                break
        if end:
            break
    with session._lock:
        kp = list_kpis(session._link)
        rows = json.loads(str(session._report(DETAILS_REPORTER))) if details else None
    out: dict[str, Any] = {"makespan_ticks": kp.get("makespan_ticks"), "makespan_time": kp.get("makespan_time"),
                           "all_done": bool(kp.get("all_done")) and not cancelled, "cancelled": cancelled,
                           "ticks": ticks, "wall_s": round(time.perf_counter() - start, 2)}
    logger.info("simulate_list %s %s seed %d, %d products: %s", strategy, mode, seed, total, out)
    if details:
        done = out["all_done"] and out["makespan_time"] is not None
        out["details"] = compute_details(rows, _rules(session.model_path), float(out["makespan_time"])) if done else None
    return out
