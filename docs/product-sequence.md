# Fixed product set and completed work

## What it is and why it exists

To compare routing strategies (rule 3, heuristic B1, LLM agent) they must all receive the
**same input products**: the same type, in the same order and with the same priority. In the
original model this does not happen: the type (`one-of PosibleProducts`) and the priority
(`random`) come from the global random generator, which gets out of step as soon as a strategy
decides differently (measured in A1 with `scripts/a1/measure_rng.py`: with seed 42, product 204
is already born with another type).

With the **fixed set**, product number `n` (the n-th created in the run) always has the same
type and the same priority for a given seed, whatever happens in the plant.

The way of measuring does not change (continuous mode: seed + ticks, the processed products are
counted) and neither does the arrival rule.

## How it is generated

- `n` = value of `products-created` when the product is created; the first one is `n = 1`.
- **Sub-seed of product n:**

  `sub_seed(n) = (product-sequence-seed × 1000003 + n) mod 2³¹`  (reporter `Product.Sequence.Seed n`)

  For the same sequence seed it is different for each `n < 2³¹` (it does not repeat between
  products) and it is always a valid NetLogo seed (0 … 2³¹−1), also with negative seeds. Two
  different seeds could only share a sub-seed with `n ≥ 1000003`, far above the maximum number
  of products of a run.
- Inside `with-local-randomness`: `random-seed sub_seed(n)`, then `one-of PosibleProducts`
  (type) and `random (100 - 60 + 1) + 60` (priority): the same draws, in the same order, as the
  original code (reporter `Product.Sequence.Item n` → `[type priority]`).
- The model's generator is neither used nor altered for type and priority.
- It is computed when needed (when the product is created): there is no array nor previous
  estimate, and it never runs out.

## The switch

| Where | Value |
|---|---|
| Model (`Setup`) | `fixed-product-sequence? = false`, `product-sequence-seed = 0`: the model creates products exactly like the original |
| `SimulationSession.setup(...)` | **on by default** (`fixed_product_sequence=True`) and `product-sequence-seed` = seed of the run. The platform, the workers, the API and the experiments always use it, without the user doing anything |
| `SimulationSession.setup(..., fixed_product_sequence=False)` | off: original model. Only for the regressions against the baseline: `validate_headless.py` (which feeds `compare_baseline.py`), `make_long_fixtures.py` / `test_long_regression.py`, `test_session.py::test_horizon_10000_matches_baseline`, `rule4_checks.py` (A1) and `scripts/a2/measure_arrivals.py` |

`SimulationSession.reset()` keeps the value; `import_world` reads it from the imported world
(`RunParameters.fixed_product_sequence`). NetLogo cannot read the seed of the run, which is why
Python sets `product-sequence-seed` after `setup` (also when the switch is off, so that
`platform-product-sequence` shows the sequence of that seed).

**A run with the fixed set is not equal to the baseline with the same seed.** The type and the
priority come from another generator and the model's generator stops consuming those two draws
per product, so from the first product everything else changes. Regressions against the baseline
must turn the switch off.

## Maximum number of products per run

The arrival rule creates at most one product per 100 units of simulated time:

`maximum = horizon × 0.31 / 100 + 1`  (≈ 311 with 100,000 ticks)

## Reads from Python

- `platform-state` includes `fixed_product_sequence`, `product_sequence_seed` and
  `products_created`.
- `platform-product-sequence [from to]` returns products `n = from..to` of the sequence of
  `product-sequence-seed`, computed with the same function as the creation:

  ```json
  [{"n": 1, "type": "I", "priority": 84}, {"n": 2, "type": "E", "priority": 64}]
  ```

  It consumes no randomness and can be called at any time (also half-way through a run).

## Completed work (KPI `work_completed`)

In `aclopi/sim/kpis.py`, next to the existing KPIs (which do not change). It is measured in
**units of nominal processing time**, not in number of operations:

- each finished operation adds its nominal time (`OperationDuration`: 200 for O1–O7, 100 for O8
  and O9 on M1);
- each operation still in progress at the end adds the fraction of its nominal already processed:
  `(Simulated.Time − start) / (Next.Completion − start) × nominal`, bounded to [0, 1];
- it counts every product created (finished and in progress).

The **nominal** time is used instead of the drawn one so that the random part of the processing
times neither rewards nor penalises a strategy: doing an operation is worth the same even if it
got a long time.

`created` is also added (products created = finished + in progress).

**Mean flow time (`mean_flow_time`), decision taken:** it is measured from the start of the
first operation (`first ProductRealStart`, when the product enters M1 for O8) to the last
completion (`last ProductRealCompletion`, end of O9), and only over finished products. It is
**not** measured from `ProductCreationTime` and it is kept that way on purpose: it is the
definition agreed in the headless validation and the one the baseline and the regressions use.
The difference with measuring it from creation is small and almost constant (~13.6 u.t., the trip
from the creation point to M1 in the measured runs; see `scripts/a2/measure_fixed_sequence.py`).

## What the fixed set does NOT equalise (accepted risk P9)

Only the type, order and priority of the products are equalised. These are **not** equalised
between strategies:
- the processing times drawn when entering a machine (`random-exponential`, the model's generator);
- the order in which products move (`ask` goes through agents in random order);
- the tick at which each product is created (it depends on the state of the plant: fewer than 10
  active products and a free entry zone).

It is an accepted risk (known problem P9): two strategies with the same seed see the same
products, but not the same processing times.

## Verification

- `tests/test_product_sequence.py`: switch, formula, same products with rules 1, 3 and 4 (random
  decider), same seed = same run, another seed = another set, `platform-product-sequence` matches
  what was created and does not alter the simulation, distribution of types over 1,000 products,
  completed work with a known state. 10,000-tick versions in the normal suite and 100,000-tick
  ones with `-m slow`.
- `python scripts/a1/measure_rng.py --products-only --sequence on --rules 1 3 4 --horizon 100000`.
