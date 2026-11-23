from __future__ import annotations

import faulthandler
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "model" / "Paper.nlogo"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Test groups (CLAUDE.md, rule 4; pytest.ini). A slow test of an API file is also api: it starts a whole pool
# (or runs live), so it never goes with -n. Commands: -m "api and not slow"; -m "slow and not api" -n 4; -m "slow and api".
UNIT_FILES = {"test_agent_core", "test_agent_llm", "test_agent_service", "test_agent_token", "test_agent_triage",
              "test_candidates_unit", "test_decide_context", "test_hub", "test_product_limits_unit", "test_scenarios_unit",
              "test_ui_product_set", "test_whatif_estimate", "test_sequencing_unit", "test_optimize_unit",
              "test_origin_unit"}
API_FILES = {"test_whatif", "test_live", "test_agent_decisions", "test_workers", "test_api", "test_sequencing_platform",
             "test_optimize_order"}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        name = item.path.stem
        if name in API_FILES:
            item.add_marker(pytest.mark.api)
        elif item.get_closest_marker("slow"):
            continue
        elif name in UNIT_FILES:
            item.add_marker(pytest.mark.unit)


# Hang watchdog (no plugin needed): a test that runs longer than its limit, or a pytest process that does not
# exit after the session, dumps the stack of every Python thread to stderr and ends the process (exit code 1),
# so a hang is diagnosed instead of waiting for ever. Limits: ACLOPI_TEST_TIMEOUT_S (600 s per test; slow tests
# 3600 s) and ACLOPI_EXIT_TIMEOUT_S (180 s from the end of the session to the process exit).
TEST_TIMEOUT_S = float(os.environ.get("ACLOPI_TEST_TIMEOUT_S", "") or 600)
SLOW_TEST_TIMEOUT_S = 3600.0
EXIT_TIMEOUT_S = float(os.environ.get("ACLOPI_EXIT_TIMEOUT_S", "") or 180)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Iterator[None]:
    limit = SLOW_TEST_TIMEOUT_S if item.get_closest_marker("slow") else TEST_TIMEOUT_S
    sys.stderr.write("")  # make sure stderr exists before arming
    faulthandler.dump_traceback_later(limit, exit=True, file=sys.__stderr__)
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()


def pytest_unconfigure(config: pytest.Config) -> None:
    # Armed until the interpreter exits: a process stuck at exit (e.g. joining worker processes whose pool was
    # never shut down) is dumped and ended.
    faulthandler.dump_traceback_later(EXIT_TIMEOUT_S, exit=True, file=sys.__stderr__)


RULES = {
    1: "Rule 1 - Random Machine",
    2: "Rule 2 - Nearest Machine",
    3: "Rule 3 - Potential Fields",
}


@pytest.fixture(scope="session")
def netlogo() -> Iterator[Any]:
    """One headless NetLogo workspace with Paper.nlogo loaded, shared by all tests (one JVM per process)."""
    load_dotenv(REPO_ROOT / ".env")
    home, jvm = os.environ.get("NETLOGO_HOME"), os.environ.get("JVM_PATH")
    if not home or not jvm or not Path(home).exists() or not Path(jvm).exists():
        pytest.skip("NETLOGO_HOME / JVM_PATH not configured (see .env.example)")

    import pynetlogo

    link = pynetlogo.NetLogoLink(gui=False, netlogo_home=home, jvm_path=jvm)
    link.load_model(str(MODEL_PATH))
    yield link
    link.kill_workspace()


def setup_run(netlogo: Any, rule: int, seed: int = 42, modeling_type: str = "Stochastic") -> None:
    netlogo.command(f"random-seed {seed}")
    netlogo.command(f'set Reactivity.rule "{RULES[rule]}"')
    netlogo.command(f'set Modeling.Type "{modeling_type}"')
    netlogo.command("setup")


def report_json(netlogo: Any, reporter: str) -> Any:
    # pynetlogo returns java.lang.String for NetLogo strings.
    return json.loads(str(netlogo.report(reporter)))
