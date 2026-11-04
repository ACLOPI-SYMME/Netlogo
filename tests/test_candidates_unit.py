"""compute_candidates on hand-built platform-state dicts (no NetLogo)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from aclopi.contracts.candidates import CandidateParams, ModelStatic
from aclopi.sim.candidates import compute_candidates

MACHINES = [f"M{i}" for i in range(1, 8)]
# Copies of the model tables (Set.operations, Set.Machines, Set.distances.Machines).
CAPABLE = {"O1": ["M2", "M3", "M5", "M7"], "O2": ["M2", "M3", "M6", "M7"], "O3": ["M4", "M5", "M6", "M7"],
           "O4": ["M2", "M4", "M6", "M7"], "O5": ["M3", "M4", "M5", "M7"], "O6": ["M5"], "O7": ["M6"],
           "O8": ["M1"], "O9": ["M1"]}
OPS = {"M1": ["O8", "O9"], "M2": ["O1", "O2", "O4"], "M3": ["O1", "O2", "O5"], "M4": ["O3", "O4", "O5"],
       "M5": ["O1", "O3", "O5", "O6"], "M6": ["O2", "O3", "O4", "O6"], "M7": ["O1", "O2", "O3", "O4", "O5"]}
DIST = [[1, 111.3, 201.8, 186.6, 125.5, 212.1, 298.4], [287.9, 1, 124.6, 109.4, 187.2, 273.7, 360.8],
        [247.4, 161.8, 1, 69.13, 146.9, 233.4, 320.2], [212.3, 126.8, 217.3, 1, 111.9, 198.4, 285.2],
        [129.6, 211.7, 302.2, 187.6, 1, 115.6, 202.2], [208.1, 290.1, 380.7, 365.5, 304.4, 1, 121.2],
        [120.9, 203.1, 293.5, 278.4, 217.3, 139.5, 1]]


def static(modeling_type: str = "Stochastic") -> ModelStatic:
    return ModelStatic(
        capable_machines=CAPABLE,
        operation_times={m: {o: (100.0 if m == "M1" else 200.0) for o in ops} for m, ops in OPS.items()},
        nominal_times={f"O{i}": (100.0 if i >= 8 else 200.0) for i in range(1, 10)},
        modeling_type=modeling_type,
        distances={a: {b: float(DIST[i][j]) for j, b in enumerate(MACHINES)} for i, a in enumerate(MACHINES)},
    )


def machine(name: str, product: int | None = None, next_completion: float | None = None, queue: list[int] | None = None) -> dict[str, Any]:
    busy = product is not None
    return {"name": name, "state": "Machine.Processing" if busy else "Idle", "product": product,
            "next_completion": next_completion if busy else 100000000, "queue": queue or []}


def product(pid: int, ops: list[str], order: int, heading: str, next_op: str | None = None,
            ai: str = "", ai_seq: int = -1) -> dict[str, Any]:
    return {"id": pid, "operations": ops, "sequence_order": order, "heading_workstation": heading,
            "next_operation": next_op or ops[order], "ai_next_machine": ai, "ai_decision_seq": ai_seq}


def state(machines: dict[str, dict[str, Any]], products: list[dict[str, Any]], time: float = 1000.0) -> dict[str, Any]:
    ms = [machines.get(m, machine(m)) for m in MACHINES]
    return {"tick": 3226, "time": time, "machines": ms, "products": products}


OPS_E = ["O8", "O1", "O1", "O1", "O2", "O2", "O4", "O9"]  # type E
NO_STAY = CandidateParams(occupant_may_stay=False)
ME = 200  # the product being decided: in M2 doing its first O1 (seq 1), deciding seq 2 (O1)


def by_machine(result: Any) -> dict[str, Any]:
    return {c.machine: c for c in result.candidates}


def test_current_machine_is_reprocessed_in_place() -> None:
    s = state({"M2": machine("M2", ME, 1150.0, queue=[201])},
              [product(ME, OPS_E, 1, "M2"), product(201, OPS_E, 1, "M2")])
    c = by_machine(compute_candidates(s, ME, 2, static()))["M2"]
    assert c.is_current_machine and c.travel == 0 and c.queue_time == 0 and c.en_route_time == 0
    assert c.current_remaining == 0 and c.available_in == pytest.approx(150)  # own_remaining, counted once
    assert c.start == pytest.approx(1150) and c.finish == pytest.approx(1150 + 210)


def test_queue_and_busy_machine() -> None:
    s = state({"M2": machine("M2", ME, 1100.0), "M3": machine("M3", 300, 1250.0, queue=[301, 302])},
              [product(ME, OPS_E, 1, "M2"), product(300, OPS_E, 2, "M3"),
               product(301, OPS_E, 1, "M3"), product(302, ["O8", "O5", "O9"], 1, "M3")])
    c = by_machine(compute_candidates(s, ME, 2, static(), NO_STAY))["M3"]
    assert c.travel == pytest.approx(124.6) and c.current_remaining == pytest.approx(250)
    assert c.queue_time == pytest.approx(420) and c.queue == [301, 302]
    assert c.available_in == pytest.approx(670)
    assert c.arrival == pytest.approx(1000 + 100 + 124.6)
    assert c.start == pytest.approx(1000 + 670) and c.finish == pytest.approx(1670 + 210)


def test_free_far_machine_vs_busy_near_one() -> None:
    s = state({"M2": machine("M2", ME, 1100.0), "M3": machine("M3", 300, 1500.0)},
              [product(ME, OPS_E, 1, "M2"), product(300, OPS_E, 2, "M3")])
    r = compute_candidates(s, ME, 2, static(), NO_STAY)
    c = by_machine(r)
    assert c["M5"].start == pytest.approx(1000 + 100 + 187.2)  # free, farther than M3
    assert c["M3"].start == pytest.approx(1500)
    assert r.best_by_finish == "M2"  # reprocessing in place beats both
    assert [x.machine for x in r.candidates] == sorted(c, key=lambda m: (c[m].finish, int(m[1:])))


def test_en_route_products_and_exclusions() -> None:
    s = state({"M2": machine("M2", ME, 1100.0), "M4": machine("M4", 400, 1050.0)},
              [product(ME, OPS_E, 1, "M2"),
               product(401, OPS_E, 1, "M3", next_op="O1"),  # travelling to M3
               product(400, ["O8", "O3", "O1", "O9"], 1, "M4", ai="M3", ai_seq=2),  # in M4, already sent to M3
               product(402, ["O8", "O3", "O1", "O9"], 1, "M4", ai="M3", ai_seq=9)])  # stale decision: not counted
    c = by_machine(compute_candidates(s, ME, 2, static()))["M3"]
    assert c.en_route == [400, 401] and c.en_route_time == pytest.approx(420)
    only_earlier = by_machine(compute_candidates(s, ME, 2, static(), CandidateParams(en_route_only_earlier=True)))["M3"]
    # 401 is travelling (arrival 0); 400 arrives in 50 + distances[M4][M3] = 267.3 > own 100 + 124.6.
    assert only_earlier.en_route == [401]


def test_own_product_never_counted() -> None:
    s = state({"M2": machine("M2", ME, 1100.0, queue=[ME]), "M3": machine("M3", queue=[ME])},
              [product(ME, OPS_E, 1, "M2", ai="M3", ai_seq=2)])
    for c in compute_candidates(s, ME, 2, static()).candidates:
        assert ME not in c.queue and ME not in c.en_route and c.queue_time == 0 and c.en_route_time == 0


def test_long_own_remaining_hides_other_queues() -> None:
    s = state({"M2": machine("M2", ME, 1900.0), "M3": machine("M3", 300, 1300.0)},
              [product(ME, OPS_E, 1, "M2"), product(300, OPS_E, 2, "M3")])
    c = by_machine(compute_candidates(s, ME, 2, static()))["M3"]
    assert c.start == pytest.approx(c.arrival) == pytest.approx(1900 + 124.6)  # M3 is free long before


def test_next_machine_o9_and_last_operation() -> None:
    ops = ["O8", "O1", "O9"]
    s = state({"M2": machine("M2", ME, 1100.0)}, [product(ME, ops, 0, "M1")])
    s["machines"][0] = machine("M1", ME, 1100.0)
    s["machines"][1] = machine("M2")
    r = compute_candidates(s, ME, 1, static())
    for c in r.candidates:
        assert c.next_machine == "M1" and c.travel_next == pytest.approx(DIST[int(c.machine[1:]) - 1][0])
        assert c.finish_plus_next == pytest.approx(c.finish + c.travel_next)
    # Deciding the last operation: no next machine.
    s2 = state({"M1": machine("M1", ME, 1100.0)}, [product(ME, ["O8", "O1"], 0, "M1")])
    for c in compute_candidates(s2, ME, 1, static()).candidates:
        assert c.next_machine is None and c.finish_plus_next == c.finish


def test_next_machine_prefers_the_candidate_itself() -> None:
    s = state({"M2": machine("M2", ME, 1100.0)}, [product(ME, OPS_E, 1, "M2")])
    c = by_machine(compute_candidates(s, ME, 2, static()))  # next op (seq 3) is O1 again
    assert c["M3"].next_machine == "M3" and c["M3"].travel_next == 0
    assert c["M5"].next_machine == "M5"


def test_single_candidate_and_deterministic() -> None:
    ops = ["O8", "O1", "O6", "O9"]
    s = state({"M2": machine("M2", ME, 1100.0)}, [product(ME, ops, 1, "M2")])
    r = compute_candidates(s, ME, 2, static("Deterministic"))
    assert [c.machine for c in r.candidates] == ["M5"] and r.gap_finish is None and r.gap_finish_plus_next is None
    assert r.candidates[0].proc_time == 200  # no +10 in Deterministic
    assert by_machine(compute_candidates(s, ME, 2, static()))["M5"].proc_time == 210


def test_gaps_bests_and_deltas() -> None:
    s = state({"M2": machine("M2", ME, 1100.0), "M3": machine("M3", 300, 1500.0)},
              [product(ME, OPS_E, 1, "M2"), product(300, OPS_E, 2, "M3")])
    r = compute_candidates(s, ME, 2, static())
    finishes = sorted(c.finish for c in r.candidates)
    assert r.gap_finish == pytest.approx(finishes[1] - finishes[0])
    assert min(c.delta_finish for c in r.candidates) == 0 and min(c.delta_finish_plus_next for c in r.candidates) == 0
    assert r.travel_source == "distances" and r.current_machine == "M2" and r.own_remaining == pytest.approx(100)


def test_occupant_and_first_queued_may_stay() -> None:
    # M3: 300 processes O1 (index 2) and its next one (index 3) is O1 too; 301 waits for O1 (index 1)
    # and its following one (index 2) is O1: both may be reprocessed in place.
    s = state({"M2": machine("M2", ME, 1100.0), "M3": machine("M3", 300, 1250.0, queue=[301])},
              [product(ME, OPS_E, 1, "M2"), product(300, OPS_E, 2, "M3"), product(301, OPS_E, 1, "M3")])
    # Chains (cap 3): 300 does O1 O2 O2 (indices 3-5) on M3; 301 does O1 O1 O2 (indices 2-4).
    c = by_machine(compute_candidates(s, ME, 2, static()))["M3"]
    assert c.stay == [300, 301] and c.stay_time == pytest.approx(6 * 210)
    assert c.available_in == pytest.approx(250 + 210 + 6 * 210)
    one = by_machine(compute_candidates(s, ME, 2, static(), CandidateParams(occupant_chain_max=1)))["M3"]
    assert one.stay_time == pytest.approx(2 * 210)  # only the next operation of each
    off = by_machine(compute_candidates(s, ME, 2, static(), NO_STAY))["M3"]
    assert off.stay == [] and off.available_in == pytest.approx(250 + 210)


def test_chain_stops_at_the_first_operation_the_machine_cannot_do() -> None:
    # 500 in M5 doing O3 (index 1); next O5 (M5 can), then O9 (M5 cannot): chain of 1.
    s2 = state({"M3": machine("M3", ME, 1100.0), "M5": machine("M5", 500, 1250.0)},
               [product(ME, ["O8", "O1", "O5", "O9"], 1, "M3"), product(500, ["O8", "O3", "O5", "O9"], 1, "M5")])
    assert by_machine(compute_candidates(s2, ME, 2, static()))["M5"].stay_time == pytest.approx(210)


def test_stay_skips_an_operation_already_counted_and_needs_a_capable_machine() -> None:
    # 300 in M3 already sent to M3 for index 3 (counted en route): the stay is index 4 (O2, M3 can do it).
    s = state({"M2": machine("M2", ME, 1100.0), "M3": machine("M3", 300, 1250.0)},
              [product(ME, OPS_E, 1, "M2"), product(300, OPS_E, 2, "M3", ai="M3", ai_seq=3)])
    c = by_machine(compute_candidates(s, ME, 2, static()))["M3"]
    # Chain from index 4: O2 O2 (M3), then O4 (M3 cannot) -> 2 operations.
    assert c.en_route == [300] and c.stay == [300] and c.available_in == pytest.approx(250 + 210 + 2 * 210)
    # 400 in M5 doing O3 with O9 next: M5 cannot do O9, so it leaves.
    s = state({"M2": machine("M2", ME, 1100.0), "M5": machine("M5", 400, 1250.0)},
              [product(ME, OPS_E, 1, "M2"), product(400, ["O8", "O3", "O9"], 1, "M5")])
    assert by_machine(compute_candidates(s, ME, 2, static()))["M5"].stay == []


def test_result_fits_the_platform_response_model() -> None:
    from aclopi.api.models import CandidatesResponse

    s = state({"M2": machine("M2", ME, 1100.0), "M3": machine("M3", 300, 1500.0, queue=[301])},
              [product(ME, OPS_E, 1, "M2"), product(300, OPS_E, 2, "M3"), product(301, OPS_E, 1, "M3")])
    data = compute_candidates(s, ME, 2, static()).as_dict()
    parsed = CandidatesResponse(**data).model_dump()
    assert parsed["best_by_finish"] == data["best_by_finish"] and parsed["candidates"][0]["available"] is True
    assert parsed["candidates"][0]["available_in"] == data["candidates"][0]["available_in"]


def test_invalid_requests() -> None:
    s = state({"M2": machine("M2", ME, 1100.0)}, [product(ME, OPS_E, 1, "M2"), product(201, OPS_E, 1, "M3")])
    assert compute_candidates(s, 999, 2, static()).reason == "unknown-or-finished-product"
    assert compute_candidates(s, ME, 99, static()).reason == "invalid-seq"
    assert compute_candidates(s, ME, 3, static()).reason == "seq-mismatch"
    assert compute_candidates(s, 201, 2, static()).reason == "not-in-machine"


def test_distances_match_measured_travel_times() -> None:
    """data/a0/travel_times.csv (A0 phase 0): minimum measured ticks x 0.31 = distances within 1 % on
    every route with at least 2 trips; routes seen once (M3->M7, M6->M5, M6->M4) include waits, so
    there distances is only a lower bound."""
    path = Path(__file__).resolve().parents[1] / "data" / "a0" / "travel_times.csv"
    rows = [r for r in csv.DictReader(path.open(encoding="utf-8")) if r["min_ticks"]]
    assert len(rows) >= 10
    for r in rows:
        measured = float(r["min_ticks"]) * 0.31
        expected = DIST[int(r["from"][1:]) - 1][int(r["to"][1:]) - 1]
        assert float(r["distance"]) == pytest.approx(expected)
        assert measured >= expected * 0.99, (r["from"], r["to"])  # never faster than distances
        if int(r["trips_b_free"]) >= 2:
            assert measured == pytest.approx(expected, rel=0.01), (r["from"], r["to"])
