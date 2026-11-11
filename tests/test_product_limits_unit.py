"""Product lists on the platform: at most 30 products (API and CSV); the priority is optional; the CSV of
orders (PO, Item ID, #, Type, Priority, DueDate) and the product id PO-Item ID-#."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aclopi.api import Settings, create_app
from aclopi.api.models import MAX_PLATFORM_PRODUCTS, SessionCreate
from aclopi.api.models import ProductItem
from aclopi.api.product_sets import parse_csv, products_hash, to_csv


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


ORDERS = ("Product Order (PO);Item ID;#;Type;Priority;DueDate\n"
          "PO-1;IT-7;1;A;70;1500,5\nPO-1;IT-7;2;e;;\nPO-2;IT-9;1;B;90;20\n")


def test_orders_csv() -> None:
    products, errors = parse_csv(ORDERS.encode("utf-8-sig"))
    assert errors == []
    assert products == [{"po": "PO-1", "item_id": "IT-7", "number": "1", "type": "A", "priority": 70, "due_date": 1500.5},
                        {"po": "PO-1", "item_id": "IT-7", "number": "2", "type": "E", "priority": 80},
                        {"po": "PO-2", "item_id": "IT-9", "number": "1", "type": "B", "priority": 90, "due_date": 20.0}]
    assert [ProductItem(**p).id for p in products] == ["PO-1-IT-7-1", "PO-1-IT-7-2", "PO-2-IT-9-1"]
    # round trip through the export
    again, errors = parse_csv(to_csv(products).encode())
    assert errors == [] and again == products
    # the hash is the simulation's identity: PO, Item ID, # and due date do not change it
    assert products_hash(products) == products_hash([{"type": p["type"], "priority": p["priority"]} for p in products])


@pytest.mark.parametrize("text, message", [
    ("PO,Item ID,#,Type\nA1,I1,1,A\nA1,I1,1,B\n", "the id A1-I1-1 (PO-Item ID-#) repeats line 2"),
    ("PO,Item ID,#,Type,DueDate\nA1,I1,1,A,soon\n", "DueDate must be a number of u.t."),
    ("PO,Item ID,#,Type,DueDate\nA1,I1,1,A,-5\n", "DueDate must be 0 or more u.t."),
    ("PO,Item ID,#,Priority\nA1,I1,1,80\n", "missing column 'Type'"),
])
def test_orders_csv_errors(text: str, message: str) -> None:
    _, errors = parse_csv(text.encode())
    assert any(message in e["error"] for e in errors), errors


def test_product_id_and_repeated_ids(http: TestClient) -> None:
    item = ProductItem(po=" PO-1 ", item_id="IT", number=3, type="a", due_date=10)
    assert item.model_dump() == {"po": "PO-1", "item_id": "IT", "number": "3", "type": "A", "priority": 80,
                                 "due_date": 10.0, "id": "PO-1-IT-3"}
    assert ProductItem(type="B").model_dump() == {"type": "B", "priority": 80}  # no id without the three parts
    assert ProductItem(**item.model_dump()).id == "PO-1-IT-3"  # the stored id is accepted back (e.g. Repeat)
    twice = [{"po": "1", "item_id": "2", "number": "3", "type": "A"}] * 2
    r = http.post("/product-sets", json={"name": "x", "products": twice})
    assert r.status_code == 422 and "repeats product 1" in r.text
    assert http.post("/sessions", json={"rule": 3, "products": twice}).status_code == 422
    assert http.post("/product-sets", json={"name": "x", "products": [{"type": "A", "due_date": -1}]}).status_code == 422
