"""Decision flow of the agent with a fake platform and the fake LLM (no NetLogo, no network)."""

from __future__ import annotations

import asyncio
from typing import Any

from aclopi.agent.core import Agent, AgentConfig
from aclopi.agent.llm.fake import FakeLLM


def cands(finishes: dict[str, tuple[float, float]], current: str = "M2", own: float = 150.0) -> dict[str, Any]:
    cs = [{"machine": m, "finish": 1000 + f, "finish_plus_next": 1000 + n, "start": 1000 + f - 210}
          for m, (f, n) in finishes.items()]
    cs.sort(key=lambda c: c["finish"])
    return {"product": 200, "seq": 2, "operation": "O1", "tick": 3226, "time": 1000.0, "valid": True,
            "current_machine": current, "own_remaining": own, "gap_finish": None, "candidates": cs}


class FakePlatform:
    def __init__(self, candidates: dict[str, Any], what_if: dict[str, Any] | None = None) -> None:
        self.c, self.w, self.what_ifs = candidates, what_if, []

    async def candidates(self, sid: str, product: int, seq: int) -> dict[str, Any]:
        return self.c

    async def state(self, sid: str) -> dict[str, Any]:
        return {"time": 1000.0, "products": [{"id": 200, "type": "E", "operations": ["O8", "O1", "O1", "O1", "O9"]}],
                "machines": [{"name": "M1", "state": "Idle", "queue": []}]}

    async def what_if(self, sid: str, product: int, seq: int, options: list[str], budget_ms: int) -> dict[str, Any]:
        self.what_ifs.append((options, budget_ms))
        return self.w or {"status": "skipped", "skipped_reason": "no-free-worker", "options": []}


def request(mode: str = "fast", tps: float | None = None) -> dict[str, Any]:
    return {"session_id": "s1", "product": 200, "seq": 2, "strategy": "agent", "mode": mode, "ticks_per_second": tps, "tick": 3226}


def decide(platform: FakePlatform, llm: FakeLLM, req: dict[str, Any], config: AgentConfig = AgentConfig()) -> tuple[Any, dict]:
    return asyncio.run(Agent(platform, llm, config).decide(req))


OBVIOUS = {"M3": (300, 400), "M2": (600, 700)}
UNCERTAIN = {"M3": (300, 500), "M2": (400, 600)}
VERY_CLOSE = {"M3": (300, 500), "M2": (330, 450), "M5": (600, 700)}


def test_obvious_is_decided_by_code() -> None:
    llm = FakeLLM()
    d, rec = decide(FakePlatform(cands(OBVIOUS)), llm, request())
    assert (d.machine, d.decision_level) == ("M3", "code-obvious") and llm.calls == 0
    assert rec["estimated_finish"] == 1300 and rec["triage"] == "obvious"


def test_uncertain_goes_to_the_llm() -> None:
    llm = FakeLLM()
    d, rec = decide(FakePlatform(cands(UNCERTAIN)), llm, request())
    assert d.decision_level == "llm" and d.machine == "M3" and llm.calls == 1
    assert not rec["what_if_offered"] and len(rec["latencies"]["llm_ms"]) == 1


def test_very_close_with_what_if_fast() -> None:
    what_if = {"status": "ok", "options": [
        {"machine": "M3", "op_end_time": 1320.0, "others": {"work": 400, "wait": 50, "presence": 600, "finished": 0}},
        {"machine": "M2", "op_end_time": 1310.0, "others": {"work": 420, "wait": 40, "presence": 600, "finished": 0}}]}
    platform = FakePlatform(cands(VERY_CLOSE), what_if)
    llm = FakeLLM(what_if_rate=1.0)
    d, rec = decide(platform, llm, request())
    assert d.decision_level == "llm-what-if" and d.machine == "M2" and llm.calls == 2  # lowest op_end_time
    assert platform.what_ifs == [(["M3", "M2"], 15000)]  # code-chosen options, fast budget
    assert rec["what_if_requested"] and rec["what_if"]["status"] == "ok" and "what_if_ms" in rec["latencies"]


def test_what_if_skipped_still_decides() -> None:
    platform = FakePlatform(cands(VERY_CLOSE))  # what-if answers skipped
    d, rec = decide(platform, FakeLLM(what_if_rate=1.0), request())
    assert d.decision_level == "llm" and rec["what_if_reason"] == "no-free-worker"


def test_invalid_json_falls_back_to_best_by_finish() -> None:
    d, rec = decide(FakePlatform(cands(UNCERTAIN)), FakeLLM(invalid_rate=1.0), request())
    assert (d.machine, d.decision_level) == ("M3", "code-fallback") and rec["error"] == "llm-invalid-json"


def test_live_deadline_exhausted_sends_nothing() -> None:
    # own_remaining 150 u.t. at 1000 ticks/s -> ~0.5 s - 2 s margin: no time at all.
    d, rec = decide(FakePlatform(cands(UNCERTAIN)), FakeLLM(latency_s=0.3), request("live", 1000.0))
    assert d is None and "rule 3" in rec["error"]


def test_live_llm_timeout_with_time_left_is_a_fallback() -> None:
    # Deadline ~ 150 / 0.31 / 160 - 2 = 1.02 s; the LLM answers invalid JSON at once: time is left.
    d, _ = decide(FakePlatform(cands(UNCERTAIN)), FakeLLM(invalid_rate=1.0), request("live", 160.0))
    assert d is not None and d.decision_level == "code-fallback"


def test_live_no_what_if_from_m1_or_without_time() -> None:
    llm = FakeLLM(what_if_rate=1.0)
    # In M1: never offered, even if very close and with plenty of time.
    d, rec = decide(FakePlatform(cands(VERY_CLOSE, current="M1", own=100000)), llm, request("live", 32.0))
    assert not rec["what_if_offered"] and d.decision_level == "llm"
    # Not in M1 but only ~8 s left (< 5.5 + 3): not offered.
    d, rec = decide(FakePlatform(cands(VERY_CLOSE, own=0.31 * 32 * 10)), FakeLLM(what_if_rate=1.0), request("live", 32.0))
    assert not rec["what_if_offered"]
    # Plenty of time: offered, budget = min(15000, left - 3 s).
    platform = FakePlatform(cands(VERY_CLOSE, own=0.31 * 32 * 60))
    d, rec = decide(platform, FakeLLM(what_if_rate=1.0), request("live", 32.0))
    assert rec["what_if_offered"] and platform.what_ifs[0][1] == 15000


def test_at_most_two_llm_calls_and_invalid_candidates() -> None:
    llm = FakeLLM(what_if_rate=1.0)
    decide(FakePlatform(cands(VERY_CLOSE)), llm, request())
    assert llm.calls == 2
    bad = {"valid": False, "reason": "seq-mismatch", "candidates": [], "time": 1000.0}
    d, rec = decide(FakePlatform(bad), FakeLLM(), request())
    assert d is None and rec["error"].startswith("candidates-invalid")
