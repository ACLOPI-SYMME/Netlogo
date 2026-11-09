"""Set de productos tab, scenario form and rule / strategy (live.html) in a headless browser, without NetLogo.

A small FastAPI app serves the real page and the endpoints the tab uses: parse-csv with the real
parser (aclopi.api.product_sets.parse_csv), product-sets, health, GET /scenarios (the real
list_scenarios), GET /runs (the runs in RUNS) and POST /sessions (records the body). Needs Playwright with Chromium or Edge (`pip install playwright`); skipped otherwise.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

from fastapi import FastAPI, File, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402

from aclopi.api.product_sets import parse_csv  # noqa: E402
from aclopi.sim.scenarios import list_scenarios  # noqa: E402

PAGE = Path(__file__).resolve().parents[1] / "aclopi" / "api" / "static" / "live.html"
CSV_OK = "type,priority\nA,70\nI,80\nP,90\nB,60\nE,100\n"
CSV_WITH_ERRORS = "type,priority\nA,70\nX,80\n\nB,60\nE,100\n"


def _run(run_id: str, rule: int, strategy: str | None) -> dict[str, Any]:
    return {"run_id": run_id, "created_at": 1_700_000_000, "status": "finished", "reason": "horizon", "rule": rule,
            "strategy": strategy, "seed": 42, "seed_source": "given", "horizon_ticks": 3000, "mode": "fast",
            "ticks": 3000, "scenario_id": "S0", "scenario": {"id": "S0", "params": {}}, "kpis": {"finished": 1}}


# Rule 4 runs as the API stores them: agent (the page), b1 / b1b (experiments), none (tests).
RUNS = [_run("run-agent-0001", 4, "agent"), _run("run-b1-000001", 4, "b1"), _run("run-b1b-00001", 4, "b1b"),
        _run("run-none-0001", 4, "none"), _run("run-rule3-001", 3, None)]


def fake_platform(sessions: list[dict[str, Any]]) -> FastAPI:
    app = FastAPI()

    @app.get("/ui")
    def ui() -> FileResponse:
        return FileResponse(PAGE, media_type="text/html")

    @app.post("/product-sets/parse-csv")
    async def parse(file: UploadFile = File(...)) -> Any:
        products, problems = parse_csv(await file.read())
        if problems:
            return JSONResponse({"code": "csv_invalid", "detail": "errors", "errors": problems}, status_code=422)
        return {"products": products, "total": len(products)}

    @app.get("/product-sets")
    def sets() -> list[Any]:
        return []

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ready"}

    @app.get("/runs")
    def runs() -> dict[str, Any]:
        return {"runs": RUNS, "next_cursor": None}

    @app.get("/scenarios")
    def scenarios() -> list[Any]:
        return [{"id": sc.id, "name": sc.name, "description": sc.description, "params": [vars(p) for p in sc.params]}
                for sc in list_scenarios()]

    @app.post("/sessions")
    async def create(request: Request) -> dict[str, Any]:
        sessions.append(await request.json())
        body = await request.json()
        return {"session_id": "s1", "parameters": {"seed": 1}, "seed_source": "random", "warnings": [],
                "scenario": body.get("scenario") or {"id": "S0", "params": {}}}

    return app


@pytest.fixture(scope="module")
def server() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    sessions: list[dict[str, Any]] = []
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(fake_platform(sessions), host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", sessions
    srv.should_exit = True
    thread.join(5)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge")  # the installed Edge: no browser download
        except Exception:  # noqa: BLE001 - elsewhere (e.g. Linux CI) Playwright's own Chromium, if installed
            b = p.chromium.launch()
        yield b
        b.close()


def load_csv(page: Any, tmp_path: Path, text: str) -> None:
    path = tmp_path / "set.csv"
    path.write_text(text, encoding="utf-8")
    page.click("#tab-set")
    page.set_input_files("#csv-file", str(path))
    page.wait_for_function("document.querySelectorAll('#set-rows tr').length > 0")


def rows(page: Any) -> list[str]:
    return page.eval_on_selector_all("#set-rows tr select", "els => els.map(e => e.value)")


def test_csv_drag_delete_and_session_body(server: tuple[str, list], browser: Any, tmp_path: Path) -> None:
    url, sessions = server
    page = browser.new_page()
    page.on("dialog", lambda d: d.accept())
    page.goto(f"{url}/ui")
    load_csv(page, tmp_path, CSV_OK)
    assert rows(page) == ["A", "I", "P", "B", "E"]

    page.drag_and_drop("#set-rows tr:nth-child(1) td.handle", "#set-rows tr:nth-child(4)")  # A -> before B's slot
    assert rows(page) == ["I", "P", "B", "A", "E"]
    page.click("#set-rows tr:nth-child(2) button[data-a=del]")  # delete P
    assert rows(page) == ["I", "B", "A", "E"]
    page.select_option("#set-rows tr:nth-child(1) select", "T")  # edit a type
    assert rows(page) == ["T", "B", "A", "E"]

    page.click("#tab-session")
    assert page.input_value("#session-set") == "__current__"
    page.click("#create")
    page.wait_for_function("true")
    for _ in range(50):
        if sessions:
            break
        time.sleep(0.1)
    sent = sessions[-1]
    assert sent["products"] == [{"type": "T", "priority": 80}, {"type": "B", "priority": 60},
                                {"type": "A", "priority": 70}, {"type": "E", "priority": 100}]
    assert "product_set_id" not in sent
    print("JSON sent:", json.dumps(sent))
    page.close()


def test_csv_errors_keep_valid_rows(server: tuple[str, list], browser: Any, tmp_path: Path) -> None:
    url, _ = server
    page = browser.new_page()
    page.goto(f"{url}/ui")
    load_csv(page, tmp_path, CSV_WITH_ERRORS)
    assert rows(page) == ["A", "B", "E"]
    errors = page.inner_text("#set-errors")
    assert "línea 3" in errors and "línea 4: fila vacía" in errors and "Se cargaron 3 filas" in errors
    page.close()


def _sent(sessions: list[dict[str, Any]], before: int) -> dict[str, Any]:
    for _ in range(50):
        if len(sessions) > before:
            return sessions[-1]
        time.sleep(0.1)
    raise AssertionError("POST /sessions not sent")


def test_scenario_form_and_live_notices(server: tuple[str, list], browser: Any) -> None:
    url, sessions = server
    page = browser.new_page()
    page.goto(f"{url}/ui")
    page.wait_for_function("document.querySelectorAll('#scenario option').length === 4")
    # S3: the machine list needs at least one machine (error next to the field, nothing sent)
    page.select_option("#scenario", "S3")
    page.click("#scenario-params-box summary")  # "Parámetros del escenario" starts folded
    assert page.input_value('#scenario-params [data-p="interval_ticks"]') == "5000"
    for box in page.query_selector_all('#scenario-params input[data-p="machines"]'):
        box.uncheck()
    before = len(sessions)
    page.click("#create")
    page.wait_for_function("document.querySelector('[data-err=\"machines\"]').textContent !== ''")
    assert "al menos una" in page.inner_text('[data-err="machines"]') and len(sessions) == before
    page.check('#scenario-params input[value="M4"]')
    page.fill('#scenario-params [data-p="interval_ticks"]', "300")  # out of range (500-1000000)
    page.click("#create")
    assert "entre 500" in page.inner_text('[data-err="interval_ticks"]') and len(sessions) == before
    page.fill('#scenario-params [data-p="interval_ticks"]', "800")
    page.click("#create")
    assert _sent(sessions, before)["scenario"] == {"id": "S3", "params": {"interval_ticks": 800, "repair_ut": 300,
                                                                           "machines": ["M4"]}}
    # S1 partial: an empty field means "no change"
    page.select_option("#scenario", "S1")
    for m in ("M2", "M3", "M5", "M6", "M7"):
        page.fill(f'#scenario-params [data-p="times"][data-m="{m}"]', "")
    page.fill('#scenario-params [data-p="times"][data-m="M4"]', "350")
    before = len(sessions)
    page.click("#create")
    assert _sent(sessions, before)["scenario"] == {"id": "S1", "params": {"times": {"M4": 350}}}
    # Live notices: a toast, the event list, and a skipped event dimmed
    event = {"type": "scenario", "tick": 800, "kind": "repair", "machine": "M4", "value": 300, "label": "Falla en M4: +300 u.t.",
             "applied": True, "skip_reason": None, "before": None, "after": None}
    page.evaluate("ev => handle({type: 'scenario_event', tick: ev.tick, event: ev})", event)
    assert page.is_visible("#toast") and "Falla en M4" in page.inner_text("#toast")
    assert "ESCENARIO Falla en M4: +300 u.t." in page.inner_text("#events")
    page.evaluate("ev => handle({type: 'scenario_event', tick: 1600, event: {...ev, tick: 1600, applied: false, "
                  "skip_reason: 'machine-idle'}})", event)
    assert "Falla saltada: M4 libre" in page.inner_text("#toast")
    assert page.eval_on_selector("#toast", "e => e.className") == "skipped"
    assert page.eval_on_selector_all("#events div.skipped", "els => els.length") == 1
    page.close()


def test_rule_4_is_the_agent_and_runs_show_the_strategy(server: tuple[str, list], browser: Any) -> None:
    url, sessions = server
    page = browser.new_page()
    page.goto(f"{url}/ui")
    page.wait_for_function("document.querySelectorAll('#scenario option').length === 4")
    # No strategy selector; rule 4 is "Regla 4 — Agente IA" and always creates the session with agent.
    assert page.query_selector("#strategy") is None and page.query_selector("#strategy-box") is None
    assert page.eval_on_selector("#rule option[value='4']", "e => e.textContent") == "Regla 4 — Agente IA"
    page.select_option("#rule", "4")
    before = len(sessions)
    page.click("#create")
    sent = _sent(sessions, before)
    assert (sent["rule"], sent["strategy"]) == (4, "agent")
    page.select_option("#rule", "3")
    before = len(sessions)
    page.click("#create")
    assert "strategy" not in _sent(sessions, before)
    # Runs: "Regla 4 (agente)", "(B1)", "(B1b)"; a none run (tests) is just "Regla 4".
    page.click("#tab-runs")
    page.wait_for_function("document.querySelectorAll('#runs-rows tr').length === 5")
    rules = page.eval_on_selector_all("#runs-rows tr td:nth-child(4)", "els => els.map(e => e.textContent)")
    assert rules == ["Regla 4 (agente)", "Regla 4 (B1)", "Regla 4 (B1b)", "Regla 4", "Regla 3"]
    # The comparison uses the same names.
    for run_id in ("run-agent-0001", "run-b1-000001", "run-b1b-00001"):
        page.check(f'#runs-rows input[data-id="{run_id}"]')
    page.click("#runs-compare")
    heads = page.eval_on_selector_all("#runs-compare-box th", "els => els.map(e => e.textContent)")
    assert heads[1:] == ["Regla 4 (agente) run-ag", "Regla 4 (B1) run-b1", "Regla 4 (B1b) run-b1"]
    # "none" appears nowhere in the interface (visible text, options, values of the controls).
    texts = page.evaluate("""() => [document.body.innerText,
        ...[...document.querySelectorAll('option, input, select')].map(e => e.value + ' ' + e.textContent)].join(' ')""")
    assert "none" not in texts.lower()
    # Repetir keeps the original strategy (b1 run -> b1; agent run -> agent).
    before = len(sessions)
    page.click('#runs-rows tr:nth-child(2) [data-a="repeat"]')
    sent = _sent(sessions, before)
    assert (sent["rule"], sent["strategy"]) == (4, "b1")
    page.click("#tab-runs")
    page.wait_for_function("document.querySelectorAll('#runs-rows tr').length === 5")
    before = len(sessions)
    page.click('#runs-rows tr:nth-child(1) [data-a="repeat"]')
    assert _sent(sessions, before)["strategy"] == "agent"
    page.close()
