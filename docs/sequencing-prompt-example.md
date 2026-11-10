# Ejemplo de prompt de `/sequence/propose` (ronda 1)

Es el prompt exacto que recibió el LLM (strata) en la ronda 1 de `scripts/a4/sequence_rounds.py`:

- lista de 20 productos en el orden `AAAAAAAABBBBBBIIIEEE`;
- b1b, Deterministic, semilla 42;
- `evaluated` = el orden original y la heurística (ronda 0).

Además del texto, el pedido lleva:

- `response_format` con el esquema JSON (`analysis` + 2 `orders`);
- `reasoning_effort: "medium"`;
- `max_tokens` 8120;
- `temperature` 0.

La clave del LLM va solo en la cabecera HTTP y no aparece aquí.

Respuesta de esa ronda: 26.1 s; `analysis`:

> Best order (26612) puts I/E last: index 16 enters tick 21936, finishes 26612. M1 idle 13692 ticks (48.5% occ). 26 missed zone checks. Tail gaps [22303-23225],[23905-24556],[24879-26289] show M1 waiting for late O9. Short I (4093 ticks) and E (5848 ticks) waste time entering at 18710-21936. Lower bo…

## Mensaje `system`

```text
You plan the ENTRY ORDER of a list of products into a simulated monorail plant, to finish the
WHOLE list as early as possible (minimum makespan). Every order you propose is simulated and you get
the results back; use them.

PLANT (read from the simulation model; times in simulated time units, u.t.; 1 tick = 0.31 u.t.)
- Machines, operations they can do and processing time (Machine.Operations.Time, u.t.):
  M1: O8 100, O9 100
  M2: O1 200, O2 200, O4 200
  M3: O1 200, O2 200, O5 200
  M4: O3 200, O4 200, O5 200
  M5: O1 200, O3 200, O5 200, O6 200
  M6: O2 200, O3 200, O4 200, O6 200
  M7: O1 200, O2 200, O3 200, O4 200, O5 200
- M1 loads and unloads: EVERY product starts with O8 and ends with O9 on M1, so M1 is shared by all.
- Mode Deterministic: processing times are exactly the ones above (no random extra; in Stochastic mode M2, M3, M4, M5, M6, M7 add an exponential extra of mean 10 u.t.).
- Travel time between machines (u.t., row = from, column = to; 0 = staying on the same machine,
  which also skips that machine's queue):
          M1     M2     M3     M4     M5     M6     M7
   M1      0  111.3  201.8  186.6  125.5  212.1  298.4
   M2  287.9      0  124.6  109.4  187.2  273.7  360.8
   M3  247.4  161.8      0  69.13  146.9  233.4  320.2
   M4  212.3  126.8  217.3      0  111.9  198.4  285.2
   M5  129.6  211.7  302.2  187.6      0  115.6  202.2
   M6  208.1  290.1  380.7  365.5  304.4      0  121.2
   M7  120.9  203.1  293.5  278.4  217.3  139.5      0

ENTRY RULE
- Products enter in list order. The model checks the entry when the simulated time is within
  0.2 u.t. after a multiple of 100 u.t. (time advances 0.31 u.t. per tick, so some
  100 u.t. windows get no check). A new product enters only if there are fewer than 10 products
  in the plant AND no product is in the entry zone next to M1 (x 90-115, y 80-110 of the
  plant layout). A missed check waits for the next one.
- A new product needs 13.64 u.t. to reach M1.

ROUTING (b1b): each operation goes to the capable machine with the lowest finish_plus_next = estimated end of the operation there (travel, queue and products on their way included) + travel to the closest machine of the following operation; ties: lowest machine number. Staying on the same machine costs no travel.

ANSWER: only the JSON object requested.
- "analysis": at most 300 characters, why the best evaluated order loses time, with the
  numbers of its details (idle time of M1, missed entry checks, last product, occupancy, lower bound).
- "orders": 2 NEW orders that correct that, different from every evaluated order. Each "order" lists
  every index of the list exactly once. Each "reasoning": at most 300 characters, what you changed
  and why it should finish earlier. Write in English.
```

## Mensaje `user`

```text
LIST: 20 products (8 A, 3 I, 6 B, 3 E). Index: type, in the current order:
0:A 1:A 2:A 3:A 4:A 5:A 6:A 7:A 8:B 9:B 10:B 11:B 12:B 13:B 14:I 15:I 16:I 17:E 18:E 19:E

PRODUCT TYPES IN THE LIST (min_time = from creation to the end of O9 with no waiting: entry travel + processing + travel on the best route)
- A x8: O8[M1] O1[M2/M3/M5/M7] O1[M2/M3/M5/M7] O1[M2/M3/M5/M7] O2[M2/M3/M6/M7] O4[M2/M4/M6/M7] O3[M4/M5/M6/M7] O5[M3/M4/M5/M7] O9[M1]; work 1600 u.t.; min_time 2032.94 u.t. (6558 ticks) via M1-M7-M7-M7-M7-M7-M7-M7-M1
- B x6: O8[M1] O1[M2/M3/M5/M7] O1[M2/M3/M5/M7] O1[M2/M3/M5/M7] O2[M2/M3/M6/M7] O2[M2/M3/M6/M7] O3[M4/M5/M6/M7] O5[M3/M4/M5/M7] O9[M1]; work 1600 u.t.; min_time 2032.94 u.t. (6558 ticks) via M1-M7-M7-M7-M7-M7-M7-M7-M1
- I x3: O8[M1] O1[M2/M3/M5/M7] O1[M2/M3/M5/M7] O3[M4/M5/M6/M7] O5[M3/M4/M5/M7] O9[M1]; work 1000 u.t.; min_time 1268.74 u.t. (4093 ticks) via M1-M5-M5-M5-M5-M1
- E x3: O8[M1] O1[M2/M3/M5/M7] O1[M2/M3/M5/M7] O1[M2/M3/M5/M7] O2[M2/M3/M6/M7] O2[M2/M3/M6/M7] O4[M2/M4/M6/M7] O9[M1]; work 1400 u.t.; min_time 1812.84 u.t. (5848 ticks) via M1-M2-M2-M2-M2-M2-M2-M1

FIGURES OF THE LIST (u.t.)
- Work per operation: O1 11400, O2 5200, O3 3400, O4 2200, O5 3400, O8 2000, O9 2000
- Work each machine could take (sum of the operations it can do): M1 4000, M2 18800, M3 20000, M4 9000, M5 18200, M6 10800, M7 25600
- M1 load (O8 + O9 of all): 4000 u.t.
- Earliest entries (one per entry check, if nothing blocks): first 100.13, last 3000.18 u.t.
- Lower bound of the makespan in the current order: 15526 ticks (4813.02 u.t.) = max(M1 bound 4113.77: first arrival + M1 load; path bound 4813.02: earliest entry + min_time, worst for index 19)

EVALUATED ORDERS (simulated; makespan in ticks; idle = ticks without processing; missed = entry checks missed because the zone was occupied / the plant was full)
0. AAAAAAAABBBBBBIIIEEE order [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]: makespan 27745; last: index 19 (E, position 19); M1 idle 14825; missed zone 25 / full 0 of 45 checks; occupancy M1 46.6% M2 69.9% M3 46.6% M4 48.9% M5 53.6% M6 41.9% M7 37.3%
1. ABABABABABABAAEEEIII order [0, 8, 1, 9, 2, 10, 3, 11, 4, 12, 5, 13, 6, 7, 17, 18, 19, 14, 15, 16]: makespan 26612; last: index 16 (I, position 19); M1 idle 13692; missed zone 26 / full 0 of 46 checks; occupancy M1 48.5% M2 68% M3 55.8% M4 53.4% M5 51% M6 43.7% M7 38.8% <- BEST

DETAILS OF THE BEST (26612 ticks, 11086 above the lower bound of the current order)
position: index type entry_tick start_tick end_tick (entry = created; start = O8 starts on M1)
  0: 0 A 323 367 7182
  1: 8 B 968 1012 7747
  2: 1 A 1613 1657 8917
  3: 9 B 2581 2625 11819
  4: 2 A 3226 3270 11086
  5: 10 B 3871 3915 10729
  6: 3 A 4839 4883 13496
  7: 11 B 5484 5528 12310
  8: 4 A 6452 6496 17136
  9: 12 B 8065 8109 14924
  10: 5 A 9355 9399 17689
  11: 13 B 10000 10044 16779
  12: 6 A 12581 12625 21379
  13: 7 A 13549 13593 20683
  14: 17 E 14194 14238 20326
  15: 18 E 15484 15528 21736
  16: 19 E 17742 17786 23905
  17: 14 I 18710 18754 23548
  18: 15 I 19355 19399 24879
  19: 16 I 21936 21980 26612
- M1 idle intervals, longest first (ticks): [1980-2625], [4238-4883], [5851-6496], [22303-23225], [23905-24556], [24879-26289]

Give the analysis and 2 NEW orders of the indices 0-19.
```
