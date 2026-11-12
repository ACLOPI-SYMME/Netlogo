# Simulation workers (`aclopi.workers`)

The base of the backend: the API (L5.2) only talks to the simulations through this package.

## Why processes

NetLogo only works from the main thread of a Python process (see `docs/known-issues.md`, item 5). That is why each simulation lives in its own worker process, with its own JVM (JPype loads the JVM inside the process, so there are no separate `java` processes). Inside the worker, `SimulationSession` is always used from its main thread. The process that manages the workers (the API) can use threads or asyncio, because NetLogo does not live in it.

Default configuration: 5 session workers + 2 what-if workers, each one with `-Xmx768m`.

## Modules

| Module | Content |
|---|---|
| `protocol.py` | Message format, operations, per-operation timeouts and exceptions |
| `worker.py` | Worker process: loading, warm-up and request loop |
| `handle.py` | `WorkerHandle`: requests and responses by id, safe with several threads |
| `pool.py` | `WorkerPool`: startup, session assignment, what-if lending, crashes and shutdown |
| `procinfo.py` | Memory and priority of each process (`psutil`) |

## Messages

Each worker has two `multiprocessing` queues (`spawn` context): the request queue and the output queue. Only simple data travels (`dict`, `list`, `str`, numbers, `bool`, `None`).

```python
{"id": 17, "op": "step", "args": {"n": 3}}                                                # request
{"type": "response", "id": 17, "ok": True, "result": {...}, "elapsed_ms": 4.1}              # response
{"type": "response", "id": 18, "ok": False, "error": {"type": "...", "message": "..."}, ...} # error
{"type": "push", "event": "ready", "data": {...}}                                            # with no previous request
```

Responses and `push` messages share the output queue, so they arrive in the order the worker produced them. In L5.1 the only `push` is `ready` (or `fatal` if the worker could not start); the live mode (L5.3) sends the state and the events through it.

Operations: `ping`, `setup`, `step`, `state`, `events`, `layout`, `kpis`, `reset`, `export_world`, `import_world`, `shutdown`.

**Optimize order** (`docs/optimize-order.md`):

- **`optimize_sim`** starts one `simulate_list` of a list in a given order and answers at once. The worker runs it in its loop with its priority lowered; the priority is restored at the end.
- **Between pieces** (≤ 1,000 ticks, about 1 s) the worker:
  - pushes `optimize_sim_progress` `{job_id, ticks, done, total}`;
  - answers `optimize_cancel`, `stop` and `ping`;
  - refuses every other request (`RunStateError`). A `shutdown` ends the job and then the worker.
- **At the end** it pushes `optimize_sim_done` `{job_id, result}` or `optimize_sim_error`.
- **Afterwards** the API sets the session up again.

## Rule: no request lasts more than a few seconds

A worker serves one request at a time. While it runs it cannot answer anything else, so the main process cannot tell "busy" from "hung". Therefore:

- **Each operation has its own timeout** (`OP_TIMEOUTS_S`; for `step`, `5 s + 5 ms per tick`).
- **If a request exceeds its timeout, the worker is considered hung:** the request fails with `WorkerTimeout`, the worker is killed and restarted, and its session is marked as lost (`SessionLost`).
- **`step` accepts at most `MAX_STEP_TICKS` (2000) ticks per request.** A larger value is rejected with a clear error.
- **Long runs (fast mode, L5.3) are made by the worker itself in blocks inside its loop**, reporting progress through the output queue as `push` messages. They are never made with a single long request.

L5.2 and L5.3 must respect this rule.

## Diagnostic operations (`command`, `report`)

They run arbitrary NetLogo code. They exist only for tests and diagnosis: the worker rejects them unless the pool was created with `debug=True`. **The API must never create a pool with `debug=True` nor expose these operations.**

## Crashes and errors

- **Error inside an operation** (for example, an invalid NetLogo command): it is returned as an error response (`WorkerError`) and the worker stays alive.
- **Failed `import_world`:** `import-world` clears the world before reading the file. If the import fails, the worker stays alive but without a simulation (`ping` returns `configured: false`) until a new `setup` or `import_world`. NetLogo in headless mode reports some corrupt files only on the console, without raising an exception; `SimulationSession.import_world` checks that the loaded world is valid.
- **Worker that dies or is killed:** a monitor thread waits on the processes' *sentinels* and detects it immediately. Pending requests fail with `WorkerCrashed`, the session goes to `lost_sessions()` and the worker is restarted with new queues (a queue can be left corrupt if its process dies while using it).
- **Main process that dies:** each worker checks in its loop that the parent process is still alive; if not, it closes its session and exits. No orphan processes are left.

## Priority

What-if workers lower their own priority when they start: `nice +10` on Linux and `BELOW_NORMAL_PRIORITY_CLASS` on Windows.

## What-if across processes

`export_world` on a session worker returns the path of the file, inside the pool's working folder (`<work_dir>/pool_<id>/worlds`); `import_world` on a what-if worker loads it and deletes it. `WorkerPool.whatif_from_session(session_id)` does both and lends the what-if worker. If none is free, it raises `NoFreeWorker` immediately: what-ifs are not queued.
