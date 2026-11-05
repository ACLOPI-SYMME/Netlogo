from __future__ import annotations

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

# Test groups (CLAUDE.md, rule 4; pytest.ini). A test marked slow keeps only slow, so -m api never runs 100,000 ticks.
UNIT_FILES = {"test_agent_core", "test_agent_llm", "test_agent_service", "test_agent_token", "test_agent_triage",
              "test_candidates_unit", "test_decide_context", "test_hub", "test_ui_product_set", "test_whatif_estimate"}
API_FILES = {"test_whatif", "test_live", "test_agent_decisions", "test_workers", "test_api"}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        name = item.path.stem
        if item.get_closest_marker("slow"):
            continue
        if name in UNIT_FILES:
            item.add_marker(pytest.mark.unit)
        elif name in API_FILES:
            item.add_marker(pytest.mark.api)


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
