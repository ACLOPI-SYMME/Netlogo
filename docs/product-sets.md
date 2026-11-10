# Product sets (L5.6)

The order and type of the products that enter the plant can come from a **user-defined list**, instead of the seed.

- **Each product** has the fields below. **Only `type` and `priority` reach the NetLogo model**; PO, Item ID, # and the due date are platform data: they are validated, stored with the set, the session and the run, and shown on the page.

| Field | CSV column | Meaning | Values |
|---|---|---|---|
| `po` | `PO` (also "Product Order (PO)") | Product Order | text, optional |
| `item_id` | `Item ID` | Item of the order | text, optional |
| `number` | `#` | Number of the product within that PO and item | text, optional |
| `id` | — (derived) | `PO-Item ID-#`, only when the three are given. Identifies the product; two products of a list cannot share it (422) | text, or missing |
| `type` | `Type` | Product type | A, I, P, B, E, L, T (required) |
| `priority` | `Priority` | Priority of the product | integer 60–100, 80 by default |
| `due_date` | `DueDate` | Due date, in simulated time units (u.t.) | number ≥ 0, optional |

- **The priority is not used today:** the model stores it on the product, but no rule (1–4) and not the agent use it to decide. What does matter is the **order** of the list, which is the order of entry into the plant.
- **The due date is not used today either:** it is stored and shown; it does not change the simulation nor the decisions.
- **Entry order:** the order of the list.
- **When each product enters:** the model still decides it as always: every 100 u.t., if there are fewer than 10 active products and the entry zone of M1 is free (procedure `Go`).
- **The seed** still controls all the rest of the randomness.

## Change in the model (branch `model/product-list`)

It is the only change. It reuses the creation path of Línea A's fixed set (`fixed-product-sequence?`, `docs/product-sequence.md`).

| What | Where (`model/Paper.nlogo`) |
|---|---|
| Globals `product-list?` (switch) and `product-list` (list of `[type priority]` set by Python) | lines 56–58 |
| `Setup`: `product-list? false` and `product-list []` | lines 140–141 |
| `Go`: with the switch on, product n takes the type of `item (n − 1) product-list`; if the list ran out, nothing is created. With the switch off, the code is the one from before (fixed set or `one-of PosibleProducts`) | lines 158–164 |
| `Create.product`: with the switch on, `priority` = `last item (n − 1) product-list` | line 542 |
| `platform-state`: `product_list_active`, `product_list_length` and `product_list_next` (= `products-created`, the 0-based index of the next product of the list) | lines 3115–3117 |

- **No random numbers consumed.** The list does not use the main generator for the type or the priority, like the fixed set.
- **"Generate from seed"** uses the reporter that already existed, `platform-product-sequence [from to]` (Línea A). `SimulationSession.product_sequence(seed, count)` changes `product-sequence-seed` only while reading and restores it afterwards; no new reporter was needed.

## Python

`SimulationSession.setup(..., product_list=[(type, priority), ...])`:
- validates the list with `validate_product_list`: 1 to 1000 products, valid type and integer priority from 60 to 100 (the API limits it to 30; the in-process session accepts up to 1000 for the experiments);
- sets it after `setup` and turns the switch on. The list takes precedence over the fixed set.

## Guarantees (tested)

| Guarantee | How it is tested | Result |
|---|---|---|
| With the switch off, the model is identical to the one from before | `compare_baseline.py` and `tests/test_product_sequence.py` | OK |
| The sequence of seed 42 loaded as a list gives exactly the same products (who, type, priority) and the same KPIs over 10,000 ticks as the fixed set of seed 42 | `tests/test_product_list.py::test_list_from_the_seed_equals_the_fixed_sequence` | OK |
| A list of 5 creates exactly those 5, in that order, and no others | `tests/test_product_list.py` | OK |

## End of the run and KPIs

- **End of a run with a list** (live and fast): the run ends when **every** product of the list has finished, with `run_reason: "all_products_done"` and `finished.reason` in the WebSocket, or when it reaches the horizon (`"horizon"`), whichever comes first.
- **Exact stop:** sessions with a list advance with `SimulationSession.step_product_list`, which stops at the exact `go` in which the last product finishes and never advances past it.
- **Why it is needed:** `PrintData` (in `Go`, line 173) computes means over the live products and failed when none was left (fixed since then: item 7 of `docs/known-issues.md`). The exact stop is kept so that the run ends at the right tick.

New KPIs (`aclopi/sim/kpis.py`, `GET /kpis`):

| KPI | Meaning |
|---|---|
| `products_total` | Length of the list (`null` without a list) |
| `all_done` | Every product of the list was created and finished |
| `makespan_time` | Last `ProductRealCompletion` of the finished products, from the start of the run (`null` unless all finished) |
| `makespan_ticks` | `makespan_time / 0.31`, rounded |

## API

| Route | What it does |
|---|---|
| `POST /product-sets`, `GET /product-sets`, `GET`/`PUT`/`DELETE /product-sets/{id}` | Sets with `name` and `products` `[{po, item_id, number, type, priority, due_date}]` in order, **1 to 30 products** (the size of Línea A's experiments). `type` accepts lower case; empty optional fields are left out of the stored product, and `id` is added when PO, Item ID and # are given |
| `POST /product-sets/parse-csv` (multipart, field `file`) | Turns a CSV into a validated list, without saving it. Columns `PO`, `Item ID`, `#`, `Type` (required), `Priority` (optional, 80) and `DueDate` (optional, u.t.); header names in any case; separator `,` or `;` (with `;`, the due date may use a decimal comma); UTF-8 with or without BOM. The old format `type,priority` is still accepted. With errors it answers 422 with `errors: [{line, error}]`, where `line` is the line of the file (the header is line 1); a repeated id is an error |
| `GET /product-sets/{id}/csv` | Exports the set (`PO,Item ID,#,Type,Priority,DueDate`) |
| `POST /product-sets/generate` `{seed?, count}` | The list the model generates with that seed (fixed set; a short operation on a borrowed what-if worker). Without `seed` one is drawn and returned |
| `POST /sessions` | Accepts `product_set_id` **or** `products` (inline). With neither, it behaves as before (set generated from the seed, "Random" on the page). The session keeps a **copy**: editing the set afterwards does not change it. `SessionInfo` includes `product_set_id`, `products_total` and `products_hash` (sha256 of the list) |

Storage: DynamoDB with `ACLOPI_DYNAMODB_ENDPOINT` (table `aclopi_product_sets`, L5.7), in memory otherwise (`InMemoryProductSetStore`). Each product is stored with its fields and its `id`.

**`products_hash`** is computed only from the type and the priority of each product, in order: it is the identity of the list **for the simulation**. Two lists with the same types and priorities but other PO, Item ID, # or due dates have the same hash, because the model runs them identically.

## Optional seed

- **Seed given:** in `POST /sessions`, `seed` is optional. If present, it must be an integer between −2147483648 and 2147483647; otherwise 422.
- **Seed missing:** the platform draws it with `secrets`, not with the model's randomness.
- **Record:** the seed used is **always** saved in `parameters.seed`, together with `seed_source` (`user` or `random`), so any run can be repeated.
- **Page `/ui`:**
  - "Set a seed" checkbox, unchecked by default, with a tooltip;
  - the field is required and validated when the checkbox is checked;
  - when the session is created it shows "Seed used: N" with a button to copy it;
  - "Generate from seed" (Order entry tab) follows the same pattern.
