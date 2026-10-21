"""Structure of platform-layout, platform-state and the event buffer, and proof that reading them
does not alter the simulation."""

from __future__ import annotations

import json
from typing import Any

import pytest

from conftest import report_json, setup_run

N_TICKS = 500
EVENT_FIELDS = ["tick", "event", "who", "product_type", "location", "operation", "next_operation", "destination", "time"]
EVENT_TYPES = {"ProductEntersMachine", "ProductExitsMachine", "PassingBy"}
MACHINE_NAMES = [f"M{i}" for i in range(1, 8)]
SEGMENTS = ["W1", "W2", "W3A", "W3B"] + [f"W{i}" for i in range(4, 19)]
IDLE_COMPLETION = 100000000  # Next.Completion of an idle machine


def is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def run_ticks(netlogo: Any, n: int) -> None:
    netlogo.command(f"repeat {n} [ go ]")


def test_json_helpers_escape_and_numbers(netlogo: Any) -> None:
    assert json.loads(str(netlogo.report(r'json-str "a\"b\\c\nd"'))) == 'a"b\\c\nd'
    assert json.loads(str(netlogo.report("json-num 100000000"))) == IDLE_COMPLETION
    assert json.loads(str(netlogo.report("json-num 0.00001"))) == pytest.approx(1e-5)
    assert json.loads(str(netlogo.report("json-num 1e20"))) == pytest.approx(1e20)
    assert json.loads(str(netlogo.report("json-num -3.5"))) == -3.5
    assert json.loads(str(netlogo.report("json-list []"))) == []
    assert json.loads(str(netlogo.report("json-obj []"))) == {}
    assert json.loads(str(netlogo.report('json-any (list 1 "x" true (list 2.5 "y"))'))) == [1, "x", True, [2.5, "y"]]


def test_platform_layout_structure(netlogo: Any) -> None:
    setup_run(netlogo, rule=3)
    layout = report_json(netlogo, "platform-layout")

    assert set(layout) == {"nodes", "conveyors", "curves", "machines", "sensors", "switches"}
    assert len(layout["nodes"]) == 94
    node_ids = {n["id"] for n in layout["nodes"]}
    assert all(set(n) == {"id", "x", "y"} and is_num(n["x"]) and is_num(n["y"]) for n in layout["nodes"])

    assert len(layout["conveyors"]) == 105
    for c in layout["conveyors"]:
        assert set(c) == {"from", "to", "shape", "default_position", "active"}
        assert c["from"] in node_ids and c["to"] in node_ids
        assert c["shape"] in {"default", "curve1", "curve2", "curve3"}
        assert isinstance(c["default_position"], bool) and isinstance(c["active"], bool)
    assert set(layout["curves"]) == {"curve1", "curve2", "curve3"}

    assert [m["name"] for m in layout["machines"]] == MACHINE_NAMES
    assert all(is_num(m["x"]) and is_num(m["y"]) for m in layout["machines"])
    assert len(layout["sensors"]) == 48
    assert len(layout["switches"]["diverge"]) == 11 and len(layout["switches"]["merge"]) == 11
    assert set(layout["switches"]["diverge"]) <= node_ids and set(layout["switches"]["merge"]) <= node_ids


@pytest.mark.parametrize("rule", [1, 2, 3])
def test_platform_state_structure(netlogo: Any, rule: int) -> None:
    setup_run(netlogo, rule=rule)
    initial = report_json(netlogo, "platform-state")
    # Idle machines report the large sentinel completion time; it must survive JSON encoding.
    assert all(m["next_completion"] == IDLE_COMPLETION for m in initial["machines"])

    run_ticks(netlogo, N_TICKS)
    state = report_json(netlogo, "platform-state")

    assert set(state) == {"tick", "time", "terminado", "finished", "segments", "gates", "machines", "products"}
    assert state["tick"] == N_TICKS
    assert is_num(state["time"]) and state["terminado"] == "No"
    assert set(state["segments"]) == set(SEGMENTS)
    assert all(v in (0, 1) for v in state["segments"].values())

    assert len(state["gates"]) == 22
    for g in state["gates"]:
        assert set(g) == {"node", "kind", "active"} and g["kind"] in {"diverge", "merge"}
        assert g["active"] is None or isinstance(g["active"], int)

    assert [m["name"] for m in state["machines"]] == MACHINE_NAMES
    for m in state["machines"]:
        assert set(m) == {"id", "name", "state", "operation", "product", "remaining", "next_completion", "queue", "attractiveness"}
        assert m["state"] in {"Idle", "Machine.Processing"}
        assert is_num(m["next_completion"]) and isinstance(m["queue"], list)
        if m["state"] == "Machine.Processing":
            assert is_num(m["remaining"])
        else:
            assert m["remaining"] is None and m["next_completion"] == IDLE_COMPLETION

    assert state["products"], "products should exist after 500 ticks"
    for p in state["products"]:
        assert set(p) == {
            "id", "type", "state", "x", "y", "last_node", "next_node", "next_operation",
            "heading_workstation", "sequence_order", "operations", "created",
        }
        assert p["id"] >= 200 and p["type"] in {"A", "I", "P", "B", "E", "L", "T"}
        assert p["state"] != "death"
        assert is_num(p["x"]) and is_num(p["y"]) and is_num(p["created"])
        assert 0 < p["created"] <= state["time"]
        assert isinstance(p["operations"], list) and p["operations"]


@pytest.mark.parametrize("rule", [1, 2, 3])
def test_event_buffer_structure(netlogo: Any, rule: int) -> None:
    setup_run(netlogo, rule=rule)
    assert report_json(netlogo, "platform-events")["events"] == []

    run_ticks(netlogo, N_TICKS)
    payload = report_json(netlogo, "platform-events")
    assert payload["fields"] == EVENT_FIELDS
    events = payload["events"]
    # The buffer mirrors every row appended to EventFrameInfo (the Events CSV).
    assert len(events) == int(netlogo.report("length EventFrameInfo"))
    for ev in events:
        assert len(ev) == len(EVENT_FIELDS)
        tick, kind, who, ptype, location, operation, next_op, destination, time = ev
        assert isinstance(tick, int) and 0 <= tick < N_TICKS
        assert kind in EVENT_TYPES and isinstance(who, int) and who >= 200
        assert all(isinstance(v, str) for v in (ptype, location, operation, next_op, destination))
        assert operation not in {"XXX", "YYY"}
        assert is_num(time) and abs(time - tick * 0.31) <= 0.32

    netlogo.command("platform-clear-events")
    assert report_json(netlogo, "platform-events")["events"] == []


def snapshot(netlogo: Any) -> dict[str, Any]:
    """Full observable state plus the next random numbers (equal only if the RNG state is equal)."""
    return {
        "state": str(netlogo.report("platform-state")),
        "events_csv": str(netlogo.report("(word EventFrameInfo)")),
        "data_csv": str(netlogo.report("(word DataFrameInfo)")),
        "rng": [int(netlogo.report("random 2147483647")) for _ in range(3)],
    }


def test_snapshot_detects_unprotected_reads(netlogo: Any) -> None:
    """Control: a read that shuffles an agentset outside with-local-randomness must be detected."""
    setup_run(netlogo, rule=3)
    for _ in range(N_TICKS):
        netlogo.command("go")
    clean = snapshot(netlogo)

    setup_run(netlogo, rule=3)
    for _ in range(N_TICKS):
        netlogo.command("go")
        netlogo.report("length [who] of nodes")  # consumes the main RNG
    assert snapshot(netlogo) != clean


@pytest.mark.parametrize("rule", [1, 2, 3])
def test_reading_does_not_alter_simulation(netlogo: Any, rule: int) -> None:
    setup_run(netlogo, rule=rule)
    for _ in range(N_TICKS):
        netlogo.command("go")
    unread_events = report_json(netlogo, "platform-events")["events"]
    unread = snapshot(netlogo)

    setup_run(netlogo, rule=rule)
    report_json(netlogo, "platform-layout")
    read_events: list[Any] = []
    for _ in range(N_TICKS):
        netlogo.command("go")
        report_json(netlogo, "platform-state")
        read_events.extend(report_json(netlogo, "platform-events")["events"])
        netlogo.command("platform-clear-events")
    read = snapshot(netlogo)

    assert read_events == unread_events
    assert read == unread
