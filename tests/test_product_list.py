"""Product list in the model (product-list?, product-list; docs/product-sets.md)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from aclopi.sim import SimulationSession
from aclopi.sim.session import validate_product_list

PRODUCTS = "platform-local [ -> json-any map [p -> [(list who ProductType priority)] of p] sort products ]"


def _run(product_list: list[tuple[str, int]] | None, ticks: int = 10000) -> tuple[dict[str, Any], list[Any]]:
    with SimulationSession() as s:
        s.setup(seed=42, rule=3, horizon_ticks=ticks, product_list=product_list)
        s.run_to_end()
        return s.kpis().as_dict(), json.loads(str(s._report(PRODUCTS)))


def test_list_from_the_seed_equals_the_fixed_sequence() -> None:
    """Guarantee 2: the fixed sequence of seed 42, loaded as a product list, gives exactly the same
    products and KPIs over 10,000 ticks."""
    with SimulationSession() as s:
        s.setup(seed=42, rule=3)
        generated = s.product_sequence(42, 300)
    fixed_kpis, fixed_products = _run(None)
    list_kpis, list_products = _run(generated)
    assert len(fixed_products) > 10
    assert list_products == fixed_products
    list_only = {"products_total", "all_done", "makespan_ticks", "makespan_time"}  # KPIs of a list run
    same = {k: v for k, v in fixed_kpis.items() if k not in list_only}
    assert {k: v for k, v in list_kpis.items() if k not in list_only} == same
    assert list_kpis["products_total"] == 300 and fixed_kpis["products_total"] is None


def test_short_list_creates_exactly_those_products() -> None:
    items = [("E", 70), ("A", 90), ("T", 60), ("A", 100), ("L", 80)]
    with SimulationSession() as s:
        s.setup(seed=7, rule=3, horizon_ticks=20000, product_list=items)
        state = s.state()
        assert state["product_list_active"] is True and state["product_list_length"] == 5
        s.step(2000)
        while s.ticks < 20000 and s.state()["product_list_next"] < 5:
            s.step(2000)
        s.step(2000)
        created = json.loads(str(s._report(PRODUCTS)))
        assert [(t, p) for _, t, p in created] == items  # in entry order (who order)
        assert s.state()["product_list_next"] == 5


def test_switch_off_by_default() -> None:
    with SimulationSession() as s:
        s.setup(seed=42, rule=3)
        state = s.state()
        assert state["product_list_active"] is False and state["product_list_length"] == 0


@pytest.mark.parametrize("bad", [[], [("X", 80)], [("A", 59)], [("A", 101)], [("A", 80.5)], [("A", 80)] * 1001])
def test_validation(bad: list[Any]) -> None:
    with pytest.raises(ValueError):
        validate_product_list(bad)


def test_exact_stop_is_identical_to_step() -> None:
    """step_product_list stops at the go in which the last product finishes; up to that tick the run
    is the same as with step (the stop condition uses no random numbers)."""
    items = [("E", 70), ("A", 90), ("T", 60)]
    with SimulationSession() as s:
        s.setup(seed=7, rule=3, horizon_ticks=40000, product_list=items)
        done = False
        while not done:
            r, done = s.step_product_list(2000)
            assert r.ticks < 40000
        stop_tick, kpis = s.ticks, s.kpis().as_dict()
        assert kpis["all_done"] and kpis["finished"] == 3
        r, done = s.step_product_list(2000)
        assert r.advanced == 0 and done  # never advances after the end
    with SimulationSession() as s:
        s.setup(seed=7, rule=3, horizon_ticks=40000, product_list=items)
        left = stop_tick
        while left > 0:
            left -= s.step(min(left, 2000)).advanced
        assert s.kpis().as_dict() == kpis
