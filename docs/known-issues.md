# Known issues of the model

Problems found in `model/Paper.nlogo` that are **not fixed**, so as not to change the validated behaviour of the simulation (baseline in `tests/fixtures/baseline/`, rules 1–3, seed 42, Stochastic). The line numbers of items 1–3 refer to the branch `model/l2-platform-reporters`. Items 5 and 6 are problems of the platform, not of the model.

## 1. Column 18 of the Data CSV is always 0 (`"waiting"` in lower case)

- **Where:** `PrintData`, line 261:
  `sum [simulated.time - last productrealstart] of products with [Product.State != "death" and product.state = "waiting"]`.
- **Problem:** text comparisons in NetLogo are case-sensitive and the real state is `"Waiting"`. The filter never finds products, so column 18 is 0 in every row. This was checked on the three rules of the baseline.
- **Risk if fixed naively:** some products switch to `"Waiting"` at the sensors before entering their first machine, and at that moment `ProductRealStart` is still empty. With the filter fixed, `last productrealstart` would be evaluated on `[]` and the simulation would stop with a runtime error.
- **Possible fix (pending decision):** also filter `not empty? ProductRealStart`, or define what the column should measure for those products.

## 2. Product arrival: only 21 launch opportunities in 10,000 ticks

- **Where:** `Go`, line 134:
  `if (simulated.time mod 100 <= 0.2 and count products with [Product.State != "death"] < 10 and counter = 0) [create.product ...]`.
- **Problem:** `Simulated.Time` advances 0.31 per tick and is rounded to 2 decimals. The condition `mod 100 <= 0.2` holds only **21 times** in 10,000 ticks (at 100.13; 300.08; 500.03; …; 3100.0). On top of that, fewer than 10 live products and an empty entry zone are needed, so even fewer products are created.
- **Observed effect (seed 42, Stochastic):**

  | Rule | Finished products | Final WIP |
  |---|---|---|
  | 1 – Random Machine | 1 | 10 |
  | 2 – Nearest Machine | 2 | 10 |
  | 3 – Potential Fields | 5 | 6 |

  Throughput is very low with the three rules, and with rules 1 and 2 WIP stays at the cap of 10.
- **Pending:** confirm whether the intention was an arrival every 100 time units, for example with a timer instead of `mod`.

## 3. `ProductExitsMachine` writes `"XXX"` / `"YYY"` in the Events CSV

- **Where:** `EventMachineExit`, lines 196–197.
- **Problem:** in exit events, columns 6 (sequence order) and 7 (operation) of the CSV contain the fixed texts `"XXX"` and `"YYY"`. The CSV does not say which operation finished.
- **Mitigation in L2:** the platform's `event-buffer` (`platform-events`) records the operation that really finished (`item (CurrentSequenceOrder - 1) ProductOperations`). The CSV was not changed, so that it stays identical to the baseline.

## 4. ✅ FIXED (L4b, branch `model/l4b-p6-fix`). Slowdown in long runs (P6): quadratic cost in the finished products

- **Fix applied:** in `Product.Movement`, `product.ahead` (`count products in-cone 10 50`) is only computed inside `if (product.state = "Movement") [...]`. The `ask products` is not filtered, so the same agentset is shuffled in the same order.
- **Verification, on Windows and in the Linux container:**
  - `compare_baseline.py` with the 3 rules: identical to the baseline;
  - the 29 tests pass;
  - long regression (`pytest -m slow`): rule 3, 100,000 ticks, seeds 42 and 7, with KPIs and SHA-256 of Events and Data identical to `tests/fixtures/long/`, which were generated before the change;
  - at every checkpoint of the profile (every 5,000 ticks), the products and the rows of `EventFrameInfo` and `DataFrameInfo` are the same.
- **Result (container with the L4 limits, rule 3, seed 42):** the 100,000-tick run goes down from 104.2 s to 46.0 s (2.27× faster). With 83 finished products, the cost goes from 1.47 to 0.33 ms/tick. The cost per tick no longer grows with the finished products.

Original description of the problem:

- **Where:** `Product.Movement`, `ask products [ let product.ahead count products in-cone 10 50 ... if (product.state = "Movement" and product.ahead <= 1) [...] ]`.
- **Problem:** finished products are not removed; they all pile up at (2,2), with state `"death"`. On every tick, every product, finished or not, computes `count products in-cone 10 50` **before** checking its state. Among products piled up at the same point, each one counts all the others, so the cost grows with the square of the finished products.
- **Measurement (L4, Linux container, rule 3, seed 42, 100,000 ticks):** from 0.72–0.85 ms/tick between ticks 15,000 and 40,000 to 1.47 ms/tick at tick 100,000, with 83 finished products, all at (2,2). Leaving out the JVM warm-up, the fit `ms/tick = 0.755 + 1.21e-4 · death²` gives R² = 0.96; the linear one gives R² = 0.88. The other variables (total products, rows of `EventFrameInfo` and `DataFrameInfo`) grow at the same time and give similar fits; what points to the finished products is the mechanism, not the statistics.
- **Why the `ask` was not filtered:** with `ask products with [Product.State != "death"]` the size of the shuffled agentset would change and the equality with the baseline would **break**.

## 5. Platform: calls to NetLogo from Python threads other than the main one

- **Error (L4, Linux container):** any `report` made from a Python thread that is not the main one fails, even with a single thread:
  `java.lang.NullPointerException: Cannot invoke "java.lang.ClassLoader.loadClass(String)" because "this.normalClassLoader" is null` in `org.nlogo.generate.CustomClassLoader.loadClass`, while compiling the reporter.
- **Probable cause (not verified):** NetLogo's compiler loads the classes it generates with the thread's *context class loader*. The threads JPype attaches to the JVM have it set to `null`.
- **Consequence:** today each workspace is used from the main thread of its process. Organising by processes works; organising by threads does not.

## 6. Platform: line endings of the CSV files depend on the operating system

NetLogo writes the CSV files with the system's line separator: CRLF on Windows and LF on Linux. The baseline was generated on Windows. `compare_baseline.py` compares the SHA-256 of the content with line endings normalised to LF, so the regression holds on both platforms.

## 7. ✅ FIXED (P11, branch `model/p11-printdata`). `PrintData` failed with no live products

**What happened.** `PrintData`, which adds a row to the Data CSV every `Interval.Logs` u.t. (`Go`, line 173), computes means over the live products. With a product set that runs out (`docs/product-sets.md`) none may be left, and NetLogo fails with `Can't find the mean of a list with no numbers`. With the normal arrival of products it never happens, because there is always one alive.

**Affected computations**, all in `PrintData`:

| Line (before the change) | Computation | Data columns (from 0) |
|---|---|---|
| 281, 283 | `mean [xcor]` and `mean [ycor]` of the live products | 7 and 9 |
| 282, 284 | Standard deviation of x and y (`mean` inside `sqrt`) | 8 and 10 |
| 319 | Mean ratio of completed operations: sum ÷ `count` of the live products (division by 0) | Block 2, last column |
| 427–430 | The same means and deviations of block 5 (KPI) | The four corresponding columns of block 5 |

The rest already works with an empty set:
- sums and counts give 0;
- the entropy iterates an empty list;
- `EventPassing` is protected with `any?`;
- `PotentialFields` and the queues use empty lists;
- `ExportData` only writes.

In Python, `aclopi/sim/kpis.py` already returned `mean_flow_time = None` with no finished products (`ifelse-value any?`).

**Change.** Each of those values is `ifelse-value (any? products with [Product.State != "death"]) [original expression] [0]`. Those columns are **0** in the Data rows written when no product is alive, which only happens at the end of a run with a product set.

**Guarantee:** with live products the expression is the original one and `any?` uses no random numbers, so the baseline does not change (`compare_baseline.py` OK).

**Platform.** Sessions with a list still end at the exact `go` in which the last product finishes (`SimulationSession.step_product_list`, `run_reason: "all_products_done"`). It is no longer to avoid this error, but so that the run ends at the right tick. Test: `tests/test_product_list.py::test_p11_printdata_with_no_product_alive`.

## 8. Rule 3 gets stuck in S1 with seed 4 (not fixed before the delivery)

**What happens.** With rule 3 (Potential Fields), scenario S1 (heterogeneous machines) and seed 4, the plant gets stuck: product 221 is left waiting next to M6 and the run stops advancing in practice. Línea A found it.

**How it shows on the platform** (only relevant to experiments: scenarios are no longer available on the platform):
- **Live:** the plant looks frozen and no message appears.
- **Fast:** the run reaches the horizon without finishing the product list.

**Status.** Not fixed before the delivery. The reproducibility tests of the scenarios (`tests/test_scenarios_repro.py`) use seed 42 so as not to fall into this case.
