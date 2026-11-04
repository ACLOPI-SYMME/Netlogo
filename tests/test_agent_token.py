"""ACLOPI_AGENT_TOKEN: the platform and the mock agent compare the Bearer token in constant time
(secrets.compare_digest via aclopi.contracts.agent.bearer_matches), never with == / !=."""

from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from aclopi.agent_mock.app import MockConfig, create_mock_app
from aclopi.contracts import agent as contract

REPO = Path(__file__).resolve().parents[1]
TOKEN = "s3cret-token"


def test_bearer_matches() -> None:
    assert contract.bearer_matches(f"Bearer {TOKEN}", TOKEN)
    for wrong in (None, "", TOKEN, f"Bearer {TOKEN}x", f"bearer {TOKEN}", f"Bearer {TOKEN[:-1]}", "Bearer ñ"):
        assert not contract.bearer_matches(wrong, TOKEN), wrong


def test_bearer_matches_uses_compare_digest() -> None:
    with mock.patch.object(contract.secrets, "compare_digest", wraps=contract.secrets.compare_digest) as spy:
        assert contract.bearer_matches(f"Bearer {TOKEN}", TOKEN)
    spy.assert_called_once()


def test_no_plain_comparison_of_the_token() -> None:
    plain = re.compile(r"[!=]=\s*f?[\"']Bearer|Bearer \{[^}]*\}[\"']\s*[!=]=")
    for path in ("aclopi/api/app.py", "aclopi/agent_mock/app.py"):
        source = (REPO / path).read_text(encoding="utf-8")
        assert "bearer_matches(" in source, path
        assert not plain.search(source), path


def test_mock_agent_rejects_a_wrong_token() -> None:
    app = create_mock_app(MockConfig(platform_url="http://127.0.0.1:9", token=TOKEN))
    body = {"session_id": "s", "product": 200, "seq": 1, "strategy": "b1", "mode": "fast",
            "ticks_per_second": None, "tick": 10, "simulated_time": 3.1}
    with TestClient(app) as c:
        assert c.post("/decide", json=body).status_code == 401
        assert c.post("/decide", json=body, headers={"Authorization": "Bearer nope"}).status_code == 401
