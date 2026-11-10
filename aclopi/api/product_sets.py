"""Product sets (L5.6): named lists of products in entry order (docs/product-sets.md). A product has
PO, Item ID and # (together its id), type, priority and due date (u.t.); only type and priority reach the model.

ProductSetStore is the storage interface: InMemoryProductSetStore here; the DynamoDB
implementation comes with the results store (L5.7). CSV import/export and validation live here too.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import uuid
from typing import Any, Protocol

from aclopi.api.models import MAX_PLATFORM_PRODUCTS, product_id
from aclopi.sim.session import PRIORITY_MAX, PRIORITY_MIN, PRODUCT_TYPES

DEFAULT_PRIORITY = 80


class ProductSetStore(Protocol):
    def create(self, name: str, products: list[dict[str, Any]]) -> dict[str, Any]: ...
    def get(self, set_id: str) -> dict[str, Any] | None: ...
    def list(self) -> list[dict[str, Any]]: ...
    def update(self, set_id: str, name: str, products: list[dict[str, Any]]) -> dict[str, Any] | None: ...
    def delete(self, set_id: str) -> bool: ...


def summary(products: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {t: 0 for t in PRODUCT_TYPES}
    for p in products:
        counts[p["type"]] += 1
    return {"total": len(products), "counts": counts, "hash": products_hash(products)}


def products_hash(products: list[dict[str, Any]]) -> str:
    """sha256 of the list in order ([[type, priority], ...]): the identity of a set's content for the
    simulation. PO, Item ID, # and due date do not reach the model, so they do not change it."""
    canonical = json.dumps([[p["type"], int(p["priority"])] for p in products], separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class InMemoryProductSetStore:
    def __init__(self) -> None:
        self._sets: dict[str, dict[str, Any]] = {}

    def _row(self, set_id: str, name: str, products: list[dict[str, Any]], created_at: float) -> dict[str, Any]:
        return {"id": set_id, "name": name, "products": [dict(p) for p in products], "created_at": created_at,
                "updated_at": time.time(), **summary(products)}

    def create(self, name: str, products: list[dict[str, Any]]) -> dict[str, Any]:
        set_id = uuid.uuid4().hex
        self._sets[set_id] = self._row(set_id, name, products, time.time())
        return dict(self._sets[set_id])

    def get(self, set_id: str) -> dict[str, Any] | None:
        row = self._sets.get(set_id)
        return None if row is None else {**row, "products": [dict(p) for p in row["products"]]}

    def list(self) -> list[dict[str, Any]]:
        return [{k: v for k, v in row.items() if k != "products"}
                for row in sorted(self._sets.values(), key=lambda r: r["created_at"])]

    def update(self, set_id: str, name: str, products: list[dict[str, Any]]) -> dict[str, Any] | None:
        row = self._sets.get(set_id)
        if row is None:
            return None
        self._sets[set_id] = self._row(set_id, name, products, row["created_at"])
        return dict(self._sets[set_id])

    def delete(self, set_id: str) -> bool:
        return self._sets.pop(set_id, None) is not None


# ----- CSV -----

# CSV columns: the header names accepted for each field (case and spaces do not matter).
CSV_COLUMNS = {
    "po": ("po", "product order", "product order (po)", "product_order"),
    "item_id": ("item id", "item_id", "itemid", "item"),
    "number": ("#", "no", "no.", "number", "num"),
    "type": ("type",),
    "priority": ("priority",),
    "due_date": ("duedate", "due date", "due_date"),
}
CSV_HEADER = ["PO", "Item ID", "#", "Type", "Priority", "DueDate"]


def parse_csv(data: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(products, errors). Columns PO, Item ID, # (together the product's id), Type (required),
    Priority (optional, default 80) and DueDate (optional, u.t.); separator , or ;; UTF-8 with or
    without BOM; header names and type in any case. Errors: [{"line": n, "error": "..."}], where n is
    the line of the file (the header is line 1)."""
    errors: list[dict[str, Any]] = []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [{"line": 0, "error": "the file is not UTF-8"}]
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        return [], [{"line": 1, "error": f"empty file: the first line must be the header ({', '.join(CSV_HEADER)})"}]
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = [" ".join(h.strip().lower().split()) for h in next(reader)]
    index = {field: next((header.index(n) for n in names if n in header), None) for field, names in CSV_COLUMNS.items()}
    if index["type"] is None:
        return [], [{"line": 1, "error": f"missing column 'Type' (header: {header})"}]
    cell = lambda row, field: row[index[field]].strip() if index[field] is not None and index[field] < len(row) else ""  # noqa: E731
    products: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for line_no, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue
        ptype = cell(row, "type").upper()
        if ptype not in PRODUCT_TYPES:
            errors.append({"line": line_no, "error": f"type must be one of {', '.join(PRODUCT_TYPES)} (got {cell(row, 'type')!r})"
                           if cell(row, "type") else "missing type"})
            continue
        raw = cell(row, "priority")
        if raw == "":
            priority = DEFAULT_PRIORITY
        else:
            try:
                priority = int(raw)
            except ValueError:
                errors.append({"line": line_no, "error": f"priority must be an integer (got {raw!r})"})
                continue
            if not PRIORITY_MIN <= priority <= PRIORITY_MAX:
                errors.append({"line": line_no, "error": f"priority must be {PRIORITY_MIN}-{PRIORITY_MAX} (got {priority})"})
                continue
        product: dict[str, Any] = {}
        for field in ("po", "item_id", "number"):
            if cell(row, field):
                product[field] = cell(row, field)
        product.update(type=ptype, priority=priority)
        raw_due = cell(row, "due_date")
        if raw_due:
            try:
                due = float(raw_due.replace(",", ".") if delimiter == ";" else raw_due)
            except ValueError:
                errors.append({"line": line_no, "error": f"DueDate must be a number of u.t. (got {raw_due!r})"})
                continue
            if due < 0 or due != due:
                errors.append({"line": line_no, "error": f"DueDate must be 0 or more u.t. (got {raw_due!r})"})
                continue
            product["due_date"] = due
        pid = product_id(product.get("po"), product.get("item_id"), product.get("number"))
        if pid is not None:
            if pid in seen:
                errors.append({"line": line_no, "error": f"the id {pid} (PO-Item ID-#) repeats line {seen[pid]}"})
                continue
            seen[pid] = line_no
        products.append(product)
    if not errors and not products:
        errors.append({"line": 2, "error": "the list is empty"})
    if len(products) > MAX_PLATFORM_PRODUCTS:
        errors.append({"line": 0, "error": f"at most {MAX_PLATFORM_PRODUCTS} products (got {len(products)})"})
    return products, errors


def to_csv(products: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for p in products:
        due = p.get("due_date")
        writer.writerow([p.get("po") or "", p.get("item_id") or "", p.get("number") or "", p["type"], int(p["priority"]),
                         "" if due is None else f"{float(due):g}"])
    return out.getvalue()
