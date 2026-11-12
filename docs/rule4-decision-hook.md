# Rule 4 – AI Agent: decision hook

Interface for Python to decide which machine each product goes to. Everything described here
exists in `model/Paper.nlogo` (sections "Rule 4 - AI Agent" and "Rule 4 decision hook") and in
`aclopi/sim/decisions.py`. There is no need to read the model's code to use it.

## Mechanism

1. With `Reactivity.rule = "Rule 4 - AI Agent"`, when a product **enters** a machine for the
   operation with index `k` (index in `ProductOperations`), the model adds a **request** to the
   global queue `decision-queue` for operation `k+1`.
2. Python reads the request and answers with `platform-set-next-machine` while the product is
   being processed (~645 ticks on M2–M7, ~323 on M1).
3. When the operation **finishes** (`Cheking.Machine.Completion`), the model assigns
   `Heading.Workstation`:
   - the machine chosen by Python, if there is an answer for that operation and the machine is
     still viable → `Decision.Source = "agent"`;
   - otherwise, rule 3 (Potential Fields) with the same code and the same consumption of random
     numbers → `Decision.Source = "rule3-fallback"` if the operation has several capable machines
     (there was no valid answer from the decider), or `Decision.Source = "single-option"` if only
     one machine can do it (there was nothing to decide; today, the step to O9).
   In every case the stored answer is cleared and a line is added to `decision-log`.
   The product is never left without a destination.

"Viable" today means "capable of the operation". The reporter `machine-available? [name]`
always returns `true`; it is the point where failure scenarios would plug in.

### When a request is created and when not

A request is created on entering a machine if and only if:
- the active rule is 4;
- operation `k+1` exists (the product is not on its last operation);
- operation `k+1` can be done by **more than one** machine.

Table of capable machines (`Set.operations`):

| Operation | Machines | Request? |
|---|---|---|
| O1 | M2 M3 M5 M7 | yes |
| O2 | M2 M3 M6 M7 | yes |
| O3 | M4 M5 M6 M7 | yes |
| O4 | M2 M4 M6 M7 | yes |
| O5 | M3 M4 M5 M7 | yes |
| O6 | M5 | no |
| O7 | M6 | no |
| O8 | M1 | no |
| O9 | M1 | no |

Consequences:
- The first operation (O8 on M1) is not decided: the product is born with destination M1.
- The step to O9 (M1, last operation) produces no request; rule 3 picks M1 and it is recorded as
  `single-option` (one per product). With a decider that answers in time, every assignment to
  an operation with several machines is `agent` and there is no `rule3-fallback`.
- If Python answers anyway for a single-machine operation (accepted, because the machine is
  capable), the assignment is recorded as `agent`.
- With rules 1–3 no request is created and nothing is written to the log.

## Product variables

| Variable | Default | Meaning |
|---|---|---|
| `AI.Next.Machine` | `""` | machine chosen by Python for the next operation |
| `AI.Decision.Seq` | `-1` | index in `ProductOperations` of the operation it was chosen for |
| `Decision.Source` | `""` | who made the last assignment: `"agent"`, `"rule3-fallback"` or `"single-option"` |

They appear in `platform-state` (each live product) as `ai_next_machine`, `ai_decision_seq` and
`decision_source`.

## NetLogo reporters and commands

All those returning structures return **JSON text**. None of them consumes the model's random
generator.

### `platform-run-until-decision [max-ticks]` (reporter)

Advances with `go` until the first of:
- there is at least one request in the queue;
- `max-ticks` ticks were advanced;
- the run ended (on reaching `horizon-ticks` it makes the extra call to `go` that runs
  `ExportData`, like `platform-step`).

Returns a NetLogo list of 4 numbers: `[ticks advanced finished n_requests]`, with
`finished` = 1 or 0.

**Important:** if there are already requests in the queue when it is called, it does not advance
(it returns `advanced = 0`). After reading the requests, call `platform-clear-decisions`.

Requests are created during a `go`; when the call returns with `n_requests > 0`, the product has
just entered the machine, so there is the whole processing time to answer.

### `platform-pending-decisions` (reporter, JSON)

Does not empty the queue.

```json
{
  "fields": ["who", "seq", "operation", "origin", "tick", "candidates"],
  "requests": [
    [200, 1, "O1", "M1", 366, ["M2", "M3", "M5", "M7"]]
  ]
}
```

- `who`: product id.
- `seq`: index in `ProductOperations` of the operation to decide (`k+1`).
- `operation`: name of that operation (`"O1"`..`"O9"`).
- `origin`: machine the product is in (the one doing operation `k`).
- `tick`: tick at which it entered the machine.
- `candidates`: machines capable of the operation (computed when reading, from the operations
  table; the internal queue only stores the first 5 fields).

### `platform-clear-decisions` (command)

Empties the request queue.

### `platform-set-next-machine [who machine seq]` (reporter)

Stores Python's choice. Arguments: `who` (number), `machine` (text, e.g. `"M3"`), `seq`
(number). Returns `"ok"` or the reason for the rejection. If it rejects, nothing changes.

Validations, in this order (the first reason that applies is returned):

| Reason | When |
|---|---|
| `rule4-not-active` | the active rule is not 4 |
| `invalid-arguments` | `who` or `seq` are not numbers, or `machine` is not text |
| `unknown-product` | no product with that `who` exists (includes ids of nodes, machines, etc.) |
| `product-finished` | the product has already finished (state `"death"`) |
| `invalid-seq` | `seq` < 0, `seq` ≥ number of operations of the product, or not an integer |
| `stale-seq` | `seq` ≤ `CurrentSequenceOrder`: the operation already started or already has a machine (old answer) |
| `not-in-machine` | the product is not being processed in a machine (it is on its way) |
| `seq-mismatch` | `seq` ≠ `CurrentSequenceOrder + 1` (it is not the pending operation) |
| `unknown-machine` | `machine` is not M1..M7 |
| `machine-not-capable` | the machine cannot do operation `seq` |

"In a machine" = the last operation started has not finished yet
(`length ProductRealStart > length ProductRealCompletion`). `Product.State` is not used, because
the model switches it between "Waiting" and "Movement" while the product is being processed.

An answer that arrives after the operation finished is rejected as `stale-seq` (the product
already advanced `CurrentSequenceOrder` to `seq`), or `product-finished` if it has finished.

It can be called several times for the same operation while the product is being processed;
the last accepted answer counts.

### `platform-decision-log` (reporter, JSON)

Every assignment made by rule 4 since the last clearing (with and without a request).

```json
{
  "fields": ["tick", "who", "seq", "operation", "origin", "chosen", "source"],
  "decisions": [
    [690, 200, 1, "O1", "M1", "M7", "agent"]
  ]
}
```

- `tick`: tick at which the previous operation finished and the machine was assigned.
- `seq`, `operation`: operation assigned.
- `origin`: machine that finished the previous operation.
- `chosen`: machine assigned (`Heading.Workstation`).
- `source`: `"agent"`, `"rule3-fallback"` or `"single-option"` (see Mechanism).

### `platform-clear-decision-log` (command)

Empties the log.

## Python: `aclopi/sim/decisions.py`

Every function takes a `SimulationSession` (with `setup(..., rule=4)`) and uses its lock.

| Function | Returns |
|---|---|
| `run_until_decision(session, max_ticks)` | `DecisionStepResult(ticks, advanced, finished, pending)` |
| `pending_decisions(session)` | `list[DecisionRequest(who, seq, operation, origin, tick, candidates)]` |
| `clear_decisions(session)` | `None` |
| `set_next_machine(session, who, machine, seq)` | `"ok"` or the reason |
| `decision_log(session, clear=False)` | `list[DecisionRecord(tick, who, seq, operation, origin, chosen, source)]` |
| `clear_decision_log(session)` | `None` |

`SimulationSession.setup` accepts `rule=4`. Typical loop ("fast mode": the answer is given in the
same tick the request is created):

```python
session.setup(seed=42, rule=4, horizon_ticks=100000)
while True:
    result = run_until_decision(session, max_ticks=100000)
    for request in pending_decisions(session):
        set_next_machine(session, request.who, choose(request), request.seq)
    clear_decisions(session)
    if result.finished:
        break
```

## Guarantees

- With rule 4 and **no answers** from Python, the simulation is identical to rule 3 with the
  same seed (KPIs, events CSV and data CSV except column 2, which is the name of the rule).
  Verified by `tests/test_decisions.py` (10,000 ticks; 100,000 with `-m slow`) and
  `scripts/rule4_checks.py`.
- Reading requests or the log, clearing them and calling `platform-set-next-machine` does not
  consume the model's random generator.
- With rule 4, `ExportData` writes `Data_100_Sto_R 4_0.csv` and `Event_100_Sto_R 4_0.csv`.
- The same seed does **not** guarantee the same conditions for every strategy once the agent
  chooses something different from rule 3: see the measurement in the report of task A1.
