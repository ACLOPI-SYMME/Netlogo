"""Product lists on the platform: at most 30 products (API and CSV); the priority is optional."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aclopi.api import Settings, create_app
from aclopi.api.models import MAX_PLATFORM_PRODUCTS, SessionCreate
from aclopi.api.product_sets import parse_csv


@pytest.fixture()
def http(tmp_path: Path) -> Any:
    app = create_app(Settings(port=0, work_dir=tmp_path), pool_factory=lambda s: None, on_fatal=lambda e: None)
    return TestClient(app)  # no lifespan: validation answers before the platform is needed


def test_limit_is_30() -> None:
    assert MAX_PLATFORM_PRODUCTS == 30
    assert len(SessionCreate(rule=3, products=[{"type": "A"}] * 30).products) == 30
    with pytest.raises(ValueError):
        SessionCreate(rule=3, products=[{"type": "A"}] * 31)


def test_api_refuses_31_products(http: TestClient) -> None:
    assert http.post("/product-sets", json={"name": "x", "products": [{"type": "A"}] * 31}).status_code == 422
    assert http.post("/sessions", json={"rule": 3, "products": [{"type": "A"}] * 31}).status_code == 422
    assert http.post("/product-sets/generate", json={"count": 31}).status_code == 422
    r = http.post("/product-sets/parse-csv", files={"file": ("s.csv", "type\n" + "A\n" * 31, "text/csv")})
    assert r.status_code == 422 and any("at most 30" in e["error"] for e in r.json()["errors"])


def test_csv_without_priority() -> None:
    products, errors = parse_csv(b"type\nA\ne\n")
    assert errors == [] and products == [{"type": "A", "priority": 80}, {"type": "E", "priority": 80}]
