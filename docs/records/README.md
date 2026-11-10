# Platform records

This folder explains **every piece of data the platform produces**: what it is, when it appears, where to see it, what each field means and how to read it without mistakes. It is written for readers who know neither the code nor the NetLogo model.

The examples are **real**. They come from a single run of the platform on 9 November 2026, with the mock agent (`aclopi.agent_mock`):
- a fast run with rule 4 and a list of 5 products;
- a live run of about 20 s at 1× speed;
- a candidates query and a what-if in that session.

The full responses were saved in `results/docs_examples/`, which is not in git. The documents show excerpts.

## Index

| File | Source | Where to see it |
|---|---|---|
| [runs.md](runs.md) | Saved runs | `GET /runs`, `GET /runs/{id}`, table `aclopi_runs`, **History Logs** tab, CSV of a run |
| [decisions.md](decisions.md) | Agent decisions | `GET /runs/{id}/decisions`, table `aclopi_decisions`, "Latest decisions" panel, "Decisions" button, decisions CSV, the agent's own log (`decisions.jsonl`) |
| [metrics.md](metrics.md) | Session metrics | `GET /sessions/{id}/metrics` (groups `decisions` and `whatif`) |
| [kpis.md](kpis.md) | Plant indicators | `GET /sessions/{id}/kpis`, `kpis` of runs and of WebSocket messages |
| [events.md](events.md) | Model events | `GET /sessions/{id}/events`, `events` of WebSocket messages |
| [websocket.md](websocket.md) | Real-time messages | `ws://…/ws/sessions/{id}` (every type) |
| [candidates-and-whatif.md](candidates-and-whatif.md) | Candidates and what-if responses | `GET /sessions/{id}/candidates`, `POST /sessions/{id}/what-if`, diagnostic files |
| [sessions-and-state.md](sessions-and-state.md) | The session and the plant snapshot | `GET /sessions`, `GET /sessions/{id}`, `/state`, `/layout` |
| [product-sets.md](product-sets.md) | Saved product lists | `/product-sets`, table `aclopi_product_sets`, CSV of a set |
| [health.md](health.md) | Platform status | `/health`, `/health/ready`, `/health/live` |
| [logs.md](logs.md) | Process logs | `docker compose logs`, one JSON line per message |
| [model-csv.md](model-csv.md) | CSV written by the model itself | `Results/Data` and `Results/Events` |
| [scenarios.md](scenarios.md) | Scenario fields | Only in old runs |

For the design of each part, see also `docs/api.md`, `docs/websocket.md`, `docs/agent-api.md` and `docs/whatif.md`. This folder explains how to **read** the data; those documents explain how each part **works**.

## The page (`/ui`)

| Tab | What it is for |
|---|---|
| **Order entry** | Build the list of products (type and order, at most 30), generate it from a seed, upload or download it as CSV, save it |
| **Visualization** | Create a session, run it live or fast, watch the plant, the indicators, the agent's decisions and the model events |
| **History Logs** | Saved runs: filter, compare, see their decisions, repeat them, download them as CSV |

## Glossary

The terms below are used in every file without being explained again.

**The plant and the model**

| Term | What it is |
|---|---|
| Model | The digital twin of the plant, written in NetLogo (`model/Paper.nlogo`). The platform runs it without a window and reads its data |
| Plant | A monorail with 7 machines (M1–M7), 94 nodes and 19 gates. Products travel along the rail from machine to machine |
| Product | A part that enters the plant, does a list of operations and leaves. There are 7 types: A, I, P, B, E, L and T. Each type has its own list of operations |
| `who` / `product` | The number that identifies a product inside the model. Products are numbered from 200 upwards (200, 201, …), because the lower numbers belong to nodes, machines and sensors |
| Operation | One work step: O1 to O9. O8 and O9 are only done on M1 (when entering and when leaving the plant); O1 to O7 are done on M2–M7, and each one can be done by several machines |
| `seq` / `seq_op` | The position of an operation in the product's list of operations, counting from 0. Careful: depending on the source, the same number is called `seq` or `seq_op` (see [decisions.md](decisions.md)) |
| `priority` | A number from 60 to 100 stored on each product. No rule and not the agent use it; the page does not show it |
| Finished product | One that did all its operations. In the model it ends with state `"death"` |
| WIP | *Work in process*: products in the plant that have not finished yet |

**Time**

| Term | What it is |
|---|---|
| Tick | One step of the simulation. The model advances one tick at a time |
| u.t. | Unit of simulated time (the code, the API and the page write "u.t."). **1 tick = 0.31 u.t.** Simulated time is called `Simulated.Time` in the model and `time` or `simulated_time` in the platform |
| Duration of operations | O8 and O9 (on M1): 100 u.t., about 323 ticks. O1–O7 (M2–M7): 200 u.t., about 645 ticks, plus a random extra of 10 u.t. on average (Stochastic mode) |
| Horizon | The tick at which a run ends (`horizon_ticks`, 10,000 by default) |
| Unix time | Real time in seconds since 1 January 1970 (UTC). Example: `1794220312.47` is 9 November 2026, 10:31:52 UTC. Used in `created_at`, `finished_at`, etc. |
| ms | Milliseconds of **real** time, not simulated |

**The platform**

| Term | What it is |
|---|---|
| Session | A copy of the model loaded in a process (a *worker*), ready to run. Created with `POST /sessions` and identified by `session_id` |
| Run | One execution of the session from tick 0 until it ends, fails or is stopped. When it ends it is saved as a record with a `run_id` |
| Live mode (`live`) | The run advances at a fixed pace to be watched: 32 ticks per second at 1× speed (64 at 2×, 128 at 4×, 16 at 0.5×). The speed can be changed while it runs |
| Fast mode (`fast`) | The run advances as fast as possible. With rule 4 it stops at each decision to wait for the agent |
| Worker | A process with a NetLogo model loaded. There are session workers (one per session) and what-if workers (for the copies) |
| Seed (`seed`) | The number that fixes the randomness of the simulation. With the same seed, the same options and the same product list, the run comes out the same |
| Product set | A fixed list of products that enter the plant in that order. Without a set, products are generated from the seed (shown as "Random" on the page) |
| Stochastic mode | The only one the platform uses: operations on M2–M7 last their time plus a random extra |

**The rules and the agent**

| Term | What it is |
|---|---|
| Rule | How the machine a product goes to is chosen when it finishes an operation. 1: random machine; 2: nearest; 3: potential fields; 4: the AI agent |
| Agent | The service that decides with rule 4. It first applies code; if the case is not obvious, it asks an LLM, and it may request a what-if. For the user, rule 4 **is** the agent |
| LLM | Large language model (for example, Claude) that the agent consults in doubtful cases |
| Mock agent | `aclopi.agent_mock`: a stand-in for the agent used in tests. It draws the levels at random and always picks the machine that finishes first. Its reasons start with "mock" |
| Decision | The agent's answer: which machine the product goes to for its next operation |
| Level (`decision_level`) | Who decided inside the agent: `code-obvious`, `llm`, `llm-what-if`, `code-fallback` or `heuristic` (see [decisions.md](decisions.md)) |
| Candidates | The computation of the possible machines for an operation, with when the product would arrive, start and finish on each |
| What-if | "What would happen if…?": the platform copies the plant as it is, simulates the two options (machine A and machine B) separately and compares |
| Latency | How long something took in real time (ms). For a decision: from the moment the platform asked for it until it arrived |
| Late (`late`) | A decision that arrived when the product had already moved on. It is not applied: rule 3 decided instead |

**Statistics**

| Term | What it is |
|---|---|
| `mean` | Average |
| `p95` | 95th percentile: 95 % of the values are below this number |
| `max` | Maximum |
| `n` | How many values went into the computation |
