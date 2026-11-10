# Model events

[← Index and glossary](README.md)

## What it is

The "diary" of the products' movements: every time a product **enters** a machine, **leaves** one or **passes** certain rail nodes, the model writes a line. It is used to rebuild a product's route and to animate the plant on the page.

## How it is produced and when it is available

- The **NetLogo model** writes it, at the very moment each thing happens, in an internal list (the *event-buffer*).
- During a run, the platform empties that list at the end of **each block** and sends the events through the WebSocket (`events` of `tick` and `progress`). It also keeps the session's last 500 for the `snapshot`.
- Outside a run (session stopped or paused, or after a manual `step`): `GET /sessions/{id}/events` returns the events left in the list **since the last read** and empties it.
- Events are not saved with the run nor in DynamoDB.

## How to see it

| Where | What it brings |
|---|---|
| WebSocket, `tick` / `progress` messages | The new events of each block |
| WebSocket, `snapshot` → `recent_events` | The session's last 500 (since the last reset) |
| `GET /sessions/{id}/events` | Those not yet read. **Answers 409 while the session runs** |
| Page, Visualization tab, **Model events** panel | The last 200 |

## Fields (the 9 of the event-buffer)

| Field | Meaning | Unit | Values |
|---|---|---|---|
| `tick` | Tick of the event | ticks | — |
| `event` | What happened | — | `ProductEntersMachine` (enters a machine), `ProductExitsMachine` (leaves a machine), `PassingBy` (passes a control node) |
| `who` | Product | — | 200… |
| `product_type` | Product type | — | A, I, P, B, E, L, T |
| `location` | Where it happened | — | `M1`…`M7` on entries and exits; `Node <number>` on `PassingBy` |
| `operation` | On an entry or a pass: the operation it is going to do. On an exit: the operation **it has just finished** | — | O1…O9 |
| `next_operation` | The product's next pending operation, according to the model at that instant | — | O1…O9 |
| `destination` | Machine it is heading to | — | M1…M7 |
| `time` | Simulated time of the event | u.t. | — |

## Real example

The first four events of the fast run (they came in the WebSocket `progress` messages):

```json
[{"tick": 366, "event": "ProductEntersMachine", "who": 200, "product_type": "A", "location": "M1",
  "operation": "O8", "next_operation": "O8", "destination": "M1", "time": 113.77},
 {"tick": 690, "event": "ProductExitsMachine", "who": 200, "product_type": "A", "location": "M1",
  "operation": "O8", "next_operation": "O1", "destination": "M2", "time": 213.9},
 {"tick": 1007, "event": "PassingBy", "who": 200, "product_type": "A", "location": "Node 12",
  "operation": "O1", "next_operation": "O1", "destination": "M2", "time": 312.48},
 {"tick": 1011, "event": "ProductEntersMachine", "who": 201, "product_type": "E", "location": "M1",
  "operation": "O8", "next_operation": "O8", "destination": "M1", "time": 313.72}]
```

**Line-by-line reading of the second event:**
- `tick: 690`, `time: 213.9`: it happened at tick 690, at 213.9 u.t.
- `event: ProductExitsMachine`, `location: M1`: the product left M1.
- `who: 200`, `product_type: A`: it is product 200, of type A.
- `operation: O8`: it has just finished O8 (the entry operation, on M1). It entered at tick 366: it stayed 324 ticks, about 100 u.t., which is what O8 lasts.
- `next_operation: O1`, `destination: M2`: it will now do O1 on M2 (with rule 4, the agent had chosen the machine at tick 367).

## Useful calculations

- **Duration of an operation** = `time` of the exit − `time` of the entry of the same product on the same machine (u.t.).
- **Travel time between machines** = `time` of the entry to the next machine − `time` of the exit from the previous one.
- **Route of a product:** filter by `who` and sort by `tick`.
- **Number of events:** the fast run of the example had 104 (41 entries, 41 exits, 22 passes) for 5 products.

## Pitfalls

- **`GET /sessions/{id}/events` is not repeatable:** each call empties the list. And since during a run the platform already emptied it for the WebSocket, **after a run it usually comes back empty** (in the example, `[]`). To get every event of a run, listen to the WebSocket from the start.
- **`operation` changes meaning on exits:** it is the one that finished, not the next one.
- **Do not confuse it with the model's events CSV** (`Results/Events`), which has other columns and writes `"XXX"`/`"YYY"` on exits ([model-csv.md](model-csv.md)).
- **A reset session** starts its list of recent events again.
