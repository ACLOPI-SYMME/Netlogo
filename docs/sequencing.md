# Optimizar el orden de una lista de productos (Línea A → Línea B)

Para el botón **"Optimizar orden"** de la pestaña de productos. La Línea B usa dos piezas de la Línea A:

1. `simulate_list`, que corre dentro de un worker: devuelve el makespan de una lista en un orden dado y, si se pide, los `details` de la corrida.
2. `POST /sequence/propose`, en el servicio del agente: recibe la lista y los órdenes ya simulados (`evaluated`) y devuelve hasta 2 órdenes **nuevos** del LLM, más el de la heurística.

El LLM no adivina: recibe los datos de la planta leídos del modelo, cifras precalculadas de la lista y los resultados de lo que ya se simuló. Ver un prompt real en [sequencing-prompt-example.md](sequencing-prompt-example.md).

## Flujo por rondas

1. **Ronda 0.** Simular con `simulate_list(..., details=True)` el orden original y el de la heurística. Se puede pedir la heurística a `/sequence/propose`, o importar `largest_first`.
2. **Rondas 1…R.** Llamar a `/sequence/propose` con `evaluated` = todo lo simulado hasta ahora (`order`, `makespan_ticks`, `details`). Simular los órdenes nuevos que devuelva y agregarlos a `evaluated`.
3. Mostrar el de menor makespan. Con 3 rondas se simulan hasta 8 órdenes.

El script `scripts/a4/sequence_rounds.py` hace este flujo sin interfaz.

## 1. `simulate_list` (`aclopi/sim/sequencing.py`)

```python
from aclopi.sim.sequencing import simulate_list

out = simulate_list(session, products, strategy="b1b", mode="Deterministic", seed=42,
                    max_ticks=200_000, on_progress=None, details=False)
# {"makespan_ticks": 26612, "makespan_time": 8249.72, "all_done": True,
#  "cancelled": False, "ticks": 27100, "wall_s": 12.0}          (+ "details" si details=True)
```

| Parámetro | Valores |
|---|---|
| `session` | La `SimulationSession` del worker. Se le hace `setup` de nuevo, así que **se pierde la corrida que tuviera**. |
| `products` | Lista en el orden de entrada. Acepta `[{"type": "A", "priority": 80}, …]` o `[("A", 80), …]`. Sin prioridad se usa 80, que no cambia la corrida. |
| `strategy` | `rule1`, `rule2` o `rule3`: reglas propias del modelo.<br>`b1` o `b1b`: regla 4, que decide en el mismo worker. Usa `compute_candidates` sobre el estado de la sesión, sin HTTP y sin consumir azar del modelo. Da el mismo makespan que b1b por la plataforma (lo verifica un test). |
| `mode` | `"Deterministic"` o `"Stochastic"`. |
| `seed` | Semilla de NetLogo. Con la misma semilla y la misma lista, el makespan es el mismo. |
| `max_ticks` | Tope de la corrida, que es el horizonte del `setup`. Si se alcanza antes de terminar la lista, `all_done` es `False` y `makespan_*` es `null`. |
| `on_progress(ticks, done, total)` | Se llama como mínimo cada 1.000 ticks y una vez al final. `done` son los productos terminados y `total` el largo de la lista. Si devuelve `False`, la simulación se cancela y la respuesta trae `cancelled: True`, `all_done: False` y `makespan_*: null`. Si devuelve `None` o `True`, sigue. |
| `details` | Opcional, `False` por defecto. Con `False` la respuesta queda igual que antes, sin la clave `details`, así que el contrato no cambia. Con `True` agrega `details`, que es `null` si la lista no terminó. |

**`details`.** Sale de los registros de los productos al final de la corrida, leídos con un solo reporter dentro de `platform-local`, así que no consume azar ni cambia el makespan. También usa la regla de entrada del modelo. Los tiempos van en ticks (tiempo / 0,31).

```json
{"products": [{"index": 0, "type": "A", "entry_tick": 323, "start_tick": 367, "end_tick": 7182}, …],
 "last": 19,
 "occupancy": {"M1": 46.6, "M2": 69.9, "M3": 46.6, "M4": 48.9, "M5": 53.6, "M6": 41.9, "M7": 37.3},
 "m1_idle": {"intervals": [[0, 367], [690, 1012], …], "total_ticks": 14825},
 "entry_windows": {"checks": 45, "created": 20, "zone_busy": 25, "wip_full": 0}}
```

| Campo | Significado |
|---|---|
| `products` | Uno por **posición en la lista que recibió `simulate_list`** (`index`; la creación sigue ese orden). Si esa lista es un orden de otra, el índice original es `order[index]`, y lo mismo vale para `last`. `/sequence/propose` hace esa conversión y responde 422 si los tipos de `details` no coinciden con el orden.<br>• `entry_tick`: el producto se crea.<br>• `start_tick`: empieza O8 en M1.<br>• `end_tick`: termina O9. |
| `last` | Posición del producto que terminó último. Su `end_tick` es el makespan. |
| `occupancy` | Porcentaje del makespan en que cada máquina estuvo procesando. |
| `m1_idle` | Intervalos `[desde, hasta]` en que M1 no procesaba, y su total. |
| `entry_windows` | Chequeos de entrada que hizo `Go` hasta que se creó el último producto: con creación (`created`), perdidos porque la zona de entrada estaba ocupada (`zone_busy`) o porque la planta tenía 10 productos (`wip_full`). |

**Cómo se reconstruyen las ventanas.** El modelo suma 0,31 u.t. por tick y redondea a 2 decimales. `Go` revisa la entrada cuando `tiempo mod 100 ≤ 0,2`, así que hay ventanas de 100 u.t. sin chequeo (por ejemplo, la de 200 u.t.: los ticks caen en 199,95 y 200,26). Los momentos de chequeo se calculan igual que en el modelo, y un test comprueba que cada creación real cae en uno de ellos. En un chequeo sin creación:

- si había 10 productos vivos, cuenta como `wip_full`;
- si no, solo pudo fallar por la zona ocupada, y cuenta como `zone_busy`.

**Bloqueo.** La simulación avanza en tramos de 1.000 ticks como máximo, y menos si el modelo va lento, para que cada tramo dure alrededor de 1 s. En las pruebas ningún tramo pasó de 0,9 s.

**Tiempos de referencia.** Con b1b en modo Deterministic:

| Lista | Tiempo por simulación |
|---|---|
| 10 productos | ~6–14 s |
| 20 productos | ~12 s (la primera de un proceso, ~20 s) |

**Makespan.** Es el instante en que termina el último producto de la lista, medido desde el inicio y en ticks (1 tick = 0,31 u.t.). Es el mismo `makespan_ticks` de `GET /sessions/{id}/kpis`.

## 2. `POST /sequence/propose` (servicio del agente)

Usa autenticación `Authorization: Bearer <ACLOPI_AGENT_TOKEN>`, el mismo token que `/decide`. Sin el token responde 401.

**Pedido.**

```json
{"products": [{"type": "A", "priority": 80}, {"type": "B", "priority": 80}, {"type": "I", "priority": 80}],
 "evaluated": [{"order": [0, 1, 2], "makespan_ticks": 9050, "details": {…}},
               {"order": [1, 0, 2], "makespan_ticks": 8790, "details": {…}}],
 "strategy": "b1b", "mode": "Deterministic"}
```

| Campo | Significado |
|---|---|
| `products` | Entre 1 y 100. `type` es `A`, `B`, `E`, `I`, `L`, `P` o `T`; si no, responde 422. `priority` es opcional y no se usa. |
| `evaluated` | Opcional, hasta 50. Lo que ya se simuló: `order` (permutación de los índices; si no lo es, responde 422), `makespan_ticks` y `details` (lo que devuelve `simulate_list(details=True)`; opcional, pero sin él el LLM tiene menos datos). |
| `strategy`, `mode` | Lo que se usará en `simulate_list`. Por defecto `b1b` y `Deterministic`. Cambian cómo el prompt describe el enrutamiento y los tiempos. |
| `reasoning` | Opcional: `"none"`, `"low"` o `"medium"`. Si no viene, se usa `ACLOPI_SEQUENCE_REASONING`. `"none"` es el **modo rápido**: ~6–7 s con 20 productos, frente a ~25–55 s con `medium`. Usa su propio tope y sus propios tokens (ver Configuración). Cualquier otro valor responde 422. |

**Respuesta.** Siempre es 200, aunque el LLM falle.

```json
{"orders": [{"order": [1, 2, 0], "reasoning": "…"}, {"order": [2, 1, 0], "reasoning": "…"}],
 "analysis": "M1 idle 14825 ticks; 25 of 45 entry checks missed by the occupied zone …",
 "heuristic": {"order": [0, 1, 2], "reasoning": "Longest first"},
 "latency_ms": 21400.0,
 "error": null}
```

| Campo | Significado |
|---|---|
| `orders` | Entre 0 y 2 órdenes **nuevas** del LLM. Cada `order` es una permutación completa de los índices de `products`, que empiezan en 0. Se descartan las incompletas, las repetidas entre sí y las **iguales a una de `evaluated`**. `reasoning` dice qué cambió y por qué; está en inglés y tiene 300 caracteres como máximo. |
| `analysis` | Por qué pierde tiempo el mejor orden evaluado, con datos de sus `details`. Tiene 300 caracteres como máximo y es `null` si el LLM falló. |
| `heuristic` | La orden de `largest_first`. Siempre está presente. |
| `latency_ms` | Duración total del pedido. |
| `error` | `null` si quedó al menos una orden del LLM. Si no:<br>• `llm-timeout`<br>• `llm-invalid-json`<br>• `llm-provider`<br>• `no-valid-order` |

**Configuración, solo para este endpoint:**

- `ACLOPI_SEQUENCE_REASONING`: `reasoning_effort` del LLM; por defecto `medium`. Las decisiones de máquina siguen en `none`.
- `ACLOPI_SEQUENCE_TIMEOUT_S`: tope de la llamada; por defecto 90 s.
- `ACLOPI_SEQUENCE_MAX_PARALLEL`: llamadas de ordenamiento a la vez; por defecto 1. Tienen su propio semáforo, separado del de las decisiones de máquina, así que una decisión nunca espera detrás de un ordenamiento. Si ya están todas ocupadas, responde **429** de inmediato, con `{"code": "sequence_busy"}` y la cabecera `Retry-After` (segundos hasta el tope de la llamada en curso). El pedido no queda en cola.

El prompt pide citar solo cifras que estén en los datos (makespan, `details`, cifras precalculadas) y no estimar tiempos propios.

- `ACLOPI_SEQUENCE_FAST_TIMEOUT_S` y `ACLOPI_SEQUENCE_FAST_MAX_TOKENS`: tope y `max_tokens` con `reasoning` `"none"`; por defecto 30 s y 1.000 tokens, más 6 por producto. Con `low` y `medium` se usan hasta 8.000 tokens, más 6 por producto, para que quepan el razonamiento y la respuesta.
- `ACLOPI_SEQUENCE_PROMPT_BUDGET`: presupuesto del prompt en tokens (caracteres / 4); por defecto 30.000. Si el prompt lo pasa, solo las 3 órdenes evaluadas con menor makespan llevan sus `details` y las demás solo su makespan.

**Tamaño del prompt** (medido con `scripts/a4/sequence_prompt_size.py`, con `details` sintéticos de forma real):

| Productos | 2 evaluadas | 4 evaluadas | 8 evaluadas |
|---|---|---|---|
| 10 | 1.571 | 1.683 | 1.904 |
| 20 | 1.721 | 1.859 | 2.135 |
| 50 | 2.055 | 2.269 | 2.696 |
| 100 | 2.609 | 2.949 | 3.626 |

El prompt crece poco, porque solo la mejor orden lleva su tabla por producto, así que el presupuesto de 30.000 no se alcanza en usos normales. Lo que limita es la respuesta: 2 permutaciones completas. Con strata (una llamada por caso):

| Productos | Modo rápido (`none`) | `medium` |
|---|---|---|
| 50 | 2/2 órdenes válidas, 7,8 s | 2/2 válidas, 29,6 s |
| 100 | 1/2 válidas, 12,5 s | 1/2 válidas, 60,4 s |

**Recomendación: 50 productos como máximo** para `/sequence/propose`. La API acepta 100.

**Heurística `largest_first(products)`** (`aclopi/agent/sequencing.py`, devuelve una lista de índices; `heuristic_order(products)` en `aclopi/sim/sequencing.py` es la misma, como función pública para la Línea B):

- Primero van los tipos con más operaciones, sin contar O8/O9: A, B y L tienen 7; E tiene 6; I, P y T tienen 4.
- Dentro de cada grupo, el siguiente producto es del tipo al que le quedan más productos sin repetir el tipo anterior.
- Cada tipo mantiene el orden que tenía en la lista.

## 3. Contexto del prompt (`aclopi/agent/sequencing_context.py`)

Todo sale del modelo, no de valores escritos en el código.

`read_plant(session)` lo lee con NetLogo:

- máquinas, operaciones y `Machine.Operations.Time` vigente;
- máquinas capaces de cada operación;
- matriz `distances` (u.t.; 0 a la misma máquina);
- secuencia de cada tipo (`AgregateOperations`);
- regla de entrada (período, ventana, WIP máximo y zona) y paso del tiempo, leídos del código de `Go` y `Product.Movement`;
- extra estocástico (`random-exponential 10`, que no se aplica en M1);
- viaje desde la creación hasta M1 (13,64 u.t.), medido con un producto.

El servicio del agente no tiene NetLogo, así que usa la copia guardada en `aclopi/agent/data/plant_context.json`. La genera `scripts/a4/export_plant_context.py`, y un test falla si deja de coincidir con el modelo.

`list_figures(plant, products, strategy, mode)` calcula las cifras de la lista:

- **Por tipo:** secuencia, trabajo total, máquinas posibles por paso y `min_time`. `min_time` es el tiempo desde la creación hasta el fin de O9 sin esperas: viaje de entrada, más proceso, más viajes por la mejor ruta.
- **Trabajo** por operación y por máquina posible.
- **Carga de M1:** O8 + O9 de todos los productos.
- **Cota inferior del makespan para el orden actual:**
  - cota de M1 = primera llegada a M1 + carga de M1;
  - cota de camino = para cada posición *k*, el *k*-ésimo chequeo de entrada + `min_time` de ese producto; se toma la peor;
  - la cota es el máximo de las dos.

## Prueba por rondas (b1b, Deterministic, semilla 42, 20 productos: 8 A, 6 B, 3 I, 3 E)


Hecha con el script `scripts/a4/sequence_rounds.py` y el LLM real (strata, `reasoning_effort` medium). Las dos listas tienen los mismos productos, en distinto orden inicial.

### Lista agrupada (`AAAAAAAABBBBBBIIIEEE`)

| Ronda | Quién | Orden (tipos) | Makespan | vs. heurística |
|---|---|---|---|---|
| 0 | original | AAAAAAAABBBBBBIIIEEE | 27745 | +4.3 % |
| 0 | heuristic | ABABABABABABAAEEEIII | 26612 | +0.0 % |
| 1 | LLM 1 | IAIAIAEBEBEBABABABAA | 25760 | -3.2 % |
| 1 | LLM 2 | IEIEIEABABABABABABAA | 26134 | -1.8 % |
| 2 | LLM 1 | IIIEEEABABABABABABAA | 27585 | +3.7 % |
| 2 | LLM 2 | IIIEAEAEAAAAAABBBBBB | 27144 | +2.0 % |
| 3 | LLM 1 | AIBAIBAIBAEBAEBAEBAA | 28594 | +7.4 % |
| 3 | LLM 2 | IABIABIABEABEABEABAA | 28366 | +6.6 % |

Latencia del LLM: ronda 1: 26.1 s, ronda 2: 55.8 s, ronda 3: 53.6 s. Mejor orden: IAIAIAEBEBEBABABABAA, 25760 ticks (ronda 1, LLM 1).

### Lista intercalada ABIE (`ABIEABIEABIEABABABAA`)

| Ronda | Quién | Orden (tipos) | Makespan | vs. heurística |
|---|---|---|---|---|
| 0 | original | ABIEABIEABIEABABABAA | 27950 | +5.0 % |
| 0 | heuristic | ABABABABABABAAEEEIII | 26612 | +0.0 % |
| 1 | LLM 1 | ABABIABIABIABABAAEEE | 27142 | +2.0 % |
| 1 | LLM 2 | ABABABIABIABIABAAEEE | 26132 | -1.8 % |
| 2 | LLM 1 | EABEABEABIABIABIABAA | 27631 | +3.8 % |
| 2 | LLM 2 | AEBEAEBAIBIAIBABABAA | 28757 | +8.1 % |
| 3 | LLM 1 | ABABEABEABEABIABAAII | 24106 | -9.4 % |
| 3 | LLM 2 | ABABAEBAEBAEBIABAAII | 25847 | -2.9 % |

Latencia del LLM: ronda 1: 25.1 s, ronda 2: 26.5 s, ronda 3: 53.8 s. Mejor orden: ABABEABEABEABIABAAII, 24106 ticks (ronda 3, LLM 1).

Explicaciones de cada orden y el `analysis` de cada ronda: `results/sequencing/rounds_*.json`.

### Modo rápido (`reasoning` `"none"`, ronda 0 + 1 ronda)

Resultado de `scripts/a4/sequence_rounds.py --rounds 1 --reasoning none`. Detalle en `results/sequencing/rounds_*_none.json`.

| Lista | Heurística | Mejor del LLM | vs. heurística | Latencia |
|---|---|---|---|---|
| Agrupada | 26612 | 25654 (ABIEIEIEABABABABABAA) | −3,6 % | 6,1 s |
| Intercalada ABIE | 26612 | 27102 (AIAIAIAAAABEBEBEBBBA) | +1,8 % (no mejora) | 6,7 s |
