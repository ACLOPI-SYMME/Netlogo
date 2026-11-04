"""Deterministic fake LLM: configurable latency, rate of invalid JSON and rate of asking a what-if.

It picks the first machine allowed by the schema (the prompt lists candidates sorted by finish), or
the option with the lowest op_end_time when the prompt carries what-if results.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any

from aclopi.agent.llm.base import LLMClient, Messages


class FakeLLM(LLMClient):
    name = "fake"

    def __init__(self, latency_s: float = 0.0, invalid_rate: float = 0.0, what_if_rate: float = 0.0, seed: int = 0) -> None:
        self.latency_s, self.invalid_rate, self.what_if_rate = latency_s, invalid_rate, what_if_rate
        self._rng = random.Random(seed)
        self.calls = 0

    async def _complete(self, messages: Messages, schema: dict[str, Any], timeout_s: float) -> str:
        self.calls += 1
        draw_invalid, draw_what_if = self._rng.random(), self._rng.random()
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        if draw_invalid < self.invalid_rate:
            return '{"action": "decide", "machine": '  # truncated JSON
        props = schema.get("properties", {})
        machines = props.get("machine", {}).get("enum", [])
        actions = props.get("action", {}).get("enum", ["decide"])
        if "what_if" in actions and draw_what_if < self.what_if_rate:
            return json.dumps({"action": "what_if", "reason": "fake: too close to call"})
        prompt = messages[-1]["content"]
        ends = dict(re.findall(r"option (M\d): op_end_time ([\d.]+)", prompt))
        machine = min(ends, key=lambda m: float(ends[m])) if ends else (machines[0] if machines else "M1")
        return json.dumps({"action": "decide", "machine": machine, "reason": "fake decision"})
