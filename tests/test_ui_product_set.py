"""Set de productos tab (live.html) in a headless browser, without NetLogo.

A small FastAPI app serves the real page and the endpoints the tab uses: parse-csv with the real
parser (aclopi.api.product_sets.parse_csv), product-sets, health and POST /sessions (records the
body). Needs Playwright with Chromium or Edge (`pip install playwright`); skipped otherwise.
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
    def runs() -> list[Any]:
        return []

    @app.post("/sessions")
    async def create(request: Request) -> dict[str, Any]:
        sessions.append(await request.json())
        return {"session_id": "s1", "parameters": {"seed": 1}, "seed_source": "random", "warnings": []}

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
