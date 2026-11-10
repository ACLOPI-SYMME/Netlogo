# Optimizar el orden de una lista de productos (Línea A → Línea B)

Para el botón **"Optimizar orden"** de la pestaña de productos. La Línea B usa dos piezas de la Línea A:

1. `simulate_list`, que corre dentro de un worker: devuelve el makespan de una lista en un orden dado.
2. `POST /sequence/propose`, en el servicio del agente: devuelve hasta 2 órdenes del LLM y el de la heurística.

Un flujo típico es este:

1. Pedir órdenes a `/sequence/propose`.
2. Simular cada orden con `simulate_list` (el original, los del LLM y el de la heurística).
3. Mostrar el de menor makespan.

## 1. `simulate_list` (`aclopi/sim/sequencing.py`)

```python
from aclopi.sim.sequencing import simulate_list

out = simulate_list(session, products, strategy="b1b", mode="Deterministic", seed=42,
                    max_ticks=200_000, on_progress=None)
# {"makespan_ticks": 26612, "makespan_time": 8249.72, "all_done": True,
#  "cancelled": False, "ticks": 27100, "wall_s": 12.0}
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

**Bloqueo.** La simulación avanza en tramos de 1.000 ticks como máximo, y menos si el modelo va lento, para que cada tramo dure alrededor de 1 s. En las pruebas ningún tramo pasó de 0,9 s.

**Tiempos de referencia.** Con b1b en modo Deterministic:

| Lista | Tiempo por simulación |
|---|---|
| 10 productos | ~6–14 s |
| 20 productos | ~12 s (la primera de un proceso, ~24 s) |

**Makespan.** Es el instante en que termina el último producto de la lista, medido desde el inicio y en ticks (1 tick = 0,31 u.t.). Es el mismo `makespan_ticks` de `GET /sessions/{id}/kpis`.

## 2. `POST /sequence/propose` (servicio del agente)

Usa autenticación `Authorization: Bearer <ACLOPI_AGENT_TOKEN>`, el mismo token que `/decide`. Sin el token responde 401.

**Pedido.** Entre 1 y 100 productos. `type` es `A`, `B`, `E`, `I`, `L`, `P` o `T`; si no, responde 422. `priority` es opcional y no se usa.

```json
{"products": [{"type": "A", "priority": 80}, {"type": "B", "priority": 80}, {"type": "I", "priority": 80}]}
```

**Respuesta.** Siempre es 200, aunque el LLM falle.

```json
{"orders": [{"order": [1, 0, 2], "reasoning": "Interleaves types to balance machine loads …"},
            {"order": [2, 0, 1], "reasoning": "…"}],
 "heuristic": {"order": [0, 1, 2], "reasoning": "Longest first"},
 "latency_ms": 3180.4,
 "error": null}
```

| Campo | Significado |
|---|---|
| `orders` | Entre 0 y 2 órdenes del LLM. Cada `order` es una **permutación completa** de los índices de `products`, que empiezan en 0. Las órdenes incompletas, con índices repetidos o duplicadas se descartan. `reasoning` está en inglés y tiene 200 caracteres como máximo. Una orden puede ser igual a la original. |
| `heuristic` | La orden de `largest_first` (ver abajo). Siempre está presente. |
| `latency_ms` | Duración total del pedido. |
| `error` | `null` si quedó al menos una orden del LLM. Si no:<br>• `llm-timeout`: el tope es de 30 s (`ACLOPI_SEQUENCE_TIMEOUT_S`).<br>• `llm-invalid-json`.<br>• `llm-provider`.<br>• `no-valid-order`: el LLM respondió, pero ninguna orden era válida. |

**Heurística `largest_first(products)`** (`aclopi/agent/sequencing.py`, devuelve una lista de índices):

- Primero van los tipos con más operaciones: A, B y L tienen 7; E tiene 6; I, P y T tienen 4.
- Dentro de cada grupo, el siguiente producto es del tipo al que le quedan más productos sin repetir el tipo anterior. Un tipo solo se repite cuando no queda otro en el grupo.
- Cada tipo mantiene el orden que tenía en la lista.

**Prompt al LLM.** Incluye:

- la lista con sus índices;
- las operaciones de cada tipo, sin O8/O9;
- qué máquinas hacen cada operación;
- la regla de entrada: entra un producto cada 100 u.t. si la zona de M1 está libre y hay menos de 10 en planta;
- el objetivo: terminar toda la lista lo antes posible.

La salida es JSON con esquema.

## Prueba de referencia (lista de 20: 8 A, 6 B, 3 I, 3 E; semilla 42, Deterministic, b1b)

Resultado del script `scripts/a4/sequence_check.py` con el LLM real (strata):

| Orden | Tipos | Makespan (ticks) |
|---|---|---|
| Original | AAAAAAAABBBBBBIIIEEE | 27745 |
| LLM 1 (igual al original) | AAAAAAAABBBBBBIIIEEE | 27745 |
| LLM 2 | ABIEABIEABIEABABABAA | 27950 |
| Heurística | ABABABABABABAAEEEIII | **26612** |
