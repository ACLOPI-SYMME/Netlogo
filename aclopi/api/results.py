"""Persistent results (L5.7): runs, their decisions and product sets. docs/deploy-local.md.

ResultsStore has two implementations:
- InMemoryResultsStore: tests and runs without a database;
- DynamoResultsStore: DynamoDB (boto3, region eu-west-3; ACLOPI_DYNAMODB_ENDPOINT points to
  DynamoDB Local). Tables are created at startup only with ACLOPI_CREATE_TABLES=1 (local); in the
  cloud the infrastructure creates them.

Tables (prefix ACLOPI_DYNAMODB_TABLE_PREFIX, default "aclopi_"):
  <prefix>runs         run_id                     one item per run (finished | failed | stopped)
  <prefix>decisions    run_id + seq (number)      the run's decisions, written in batch at the end
  <prefix>product_sets id                         product sets (replaces the in-memory store)

Saving never breaks a run: errors are logged and the run goes on.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from decimal import Decimal
from typing import Any, Protocol

from aclopi.api.product_sets import summary

logger = logging.getLogger(__name__)

REGION = "eu-west-3"
RUN_FILTERS = ("seed", "strategy", "rule", "product_set_id")


class ResultsStore(Protocol):
    def save_run(self, run: dict[str, Any], decisions: list[dict[str, Any]]) -> None: ...
    def get_run(self, run_id: str) -> dict[str, Any] | None: ...
    def list_runs(self, filters: dict[str, Any], limit: int, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]: ...
    def get_decisions(self, run_id: str) -> list[dict[str, Any]]: ...


def new_run_id() -> str:
    return uuid.uuid4().hex


def _matches(run: dict[str, Any], filters: dict[str, Any]) -> bool:
    return all(run.get(k) == v for k, v in filters.items() if v is not None)


class InMemoryResultsStore:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.decisions: dict[str, list[dict[str, Any]]] = {}

    def save_run(self, run: dict[str, Any], decisions: list[dict[str, Any]]) -> None:
        self.runs[run["run_id"]] = json.loads(json.dumps(run))
        self.decisions[run["run_id"]] = [dict(d, seq=i) for i, d in enumerate(decisions)]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.get(run_id)

    def list_runs(self, filters: dict[str, Any], limit: int, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        rows = sorted((r for r in self.runs.values() if _matches(r, filters)), key=lambda r: r["created_at"], reverse=True)
        start = int(cursor or 0)
        page = rows[start:start + limit]
        return page, str(start + limit) if start + limit < len(rows) else None

    def get_decisions(self, run_id: str) -> list[dict[str, Any]]:
        return list(self.decisions.get(run_id, []))


# ----- DynamoDB -----

def to_dynamo(value: Any) -> Any:
    """Numbers -> Decimal (boto3 refuses float); None is stored as DynamoDB NULL."""
    return json.loads(json.dumps(value), parse_float=Decimal, parse_int=Decimal)


def from_dynamo(value: Any) -> Any:
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


class _Dynamo:
    def __init__(self, endpoint: str | None, prefix: str, create_tables: bool) -> None:
        import boto3

        kwargs: dict[str, Any] = {"region_name": REGION}
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        self.resource = boto3.resource("dynamodb", **kwargs)
        self.prefix = prefix
        if create_tables:
            self.create_tables()

    def table(self, name: str) -> Any:
        return self.resource.Table(f"{self.prefix}{name}")

    def create_tables(self) -> None:
        specs = {
            "runs": ([("run_id", "HASH", "S")]),
            "decisions": ([("run_id", "HASH", "S"), ("seq", "RANGE", "N")]),
            "product_sets": ([("id", "HASH", "S")]),
        }
        existing = {t.name for t in self.resource.tables.all()}
        for name, keys in specs.items():
            full = f"{self.prefix}{name}"
            if full in existing:
                continue
            self.resource.create_table(
                TableName=full, BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": a, "KeyType": k} for a, k, _ in keys],
                AttributeDefinitions=[{"AttributeName": a, "AttributeType": t} for a, _, t in keys],
            ).wait_until_exists()
            logger.info("DynamoDB table %s created", full)


class DynamoResultsStore:
    def __init__(self, endpoint: str | None, prefix: str = "aclopi_", create_tables: bool = False) -> None:
        self.db = _Dynamo(endpoint, prefix, create_tables)
        self.runs = self.db.table("runs")
        self.decisions = self.db.table("decisions")

    def save_run(self, run: dict[str, Any], decisions: list[dict[str, Any]]) -> None:
        self.runs.put_item(Item=to_dynamo(run))
        with self.decisions.batch_writer() as batch:
            for i, d in enumerate(decisions):
                batch.put_item(Item=to_dynamo({**d, "run_id": run["run_id"], "seq": i}))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        item = self.runs.get_item(Key={"run_id": run_id}).get("Item")
        return from_dynamo(item) if item else None

    def list_runs(self, filters: dict[str, Any], limit: int, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        from boto3.dynamodb.conditions import Attr

        expression = None
        for key, value in filters.items():
            if value is None:
                continue
            cond = Attr(key).eq(to_dynamo(value))
            expression = cond if expression is None else expression & cond
        rows: list[dict[str, Any]] = []
        start_key = json.loads(base64.urlsafe_b64decode(cursor.encode())) if cursor else None
        while True:  # simple paging: a scan page per call, filtered (enough for the platform's volume)
            kwargs: dict[str, Any] = {"Limit": max(limit, 50)}
            if expression is not None:
                kwargs["FilterExpression"] = expression
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            page = self.runs.scan(**kwargs)
            rows += [from_dynamo(i) for i in page.get("Items", [])]
            start_key = page.get("LastEvaluatedKey")
            if len(rows) >= limit or not start_key:
                break
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        next_cursor = base64.urlsafe_b64encode(json.dumps(start_key).encode()).decode() if start_key else None
        return rows[:limit], next_cursor

    def get_decisions(self, run_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("run_id").eq(run_id)}
        while True:
            page = self.decisions.query(**kwargs)
            items += [from_dynamo(i) for i in page.get("Items", [])]
            if "LastEvaluatedKey" not in page:
                return sorted(items, key=lambda d: d["seq"])
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


class DynamoProductSetStore:
    """ProductSetStore on DynamoDB (same interface as InMemoryProductSetStore)."""

    def __init__(self, endpoint: str | None, prefix: str = "aclopi_", create_tables: bool = False) -> None:
        self.table = _Dynamo(endpoint, prefix, create_tables).table("product_sets")

    def _row(self, set_id: str, name: str, products: list[dict[str, Any]], created_at: float) -> dict[str, Any]:
        return {"id": set_id, "name": name, "products": [dict(p) for p in products], "created_at": created_at,
                "updated_at": time.time(), **summary(products)}

    def create(self, name: str, products: list[dict[str, Any]]) -> dict[str, Any]:
        row = self._row(uuid.uuid4().hex, name, products, time.time())
        self.table.put_item(Item=to_dynamo(row))
        return row

    def get(self, set_id: str) -> dict[str, Any] | None:
        item = self.table.get_item(Key={"id": set_id}).get("Item")
        return from_dynamo(item) if item else None

    def list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"ProjectionExpression": "id, #n, #t, counts, #h, created_at, updated_at",
                                  "ExpressionAttributeNames": {"#n": "name", "#t": "total", "#h": "hash"}}
        while True:
            page = self.table.scan(**kwargs)
            items += [from_dynamo(i) for i in page.get("Items", [])]
            if "LastEvaluatedKey" not in page:
                return sorted(items, key=lambda r: r["created_at"])
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def update(self, set_id: str, name: str, products: list[dict[str, Any]]) -> dict[str, Any] | None:
        found = self.get(set_id)
        if found is None:
            return None
        row = self._row(set_id, name, products, found["created_at"])
        self.table.put_item(Item=to_dynamo(row))
        return row

    def delete(self, set_id: str) -> bool:
        out = self.table.delete_item(Key={"id": set_id}, ReturnValues="ALL_OLD")
        return "Attributes" in out
