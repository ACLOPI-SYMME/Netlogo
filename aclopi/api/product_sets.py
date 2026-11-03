"""Product sets (L5.6): named lists of products [{type, priority}] in entry order (docs/product-sets.md).

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

from aclopi.sim.session import MAX_PRODUCT_LIST, PRIORITY_MAX, PRIORITY_MIN, PRODUCT_TYPES

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
    """sha256 of the list in order ([[type, priority], ...]): the identity of a set's content."""
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

def parse_csv(data: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(products, errors). Columns type and priority (optional, default 80); separator , or ;;
    UTF-8 with or without BOM; type in any case. Errors: [{"line": n, "error": "..."}], where n is
    the line of the file (the header is line 1)."""
    errors: list[dict[str, Any]] = []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [{"line": 0, "error": "the file is not UTF-8"}]
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        return [], [{"line": 1, "error": "empty file: the first line must be the header (type, priority)"}]
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = [h.strip().lower() for h in next(reader)]
    if "type" not in header:
        return [], [{"line": 1, "error": f"missing column 'type' (header: {header})"}]
    ti, pi = header.index("type"), header.index("priority") if "priority" in header else None
    products: list[dict[str, Any]] = []
    for line_no, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue
        ptype = row[ti].strip().upper() if ti < len(row) else ""
        raw = row[pi].strip() if pi is not None and pi < len(row) else ""
        if ptype not in PRODUCT_TYPES:
            errors.append({"line": line_no, "error": f"type must be one of {', '.join(PRODUCT_TYPES)} (got {row[ti]!r})"
                           if ti < len(row) else "missing type"})
            continue
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
        products.append({"type": ptype, "priority": priority})
    if not errors and not products:
        errors.append({"line": 2, "error": "the list is empty"})
    if len(products) > MAX_PRODUCT_LIST:
        errors.append({"line": 0, "error": f"at most {MAX_PRODUCT_LIST} products (got {len(products)})"})
    return products, errors


def to_csv(products: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["type", "priority"])
    for p in products:
        writer.writerow([p["type"], int(p["priority"])])
    return out.getvalue()
