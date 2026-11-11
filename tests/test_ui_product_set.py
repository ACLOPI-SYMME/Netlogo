"""Set de productos tab, rule / strategy, decision panels and no scenarios (live.html) in a headless
browser, without NetLogo.

A small FastAPI app serves the real page and the endpoints the tab uses: parse-csv with the real
parser (aclopi.api.product_sets.parse_csv), product-sets, health, GET /runs (the runs in RUNS),
GET /runs/{id}/decisions (DECISIONS) and POST /sessions (records the body). Needs Playwright with Chromium or Edge (`pip install playwright`); skipped otherwise.
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

PAGE = Path(__file__).resolve().parents[1] / "aclopi" / "api" / "static" / "live.html"
CSV_OK = "type,priority\nA,70\nI,80\nP,90\nB,60\nE,100\n"
CSV_WITH_ERRORS = "type,priority\nA,70\nX,80\n\nB,60\nE,100\n"


def _run(run_id: str, rule: int, strategy: str | None, scenario: dict[str, Any] | None = None) -> dict[str, Any]:
    scenario = scenario or {"id": "S0", "params": {}}
    return {"run_id": run_id, "created_at": 1_700_000_000, "status": "finished", "reason": "horizon", "rule": rule,
            "strategy": strategy, "seed": 42, "seed_source": "given", "horizon_ticks": 3000, "mode": "fast",
            "ticks": 3000, "scenario_id": scenario["id"], "scenario": scenario, "kpis": {"finished": 1}}


# Rule 4 runs as the API stores them: agent (the page), b1 / b1b (experiments), none (tests); and a
# rule 3 run saved before scenarios were taken out, with S2.
RUNS = [_run("run-agent-0001", 4, "agent"), _run("run-b1-000001", 4, "b1"), _run("run-b1b-00001", 4, "b1b"),
        _run("run-none-0001", 4, "none"),
        _run("run-rule3-001", 3, None, {"id": "S2", "params": {"machine": "M7", "factor": 1.75, "start_tick": 1000}})]
LEVELS = ["code-obvious", "llm", "llm-what-if", "code-fallback"]
# 120 saved decisions of run-agent-0001 (oldest first, as GET /runs/{id}/decisions gives them).
DECISIONS = [{"seq": i, "tick": 100 + 10 * i, "request_tick": 99 + 10 * i, "product": 200 + i % 7, "product_type": "AIPBELT"[i % 7],
              "operation": f"O{1 + i % 8}", "machine": f"M{2 + i % 6}", "decision_level": LEVELS[i % 4],
              "reason": ("razón larga, " * 12 + f"fin {i}") if i % 4 == 1 else f"obvia {i}",
              "latency_ms": 40.0 + i, "late": i % 10 == 9, "strategy": "agent", "result": "ok"} for i in range(120)]


RUN_CALLS: list[dict[str, Any]] = []  # bodies of POST /sessions/{id}/run


def fake_platform(sessions: list[dict[str, Any]]) -> FastAPI:
    app = FastAPI()

    @app.post("/sessions/{sid}/run")
    async def run(sid: str, request: Request) -> dict[str, Any]:
        body = await request.json()
        RUN_CALLS.append(body)
        return {"session_id": sid, "run_state": "running_" + body["mode"], "mode": body["mode"], "speed": body.get("speed")}

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

    @app.get("/runs/{run_id}/decisions")
    def run_decisions(run_id: str) -> list[Any]:
        return DECISIONS if run_id == "run-agent-0001" else []

    @app.post("/sessions")
    async def create(request: Request) -> dict[str, Any]:
        sessions.append(await request.json())
        return {"session_id": "s1", "parameters": {"seed": 1}, "seed_source": "random", "warnings": [],
                "scenario": {"id": "S0", "params": {}}}

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
    assert "line 3" in errors and "line 4: empty row" in errors and "Loaded 3 rows" in errors
    page.close()


def _sent(sessions: list[dict[str, Any]], before: int) -> dict[str, Any]:
    for _ in range(50):
        if len(sessions) > before:
            return sessions[-1]
        time.sleep(0.1)
    raise AssertionError("POST /sessions not sent")


def _ready(page: Any) -> None:
    page.wait_for_function("typeof handle === 'function' && document.querySelector('#saved-sets') !== null")


def test_no_scenarios_and_live_decision_panel(server: tuple[str, list], browser: Any) -> None:
    url, sessions = server
    page = browser.new_page()
    page.goto(f"{url}/ui")
    _ready(page)
    # No scenario selector, params, toast nor filter / columns in the runs tab; no scenario is sent.
    for sel in ("#scenario", "#scenario-params", "#toast", "#runs-scenario"):
        assert page.query_selector(sel) is None, sel
    assert "scenario" not in page.inner_text("body").lower()
    before = len(sessions)
    page.click("#create")
    assert "scenario" not in _sent(sessions, before)
    page.wait_for_function("document.querySelector('#sid').textContent === 's1'")  # connect() done: it clears the panel
    # The live panel: WebSocket "decision" messages, newest on top, level filter, short reason with the
    # full one on hover, latency, late mark.
    long_reason = "M3 termina antes que M5 por 40 u.t.; M5 tiene dos productos en cola y uno en camino desde M2"
    page.evaluate("""r => {
        handle({type: 'decision', tick: 300, product: 201, product_type: 'A', seq_op: 1, operation: 'O2', machine: 'M3',
                level: 'llm', reason: r, late: false, latency_ms: 812.4});
        handle({type: 'decision', tick: 340, product: 202, product_type: 'E', seq_op: 2, operation: 'O5', machine: 'M6',
                level: 'code-obvious', reason: 'única cercana', late: true, latency_ms: 95.0});
    }""", long_reason)
    rows = page.eval_on_selector_all("#dec-rows tr", "els => els.map(e => [...e.cells].map(c => c.textContent))")
    assert rows[0] == ["340", "p202 (E)", "O5", "M6", "code-obvious", "única cercana", "95 ms", "⚠ late"]
    assert rows[1][:5] == ["300", "p201 (A)", "O2", "M3", "llm"] and rows[1][6:] == ["812 ms", ""]
    assert rows[1][5].endswith("…") and len(rows[1][5]) == 60
    assert page.eval_on_selector("#dec-rows tr:nth-child(2) td.reason", "e => e.title") == long_reason
    page.select_option("#dec-level", "llm")
    assert page.eval_on_selector_all("#dec-rows tr", "els => els.length") == 1
    page.select_option("#dec-level", "")
    for k in range(60):  # at most 50 kept
        page.evaluate("k => handle({type: 'decision', tick: 400 + k, product: 210, machine: 'M2', level: 'llm', late: false})", k)
    assert page.eval_on_selector_all("#dec-rows tr", "els => els.length") == 50
    assert page.inner_text("#dec-rows tr:first-child td:first-child") == "459"
    page.close()


def test_run_decisions_paged_filtered_and_csv(server: tuple[str, list], browser: Any) -> None:
    url, _ = server
    page = browser.new_page(accept_downloads=True)
    page.goto(f"{url}/ui")
    _ready(page)
    page.click("#tab-runs")
    page.wait_for_function("document.querySelectorAll('#runs-rows tr').length === 5")
    page.click('#runs-rows tr:nth-child(1) [data-a="decisions"]')
    page.wait_for_function("document.querySelectorAll('#rd-rows tr').length === 50")
    assert "120 decisions" in page.inner_text("#rd-title") and "page 1 of 3" in page.inner_text("#rd-page")
    first = page.eval_on_selector("#rd-rows tr:first-child", "e => [...e.cells].map(c => c.textContent)")
    assert first == ["1290", "p200 (A)", "O8", "M7", "code-fallback", "obvia 119", "159 ms", "⚠ late"]  # newest on top
    page.click("#rd-next"); page.click("#rd-next")
    assert page.eval_on_selector_all("#rd-rows tr", "els => els.length") == 20
    assert page.is_disabled("#rd-next") and "page 3 of 3" in page.inner_text("#rd-page")
    page.select_option("#rd-level", "llm")  # 30 decisions: one page
    assert page.eval_on_selector_all("#rd-rows tr", "els => els.length") == 30 and "page 1 of 1" in page.inner_text("#rd-page")
    with page.expect_download() as info:
        page.click("#rd-csv")
    lines = Path(info.value.path()).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "tick,product,product_type,operation,machine,level,reason,latency_ms,late"
    assert len(lines) == 121 and lines[1] == "100,200,A,O1,M2,code-obvious,obvia 0,40,false"  # all of them, in order
    assert lines[2].startswith('110,201,I,O2,M3,llm,"razón larga, ')
    # An old run with a scenario still shows (rule cell), and Repetir sends no scenario.
    assert page.inner_text("#runs-rows tr:nth-child(5) td:nth-child(4)") == "Rule 3 [S2]"
    page.close()


def test_rule_4_is_the_agent_and_runs_show_the_strategy(server: tuple[str, list], browser: Any) -> None:
    url, sessions = server
    page = browser.new_page()
    page.goto(f"{url}/ui")
    _ready(page)
    # No strategy selector; rule 4 is "Rule 4 — AI agent" and always creates the session with agent.
    assert page.query_selector("#strategy") is None and page.query_selector("#strategy-box") is None
    assert page.eval_on_selector("#rule option[value='4']", "e => e.textContent") == "Rule 4 — AI agent"
    page.select_option("#rule", "4")
    before = len(sessions)
    page.click("#create")
    sent = _sent(sessions, before)
    assert (sent["rule"], sent["strategy"]) == (4, "agent")
    page.select_option("#rule", "3")
    before = len(sessions)
    page.click("#create")
    assert "strategy" not in _sent(sessions, before)
    # Runs: "Rule 4 (agent)", "(B1)", "(B1b)"; a none run (tests) is just "Rule 4".
    page.click("#tab-runs")
    page.wait_for_function("document.querySelectorAll('#runs-rows tr').length === 5")
    rules = page.eval_on_selector_all("#runs-rows tr td:nth-child(4)", "els => els.map(e => e.textContent)")
    assert rules == ["Rule 4 (agent)", "Rule 4 (B1)", "Rule 4 (B1b)", "Rule 4", "Rule 3 [S2]"]
    # The comparison uses the same names.
    for run_id in ("run-agent-0001", "run-b1-000001", "run-b1b-00001"):
        page.check(f'#runs-rows input[data-id="{run_id}"]')
    page.click("#runs-compare")
    heads = page.eval_on_selector_all("#runs-compare-box th", "els => els.map(e => e.textContent)")
    assert heads[1:] == ["Rule 4 (agent) run-ag", "Rule 4 (B1) run-b1", "Rule 4 (B1b) run-b1"]
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
    # The old S2 run is repeated on the original plant: no scenario in the body.
    page.click("#tab-runs")
    page.wait_for_function("document.querySelectorAll('#runs-rows tr').length === 5")
    before = len(sessions)
    page.click('#runs-rows tr:nth-child(5) [data-a="repeat"]')
    assert "scenario" not in _sent(sessions, before)
    page.close()


def test_layout_tooltip_errors_speed_and_set_limits(server: tuple[str, list], browser: Any) -> None:
    url, sessions = server
    page = browser.new_page()
    page.on("dialog", lambda d: d.accept())
    page.goto(f"{url}/ui")
    _ready(page)
    # Tabs in workflow order; the session-set selector says what it is.
    assert page.eval_on_selector_all("nav.tabs button", "els => els.map(e => e.id)") == ["tab-set", "tab-session", "tab-runs"]
    assert page.eval_on_selector("label:has(#session-set) > span", "e => e.textContent") == "Product set"
    # The seed tooltip says something and shows on keyboard focus.
    page.focus("button[aria-describedby=seed-tip]")
    assert page.eval_on_selector("#seed-tip", "e => getComputedStyle(e).visibility") == "visible"
    assert "seed" in page.inner_text("#seed-tip").lower() and len(page.inner_text("#seed-tip")) > 40
    # An error stays until an action succeeds: running without a session, then creating one.
    page.click("#live")
    page.wait_for_function("document.querySelector('#msg').className === 'err'")
    assert "Create a session first" in page.inner_text("#msg")
    before = len(sessions)
    page.click("#create")
    _sent(sessions, before)
    page.wait_for_function("!document.querySelector('#msg').textContent.includes('Create a session first')")
    # The live speed can be changed while the run goes on (POST /run with the new speed); a paused live
    # run resumes at the speed selected.
    RUN_CALLS.clear()
    page.evaluate("handle({type: 'run_state', run_state: 'running_live', mode: 'live', speed: 1, tick: 30})")
    page.select_option("#speed", "4")
    page.wait_for_function("document.querySelector('#runstate').textContent.includes('4')")
    assert RUN_CALLS == [{"mode": "live", "speed": 4}]
    page.evaluate("handle({type: 'run_state', run_state: 'paused', mode: 'live', speed: 4, tick: 40})")
    page.select_option("#speed", "0.5")
    assert len(RUN_CALLS) == 1  # paused: nothing sent until Resume
    page.click("#resume")
    page.wait_for_function("document.querySelector('#runstate').dataset.state === 'running_live'")
    assert RUN_CALLS[-1] == {"mode": "live", "speed": 0.5}
    # Order entry tab: download disabled while empty, at most 30 products, errors shown.
    page.click("#tab-set")
    assert page.is_disabled("#csv-download")
    for _ in range(30):  # one product per click
        page.click("#add")
    assert page.eval_on_selector_all("#set-rows tr", "els => els.length") == 30
    assert not page.is_disabled("#csv-download") and page.is_disabled("#add")
    page.click("#set-rows tr:nth-child(1) button[data-a=dup]")
    assert "At most 30" in page.inner_text("#set-errors")
    page.fill("#gen-count", "5")
    page.click("#generate")  # the fake platform has no /product-sets/generate: the error is shown
    page.wait_for_function("document.querySelector('#set-errors').textContent.includes('404')")
    page.click("#clear")
    assert page.is_disabled("#csv-download")
    # Products are told apart by type: one colour and letter per type, with a legend.
    assert page.eval_on_selector_all("#legend span", "els => els.length") == 9
    page.close()


CSV_ORDERS = ("Product Order (PO),Item ID,#,Type,Priority,DueDate\n"
              "PO-17,IT-3,1,A,70,1500\nPO-17,IT-3,2,e,,\nPO-18,IT-9,1,B,90,2200.5\n")


def test_order_csv_ids_priority_due_date(server: tuple[str, list], browser: Any, tmp_path: Path) -> None:
    url, sessions = server
    page = browser.new_page(accept_downloads=True)
    page.on("dialog", lambda d: d.accept())
    page.goto(f"{url}/ui")
    load_csv(page, tmp_path, CSV_ORDERS)
    cells = page.eval_on_selector_all("#set-rows tr", """els => els.map(tr => [
        ...[...tr.querySelectorAll('input[data-f]')].map(i => i.dataset.f + '=' + i.value),
        'type=' + tr.querySelector('select').value, 'id=' + tr.querySelector('td.pid').textContent])""")
    assert cells[0] == ["po=PO-17", "item_id=IT-3", "number=1", "priority=70", "due_date=1500", "type=A", "id=PO-17-IT-3-1"]
    assert cells[1] == ["po=PO-17", "item_id=IT-3", "number=2", "priority=80", "due_date=", "type=E", "id=PO-17-IT-3-2"]
    # Add numbers # on from the last one of that PO and item; a repeated id is marked.
    page.fill("#add-po", "PO-17"); page.fill("#add-item", "IT-3"); page.fill("#add-due", "900")
    page.click("#add"); page.click("#add")
    assert page.eval_on_selector_all("#set-rows td.pid", "els => els.map(e => e.textContent)")[3:] == ["PO-17-IT-3-3", "PO-17-IT-3-4"]
    page.fill("#set-rows tr:nth-child(4) input[data-f=number]", "1")
    page.press("#set-rows tr:nth-child(4) input[data-f=number]", "Enter")
    assert page.eval_on_selector_all("#set-rows tr.dup", "els => els.length") == 2 and "PO-17-IT-3-1" in page.inner_text("#set-errors")
    page.fill("#set-rows tr:nth-child(4) input[data-f=number]", "3")
    page.press("#set-rows tr:nth-child(4) input[data-f=number]", "Enter")
    assert page.eval_on_selector_all("#set-rows tr.dup", "els => els.length") == 0
    # The CSV download has the six columns; the session gets PO, Item ID, #, priority and due date.
    with page.expect_download() as info:
        page.click("#csv-download")
    lines = Path(info.value.path()).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "PO,Item ID,#,Type,Priority,DueDate" and lines[1] == "PO-17,IT-3,1,A,70,1500" and lines[2] == "PO-17,IT-3,2,E,80,"
    page.click("#tab-session")
    before = len(sessions)
    page.click("#create")
    sent = _sent(sessions, before)
    assert sent["products"][0] == {"type": "A", "priority": 70, "po": "PO-17", "item_id": "IT-3", "number": "1", "due_date": 1500}
    assert sent["products"][1] == {"type": "E", "priority": 80, "po": "PO-17", "item_id": "IT-3", "number": "2"}
    page.close()
