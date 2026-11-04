# What-if y candidates (L5.4)

Estos dos endpoints permiten al código del agente (Línea A) evaluar una decisión pendiente de la regla 4 antes de tomarla. El gancho de decisión está descrito en `docs/rule4-decision-hook.md`.

## Contexto y plazos

- **Cuándo decide el agente.** Mientras el producto se procesa en una máquina: la petición se crea al **entrar** a la máquina y la respuesta se usa cuando la operación termina.
- **Plazo de decisión en vivo.** Es lo que le falta al producto en su máquina actual menos ~2 s de margen: **~8 s desde M1** y **~18 s desde M2–M7**.
- **Duración del what-if.** La fija el agente con `budget_ms` en cada pedido (10 s por defecto, de 2 a 15 s), a partir de su plazo de decisión y del tiempo que necesitan sus llamadas al LLM:
  - **desde M2–M7** (~18 s) cabe un what-if de ~10 s;
  - **desde M1** (~8 s) el what-if **no cabe** junto con las llamadas al LLM, así que el agente no debería pedirlo.
- **Meta de concurrencia.** **5 sesiones simultáneas**, con 2 workers de what-if compartidos.
- **Sesiones válidas.** Solo las de **regla 4**. La regla 4 sin decisor es exactamente la regla 3.

## `GET /sessions/{id}/candidates?product=&seq=`

Devuelve las máquinas candidatas para la operación `seq` del producto `product`, con su carga y su inicio y fin estimados.

- **Parámetros:** los dos son obligatorios. `seq` es la operación pendiente, `CurrentSequenceOrder + 1`.
- **Cálculo:** lo hace `aclopi.sim.candidates.compute_candidates` (Línea A) sobre `platform-state`, dentro del worker de la sesión. No consume azar ni altera la simulación, y mientras la sesión corre se atiende entre bloques.
- **Pedido inválido:** responde 200 con `valid: false` y `reason` (`unknown-or-finished-product`, `invalid-seq`, `seq-mismatch` o `not-in-machine`).
- **Esquema:** la respuesta es directamente `CandidatesResult` de `aclopi/contracts/candidates.py` (Línea A), sin copia en la API. Así sus campos aparecen en `contracts/openapi.json`. El significado de cada campo está en `docs/agent-status.md` ("Campos de `CandidatesResult`").

Campos principales: `candidates` (ordenadas por `finish`), `current_machine`, `own_remaining`, `next_operation`, `best_by_finish`, `best_by_finish_plus_next`, `gap_*`, `travel_source`. Por candidata: `travel` = `distances[actual][m]` en u.t., `available` (bool) y el tiempo hasta que la máquina queda libre en `available_in`, `arrival`, `start`, `finish` (u.t. absolutos), `proc_time`, `next_machine`, `travel_next`, `is_current_machine`, `queue`, `en_route`, `stay_time` y `stay`.

## `POST /sessions/{id}/what-if`

```json
{"product": 201, "seq": 1, "options": ["M2", "M3"], "max_ticks": 3000, "budget_ms": 10000}
```

- **`options`:** exactamente **2 máquinas distintas**, elegidas por el código del agente. Si son iguales, o si no son exactamente dos, la API responde 422.
- **`max_ticks`:** tope de ticks por copia, de 1 a 5000 (3000 por defecto).
- **`budget_ms`:** tiempo máximo del pedido completo (las dos copias, en serie en un solo worker), de 2000 a 15000 ms (10000 por defecto). Fuera de rango → 422. Al agotarse, la API devuelve lo que haya con `status: "timeout"`.

### Qué hace

1. **¿Ya probado?** Si en esta sesión ya hubo un what-if para el mismo (`product`, `seq`), responde `skipped` con `already-used`.
2. **Worker libre.** Toma prestado un worker de what-if **sin cola**: si no hay uno libre, responde `skipped` con `no-free-worker` en pocos milisegundos.
3. **Foto y validación.** El worker de la sesión, entre dos bloques, valida las dos opciones con `platform-check-next-machine`, mide la carga de las dos máquinas y toma **una sola foto** (export) del mundo. La sesión real no se detiene: en vivo sigue corriendo.
4. **Copias, una tras otra.** Cada copia se ejecuta en el worker prestado: importa la foto, fuerza la opción con `platform-set-next-machine` y avanza.
   - Corre primero la opción con **menor entrada estimada** (con viaje; ver "Estimación de la entrada").
   - Dentro de la copia nunca se llama al agente: las demás decisiones las toma el código de la regla 3, y las peticiones de la copia no salen del worker.
5. **Parada de cada copia:**

   | `stop_reason` | Cuándo |
   |---|---|
   | `entered` | El producto **entra** a la máquina probada. Se leen el tick, el tiempo de entrada y el fin de la operación (`Next.Completion`), que se fija al entrar, con su parte aleatoria incluida |
   | `cap` | Llegó a `max_ticks` sin entrar |
   | `stalled` | Bloqueo: durante `ACLOPI_WHATIF_STALL_TICKS` ticks (300) ningún producto cambió de posición **y** ninguna operación empezó ni terminó (el total de elementos de `ProductRealStart` y `ProductRealCompletion` de todos los productos no cambió). Se compara cada `min(150, stall_ticks)` ticks. Una operación en M2–M7 dura ~645 ticks: que todos esperen en máquina o en cola no es un bloqueo |
   | `pruned` | Solo la segunda copia: llegó a la ventana común sin entrar, así que ya es peor que la primera |
   | `timeout` | Se acabó `budget_ms` |
   | `horizon` | Terminó la corrida |

   Si el producto no entró, la entrada y el fin se **estiman** (`entry_estimated`) sobre el estado de la copia en la parada, con la fórmula de "Estimación de la entrada", y la copia queda marcada.

   El JSON del diagnóstico de un bloqueo incluye el pedido, la máquina, el tick, `quiet_ticks` y cuántas máquinas estaban procesando.

### Estimación de la entrada (con viaje)

El producto puede entrar a la máquina probada cuando **llegó** y la máquina está **libre**:

```
llegada = ahora + lo que le falta a su operación actual (si está en una máquina)
                + viaje desde su máquina hasta la probada − viaje ya hecho (si ya salió)
libre   = ahora + lo que le falta al trabajo en curso de la máquina probada
                + tiempos de proceso de los productos en su cola o en camino (+10 en M2–M7 en Stochastic)
entrada = max(llegada, libre)        fin = entrada + tiempo de la operación en esa máquina
```

**Qué estimación se usa.** Para ordenar las copias (y para `entry-beyond-cap`), la foto usa el `start` de `candidates` de la Línea A para cada opción, porque cuenta la cola, los productos en camino y el ocupante que se queda. Si `candidates` no da la máquina (por ejemplo, el producto ya no está en una máquina), se usa la fórmula de arriba como respaldo. La respuesta del snapshot dice cuál se usó (`estimate_source`: `candidates` o `fallback`). Cuando una copia no entró, la entrada estimada en la parada sale siempre de la fórmula de arriba, porque en ese momento el producto suele ir viajando.

**Viaje.** `distances[origen][destino]` (global `distances`, `Set.distances.Machines`; la fila es la máquina de origen) **ya está en u.t.**: es el viaje mínimo medido en cada ruta (`data/a0/travel_times.csv`, Línea A).

```
viaje (u.t.) = distances[origen][destino]        viaje (ticks) = viaje / 0,31
```

Antes se dividía por la velocidad del transportador (0,3 por tick) y se multiplicaba por 0,31, lo que sobreestimaba el viaje un 3,3 %. Corregido en `aclopi.sim.candidates.travel_time`.

- **Origen:** la máquina en la que está el producto (`product` de la máquina en `platform-state`) o, si ya salió, la última de `Machine.Used`. En ese caso el viaje ya hecho sale de `ahora − última ProductRealCompletion`.
- **Qué no incluye:** las esperas en compuertas ni el bloqueo detrás de otros productos. Por eso puede quedarse corta.

   Con un bloqueo, la foto y el pedido se guardan en `results/whatif_diagnostics/` (`ACLOPI_WHATIF_DIAG_DIR`) y la ruta viene en `diagnostic_file`.

**Por qué la predicción es exacta.** La copia parte de la misma foto, con el mismo estado del generador aleatorio, y la regla 3 decide lo mismo en la copia y en la sesión real. Por eso una entrada real (`entered`) predice exactamente lo que pasará si el agente asigna esa máquina en ese momento. Lo verifica `tests/test_whatif.py` (prueba a).

### Ventana común y métrica de los demás productos

**Ventana.** Es el tick en que se detuvo la **primera** copia, por entrada, tope o bloqueo.
- **Si la segunda no entró antes de la ventana:** se poda ahí, porque entra más tarde.
- **Si entró antes:** sigue hasta la ventana.

Así las dos métricas se miden en el mismo tick, y la poda coincide con la ventana.

**Métrica `others`**, sobre `[foto, ventana]`, para todos los productos salvo el que se decide:

| Campo | Significado |
|---|---|
| `work` | Trabajo de proceso **nominal** hecho en la ventana: una operación completada suma su `OperationDuration` y la que está en curso, la fracción procesada (igual que el KPI `work_completed`) |
| `wait` | Tiempo en planta dentro de la ventana menos el tiempo de proceso recibido: viajando o en cola |
| `presence` | Tiempo que los demás productos estuvieron en planta dentro de la ventana (`wait` = `presence` − proceso recibido) |
| `finished` | Productos terminados dentro de la ventana |

La plataforma no combina estas cantidades ni ordena las opciones: eso lo decide el agente.

### Definición de los campos

Todos los valores están en **unidades de tiempo simulado (u.t.)**, salvo los ticks y los conteos. 1 tick = 0,31 u.t. (`set simulated.time precision (simulated.time + 0.31) 2`, línea 1020).

Notación:

| Símbolo | Significado |
|---|---|
| `T0` | `Simulated.Time` de la foto, que es el momento de la petición |
| `T` | `Simulated.Time` en la parada de la copia, que es la ventana común para comparar |
| `W` | El producto que se decide |
| "los demás" | Todos los productos de la copia salvo `W`: también los creados dentro de la ventana y los que terminan dentro de ella. Los que terminaron antes de `T0` aportan 0 |

**Entrada y fin de la operación de `W`**

| Campo | Definición |
|---|---|
| `entry_tick` | Tick del `go` en que `W` entra a la máquina probada, es decir, en que `length ProductRealStart` pasa de `seq` a `seq + 1` |
| `entry_time` | `item seq ProductRealStart` de `W`, en u.t. |
| `op_end_time` | `Next.Completion` de la máquina probada leída en ese tick. Se fija al entrar e incluye la parte aleatoria `random-exponential 10` en M2–M7 (líneas 1310–1317 para M1, sin término aleatorio, y 1455–1462 y sus copias para M2–M7) |
| Valores estimados (`*_estimated: true`) | Cuando `W` no entra, salen de "Estimación de la entrada" sobre el estado de la copia en la parada |

**Ventana**

| Campo | Definición |
|---|---|
| `window_tick` | El tick en que se detuvo la **primera** copia, la de menor entrada estimada, ya sea por entrar, por tope, por bloqueo o por plazo |
| Cómo corre la segunda copia | Corre hasta su entrada o hasta `window_tick`, lo que llegue primero. Si entra antes, sigue hasta `window_tick`. Si no entró al llegar a la ventana, se poda (`pruned`). En ambos casos, su `others` se mide en `window_tick` |
| Excepción | Si la segunda copia se queda sin plazo antes de la ventana, `others.window_tick` dice dónde se midió |

**Métrica `others`** (las sumas son sobre los demás)

| Campo | Fórmula |
|---|---|
| `work` | `Σ trabajo_nominal(T) − Σ trabajo_nominal(T0)`. `trabajo_nominal` es el de `work_completed` (`aclopi/sim/kpis.py`): cada operación completada suma su `OperationDuration` (200 en O1–O7, 100 en O8–O9; `Set.operations`, línea 2633). La que está en curso suma `OperationDuration × fracción procesada`, donde la fracción es `(Simulated.Time − last ProductRealStart) / (Next.Completion − last ProductRealStart)`, recortada a [0, 1]. Usa el **tiempo nominal**, no el real. Una operación que cae solo en parte dentro de la ventana aporta la parte de su nominal que avanzó en ella |
| `presence` | `Σ solapamiento([max(ProductCreationTime, T0), fin], [T0, T])`, con `fin` = `last ProductRealCompletion` si terminó (estado `death`), o `T` si sigue en planta. Es tiempo **real** en planta |
| `wait` | `presence − Σ proceso_real`, con `proceso_real` = `Σ solapamiento([ProductRealStart_i, ProductRealCompletion_i o T], [T0, T])`. Es tiempo **real** sin proceso, es decir, viajando o en cola. **No usa `work`**: como `presence` y `proceso_real` son reales, `wait` no arrastra el término aleatorio. El tiempo extra de una operación larga por `random-exponential` cuenta como proceso, no como espera |
| `finished` | Cantidad de los demás con estado `death` y `last ProductRealCompletion > T0`, es decir, que terminaron dentro de la ventana |

**Ejemplo.** Con `T0` = 300 y `T` = 500 u.t. hay dos productos más:

| Producto | Qué pasa en la ventana | `presence` | `proceso_real` | `work` |
|---|---|---|---|---|
| A | En planta desde antes. Procesa O1 entre 350 y 560 (real 210: nominal 200 + 10 aleatorio) | 200 | 150 | `200 × (150 / 210) ≈ 142,9` |
| B | Se crea en 420 y viaja | 80 | 0 | 0 |

Totales: `presence` = 280, `wait` = 280 − 150 = 130, `work` ≈ 142,9 y `finished` = 0.

### Respuesta (siempre 200, salvo validación)

```jsonc
{"status": "ok",                     // ok | timeout | skipped | error
 "skipped_reason": null,             // no-free-worker | already-used | entry-beyond-cap
 "snapshot_tick": 1012, "snapshot_time": 313.72, "operation": "O1",
 "window_tick": 1987, "run_order": ["M3", "M2"],
 "timings_ms": {"export": 98, "import": 1010, "advance": 1630, "total": 2850},
 "would_skip_entry_beyond_cap": false, "loads": {"M2": 1, "M3": 0}, "estimated_entry_ticks": {"M2": 995, "M3": 694},
 "options": [                        // en el orden del pedido
   {"machine": "M2", "entered": true, "stop_reason": "entered",
    "entry_tick": 1987, "entry_time": 615.97, "entry_estimated": false,
    "op_end_time": 829.1, "op_end_estimated": false,
    "others": {"window_tick": 1987, "work": 431.2, "wait": 38.4, "presence": 612.3, "finished": 0},
    "ticks_simulated": 975, "stop_tick": 1987, "cap_reached": false, "stalled": false,
    "pruned": false, "timed_out": false, "skipped": false,
    "duration_ms": 1350, "import_ms": 505, "advance_ms": 845, "diagnostic_file": null, "error": null},
   {"machine": "M3", ...}]}
```

- **`skipped`:** es una respuesta normal; `options` viene vacío.
- **`timeout`:** trae lo que se alcanzó. Una opción que no llegó a correr viene con `skipped: true`.

### Errores de validación

| HTTP | `code` | Cuándo |
|---|---|---|
| 422 | `invalid_option` | Producto inexistente, máquina desconocida o no capaz de la operación, `seq` fuera de rango. `detail` dice el motivo de cada opción |
| 409 | `decision_not_pending` | Producto terminado (`product-finished`), fuera de una máquina (`not-in-machine`) o `seq` que no es la pendiente (`seq-mismatch`, `stale-seq`) |
| 409 | `rule4_required` | La sesión no tiene regla 4 |
| 422 | – | Formato inválido (no son 2 opciones, opciones iguales, `max_ticks` o `budget_ms` fuera de rango) |

### Entrada más allá del tope: `entry-beyond-cap` (POR CONFIRMAR, solo se registra)

- **Criterio:** la entrada estimada **con viaje** (ver "Estimación de la entrada") de **las dos** opciones queda más allá de `max_ticks`. En ese caso ninguna copia llegaría a ver la entrada y el what-if solo devolvería estimaciones.
- **Comportamiento actual:** el what-if **no** se salta. Se registra `would_skip_entry_beyond_cap: true` en la respuesta y en las métricas. Para que se salte (`skipped` con `entry-beyond-cap`), poner `ACLOPI_WHATIF_SKIP_BEYOND_CAP=1` (apagado por defecto).
- **Datos en la respuesta:** `estimated_entry_ticks` (por opción, desde la foto) y `loads`.
- La calidad de la estimación y la frecuencia del criterio se miden con `scripts/l5/whatif_estimation.py`.

## `GET /sessions/{id}/metrics`

`{"whatif": {...}}`, para la sección 3.4 del plan:

| Grupo | Campos |
|---|---|
| Pedidos | `requests`, `ok`, `timeout`, `error`, `invalid` |
| Saltados | `skipped` por motivo (`no-free-worker`, `already-used`, `entry-beyond-cap`), `would_skip_entry_beyond_cap` |
| Opciones | `options_run`, `entered`, `cap_reached`, `stalled`, `pruned`, `options_timed_out` |
| Tiempos (media, p95, máx., n) | `duration_ms`, `export_ms`, `import_ms`, `advance_ms` |
| Ticks (media, p95, máx., n) | `ticks_to_entry`, `ticks_simulated` |

## Configuración

| Variable | Por defecto | |
|---|---|---|
| `ACLOPI_WHATIF_STALL_TICKS` | 300 | Ticks sin movimiento ni proceso para declarar un bloqueo |
| `ACLOPI_WHATIF_CHUNK_TICKS` | 150 | Ticks entre lecturas de control de la copia |
| `ACLOPI_WHATIF_SKIP_BEYOND_CAP` | 0 | 1 = saltar el what-if cuando la entrada estimada de las dos opciones supera `max_ticks` |
| `ACLOPI_WHATIF_DIAG_DIR` | `results/whatif_diagnostics` | Fotos de los bloqueos |

## Diseño previsto para L5.5 (todavía no implementado)

- **Latidos en modo rápido.** Mientras se espera una decisión, el worker enviará latidos para que el vigilante de 15 s no lo mate.
- **Agente que no responde en modo rápido.** Si pasan ~90 s sin respuesta, la corrida se marca como **fallida**: no sigue con la regla 3. Si la lanzó un usuario desde `/ui`, verá "agente no disponible".
- **Agente que no responde en vivo.** El modelo aplica la regla 3 por su cuenta y la plataforma mostrará el % de `rule3-fallback`.
