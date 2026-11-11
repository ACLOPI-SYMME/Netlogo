# Scenarios: platform side

> **Scenarios are not available on the platform** (decision of 9 November 2026). The platform simulates the original plant, only in Stochastic mode, without scenarios: no changed times, no degradation and no failures.
>
> - `POST /sessions` answers `422 scenarios_unavailable` ("scenarios are not available") to any scenario other than S0. `GET /scenarios` no longer exists.
> - The page has no scenario selector or notices. Runs saved earlier with a scenario are still shown (the rule carries `[S2]`, for example), and "Repeat" repeats them without the scenario.
> - The code is kept **only for Línea A's experiments**: `aclopi/sim/scenarios.py` and the worker mechanism (`ScenarioSchedule`, block cuts) remain in the repository, with their tests (`tests/test_scenarios_repro.py`, `tests/test_scenarios_model.py`, `tests/test_scenarios.py`). The API registry refuses to create a session with a scenario other than S0, so no platform session can turn one on.
>
> The rest of this document describes how it worked on the platform (historical: API, WebSocket and page) and how the mechanism still works inside the worker.

A scenario changes the plant during the run, from Python and without touching the model. They were meant to be the highlight of the demo: watching the agent react to a failure.

**Division of work.**
- **Línea A** writes the logic in `aclopi/sim/scenarios.py`: which scenarios exist, their parameters, the calendar of events and how each event is applied to the model.
- The **platform** decides when each event is applied, records it, streams it, stores it and shows it.
- Until Línea A delivered its version, the module was a stub with the same signatures. The stub **did not change the model**: every event came out applied, with `before`/`after` set to `null`.

## Interface the platform uses (`aclopi/sim/scenarios.py`)

| Function | What it does |
|---|---|
| `list_scenarios()` | List of `ScenarioSpec(id, name, description, params)`. `params` is a list of `ParamSpec(name, type, default, min, max, description)` |
| `validate_params(id, params)` | Returns the parameters with the defaults filled in. If something is invalid, it raises `ValueError` with the reason |
| `scenario_events(id, params, seed, start, end)` | Events `ScenarioEvent(tick, kind, machine, value, label)` of the range `[start, end)`, sorted by tick. It is pure and deterministic: S3 draws with Python's `random.Random(seed)`, not with the model's randomness, so the calendar is the same for every strategy |
| `apply_events(session, events)` | Applies the events with the model at their tick. Returns one `AppliedEvent(event, applied, skip_reason, before, after)` per event |

`kind` can be:
- `set_times` (S1);
- `scale_times` (S2);
- `repair` (S3).

The only skip reason is `skip_reason = "machine-idle"`: a failure on an idle machine. That condition is evaluated inside `apply_events`, at the moment it is applied.

Test-only variable: with `ACLOPI_SCENARIO_STUB_SKIP=1`, the stub returns the `repair` events as skipped.

### The scenarios

| Id | Name | Parameters (default, range) | Events |
|---|---|---|---|
| S0 | Base | — | none |
| S1 | Heterogeneous machines | `times`: M2 160, M3 180, M4 200, M5 220, M6 240, M7 260 (each 50–1000 u.t.) | One `set_times` at tick 0 per machine given |
| S2 | Degradation | `machine` M7 (M2–M7); `factor` 1.75 (1.0–5.0); `start_tick` 10,000 (0–1,000,000) | One `scale_times` at `start_tick` |
| S3 | Failures | `interval_ticks` 5000 (500–1,000,000); `repair_ut` 300 (10–2000); `machines` M2–M7 (at least one) | One failure at each multiple of `interval_ticks` (the first at `interval_ticks`), on a machine drawn from the list. Label (written by `scenarios.py`, in Spanish): "Falla en Mx: +N u.t." |

S1 details:
- Times can be given for only some machines: the others keep the time the model has.
- `times: {}` is valid and equivalent to S0.
- On the page (historical), an empty field meant "no change".

**What each event affects in the model:**
- `scale_times` (S2) and `set_times` (S1) only change the operations that **start after** the event. An operation in progress ends with its previous time.
- The only event that lengthens an operation in progress is **`repair` (S3)**.

## API (historical)

- **`GET /scenarios`:** returned `list_scenarios()`. The page built the form from that list.
- **`POST /sessions`:**
  - accepted `scenario: {id, params}`. Optional; S0 by default;
  - validated with `validate_params`. On a `ValueError`, it answered `422` with `code: "invalid_scenario"` and the message in `detail`, for example `"factor: must be between 1 and 5 (got 9)"`;
  - the validation happened before asking for a worker.
- **`SessionInfo`:** includes `scenario: {id, params}`, with the parameters filled in, and `scenario_summary: {applied, skipped}` of the current run.
- **`GET /runs?scenario=S3`:** filters runs by scenario (still available, useful only for old runs).

## Tick rule

**An event of tick T is applied when the model is at tick T, before advancing.** This holds in every case:

| Case | When it is applied |
|---|---|
| Setup | The events of tick 0 are applied after the model's `setup`, before the first advance |
| Reset | The events are recomputed with the same seed and come out identical. Those of tick 0 are applied again |
| Live | At the end of the block that reaches T |
| Fast | Same as live |
| Fast with decisions (`run-until-decision`) | Same as live |
| Manual step | During the step: it is split into pieces that stop at each event, the event is applied and it goes on until the n ticks are done |

**Block cuts.** No advance goes past the tick of an event: the size of the block is trimmed so that it stops exactly at T.
- **In fast mode**, the block stops at whatever comes first: the next event, the next decision or the end of the block.
- **In live mode**, a trimmed block is shorter. The next block is scheduled according to the ticks it really advanced, so the pace does not change.

The events are computed once, for `[0, horizon)`, at setup and at each reset. The worker keeps track of which ones it already applied.

## Order: event, decision and what-if snapshot

When a block ends at a tick T that has events, the order is:

1. The events of T are applied (`apply_events`).
2. The decision requests of the block (`pending_decisions`) and their context are read. In the API registry:
   - first each `scenario_event` is recorded and published;
   - then `POST /decide` is sent to the agent.

   If an event coincides with a pending decision, the agent decides with the plant already changed.
3. Only afterwards, between blocks, the worker serves other requests: candidates, the what-if snapshot, the state.

   That is why, if a what-if request arrives at a tick with events, the snapshot is taken **after** applying them.

## What-if without future events

What-if copies **do not apply scenario events**: the what-if worker clears the calendar when it imports the snapshot. The agent must not know the future.

What already happened (a changed time, a degradation, a repair in progress) is part of the state of the plant. The snapshot carries it and the copy respects it.

## What is streamed and stored (historical)

**Event log.** Each `AppliedEvent` was added to the session's event log (`recent_events` of the snapshot and the page's list) as an event of type `scenario`:

```json
{"type": "scenario", "tick": 5000, "kind": "repair", "machine": "M4", "value": 300.0,
 "label": "Falla en M4: +300 u.t.", "applied": true, "skip_reason": null, "before": null, "after": null}
```

**WebSocket.** A `scenario_event` message was sent for each applied or skipped event:

```json
{"type": "scenario_event", "seq": 812, "tick": 5000, "event": { ...the record above... }}
```

It was published before the `tick`/`progress` of the block ending at that tick. The events of tick 0 (setup and reset) did not produce a message: they arrived in the snapshot.

**Snapshot.** It carries `scenario: {id, params}` and `scenario_events`, with every event already happened in the run. A client connecting late could mark the affected machines.

**Saved run** (`GET /runs`, `GET /runs/{id}`):
- `scenario_id`;
- `scenario: {id, params}`;
- `scenario_events`: the full list;
- `scenario_summary: {applied, skipped}`.

## Page (`/ui`, historical)

**Session tab:**
- scenario selector, with its name and description;
- foldable "Scenario parameters" section, built from `ParamSpec` with the defaults filled in. Errors appeared next to each field; the server validated as well.

**Live view:**
- each event appeared as a notice for 5 s and stayed in the event list;
- on a failure, the machine flashed for 5 s;
- on a degradation or a changed time, the machine kept a frame and the value;
- a skipped event looked dimmed: "Falla saltada: M4 libre".

**Runs tab:**
- columns Scenario and Failures (applied / skipped), and a scenario filter;
- "Repeat" copied the scenario with its parameters;
- the comparison grouped by scenario (with parameters), seed and product set.
