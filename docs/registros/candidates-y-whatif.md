# Respuestas de candidates y what-if

[← Índice y glosario](README.md)

Las dos son herramientas que usa el agente para decidir. Se pueden consultar a mano para entender una decisión. El diseño está en `docs/whatif.md` y `docs/agent-api.md`; aquí se explica cómo leer las respuestas. Las dos exigen `Authorization: Bearer <ACLOPI_AGENT_TOKEN>` si el token está configurado.

## Candidates

### Qué es

Para un producto que está en una máquina y una operación pendiente, calcula **cada máquina que podría hacerla**: cuándo llegaría el producto, cuándo empezaría, cuándo terminaría y qué tiene por delante. Es una cuenta sobre la foto actual de la planta; **no simula** ni cambia nada.

### Cómo se genera, cuándo y cómo verlo

- A pedido: `GET /sessions/{id}/candidates?product=<who>&seq=<operación>`. Durante una corrida, el worker lo atiende entre dos bloques.
- Solo tiene sentido mientras el producto está **dentro** de una máquina y `seq` es su siguiente operación. Si no, responde igual (200) pero con `valid: false` y el motivo.
- No se guarda. El agente real copia un resumen en su `decisions.jsonl` ([decisiones.md](decisiones.md#registro-del-lado-del-agente-real-decisionsjsonl)).

### Campos generales

| Campo | Qué significa | Unidad | Valores |
|---|---|---|---|
| `product`, `seq` | Producto y operación consultados | — | — |
| `operation` | Operación que se decide | — | O1…O9 |
| `tick`, `time` | Momento de la foto | ticks, u.t. | — |
| `valid` | Si la consulta tiene sentido ahora | — | `true`, `false` |
| `reason` | Si no es válida, por qué | — | por ejemplo `unknown-or-finished-product`, `seq-mismatch`, `not-in-machine` |
| `current_machine` | Máquina donde está el producto | — | M1…M7 |
| `own_remaining` | Lo que le falta a su operación actual | u.t. | — |
| `next_operation` | La operación que viene después de la que se decide | — | O1…O9, o `null` si es la última |
| `best_by_finish` | Máquina que termina antes | — | — |
| `best_by_finish_plus_next` | Máquina que termina antes contando el viaje a la operación siguiente | — | — |
| `gap_finish`, `gap_finish_plus_next` | Diferencia entre la mejor y la segunda en cada criterio | u.t. | `null` con una sola máquina |
| `travel_source` | De dónde salen los tiempos de viaje | — | `distances` (las distancias del modelo) |
| `candidates` | Lista de máquinas, de la que termina antes a la que termina después | — | ver abajo |

### Campos de cada máquina (`candidates[]`)

**Las horas (`arrival`, `start`, `finish`, `finish_plus_next`) son absolutas**, en u.t. del reloj de la simulación (comparables con `time`). Las demás son duraciones en u.t.

| Campo | Qué significa |
|---|---|
| `machine` | La máquina |
| `own_remaining` | Lo que le falta al producto en su máquina actual |
| `travel` | Viaje desde su máquina actual hasta esta (0 si es la misma) |
| `arrival` | Hora de llegada: `time + own_remaining + travel` |
| `current_remaining` | Lo que le falta al trabajo que esta máquina tiene en curso (0 si está libre o es la máquina actual) |
| `queue_time`, `queue` | Tiempo de proceso de los productos que esperan en su cola, y cuáles son |
| `en_route_time`, `en_route` | Tiempo de proceso de los productos que vienen en camino hacia ella, y cuáles son |
| `stay_time`, `stay` | Tiempo de los productos que probablemente se queden en esa máquina para otra operación, y cuáles son |
| `available_in` | Cuándo queda libre, contado desde ahora: `current_remaining + queue_time + en_route_time + stay_time` |
| `start` | Hora de inicio: `time + max(own_remaining + travel, available_in)` |
| `proc_time` | Duración de la operación en esa máquina (tiempo del modelo + 10 u.t. de extra promedio, salvo en M1) |
| `finish` | Hora de fin: `start + proc_time` |
| `delta_finish` | `finish` menos el mejor `finish` (0 en la mejor) |
| `next_machine`, `travel_next` | Para la operación siguiente: la máquina capaz más cercana a esta, y el viaje |
| `finish_plus_next`, `delta_finish_plus_next` | `finish + travel_next`, y su diferencia con el mejor |
| `is_current_machine` | Si es la máquina donde ya está (se reprocesa sin viajar y adelante de la cola) |
| `available` | Si la máquina está disponible. Hoy siempre `true` |

### Ejemplo real

En la corrida en vivo, pausada en el tick 642 (una de las cuatro máquinas posibles, recortado):

```json
{"product": 200, "seq": 1, "operation": "O1", "tick": 642, "time": 199.02, "valid": true, "reason": null,
 "current_machine": "M1", "own_remaining": 14.75, "next_operation": "O1",
 "best_by_finish": "M2", "best_by_finish_plus_next": "M2", "gap_finish": 14.2, "gap_finish_plus_next": 14.2,
 "candidates": [{"machine": "M2", "own_remaining": 14.75, "travel": 111.3, "arrival": 325.07,
                 "current_remaining": 0.0, "queue_time": 0.0, "en_route_time": 0.0, "stay_time": 0.0,
                 "available_in": 0.0, "start": 325.07, "proc_time": 210.0, "finish": 535.07,
                 "delta_finish": 0.0, "next_machine": "M2", "travel_next": 0.0, "finish_plus_next": 535.07,
                 "is_current_machine": false, "available": true, "queue": [], "en_route": [], "stay": []},
                {"machine": "M5", "travel": 125.5, "arrival": 339.27, "start": 339.27, "finish": 549.27,
                 "delta_finish": 14.2, "…": "…"}],
 "travel_source": "distances"}
```

**Lectura de la máquina M2:**
- El producto 200 está en M1 (`current_machine`) haciendo O8; le faltan 14,75 u.t. (`own_remaining`). Ahora son las 199,02 u.t.
- Hasta M2 hay 111,3 u.t. de viaje: llegaría a las 199,02 + 14,75 + 111,3 = **325,07** (`arrival`).
- M2 está libre y nadie va hacia ella (`available_in: 0`): empezaría al llegar (`start` = 325,07).
- O1 dura 210 u.t. en M2 (200 + 10 de extra promedio): terminaría a las **535,07** (`finish`).
- M5 terminaría 14,2 u.t. después (`delta_finish`), así que M2 es la mejor (`best_by_finish`).
- La operación siguiente también es O1 y M2 puede hacerla: se quedaría ahí (`next_machine: M2`, `travel_next: 0`).

### Trampas

- **Horas absolutas, no duraciones:** `finish: 535,07` es "a las 535,07", no "dentro de 535,07". Para duraciones desde ahora, restar `time`.
- **Es una estimación:** no conoce el extra al azar real (usa el promedio) ni lo que decidirán los demás productos.
- **`seq` es la operación** (igual que en `/decide`), no un número de fila.

## What-if

### Qué es

Para una decisión pendiente y **dos** máquinas posibles, la plataforma saca una foto de la planta, la carga en dos copias y simula cada opción por separado hasta que el producto entra a la máquina (o hasta un tope). Así compara lo que **realmente** pasaría, en lugar de estimarlo. El agente lo pide solo en los casos muy parejos.

### Cómo se genera, cuándo y cómo verlo

- A pedido: `POST /sessions/{id}/what-if` con `{"product", "seq", "options": [máquina A, máquina B], "max_ticks" (tope, 3.000 por defecto), "budget_ms" (presupuesto, 10.000 por defecto)}`.
- Solo con sesiones de regla 4 y con la decisión pendiente. Uno por decisión.
- La respuesta no se guarda; los contadores van a las métricas ([metricas.md](metricas.md)). El agente real copia un resumen en su `decisions.jsonl`.

### Campos generales

| Campo | Qué significa | Unidad | Valores |
|---|---|---|---|
| `status` | Cómo terminó | — | `ok`, `timeout` (se acabó el presupuesto), `skipped` (no se corrió), `error` |
| `skipped_reason` | Si no se corrió, por qué | — | `no-free-worker`, `already-used`, `entry-beyond-cap`, o `null` |
| `snapshot_tick`, `snapshot_time` | Momento de la foto | ticks, u.t. | — |
| `operation` | Operación que se decide | — | O1…O9 |
| `run_order` | En qué orden se simularon las opciones (primero la que se estima que entra antes) | — | — |
| `window_tick` | Tick en que se detuvo la primera copia; la segunda se compara en ese mismo tick | ticks | — |
| `timings_ms` | `export` (sacar la foto), `import` (cargarla, suma de las dos copias), `advance` (simular, suma), `total` | ms reales | — |
| `loads` | Productos en cola o en camino hacia cada máquina | conteo | — |
| `estimated_entry_ticks` | Ticks estimados, desde la foto, hasta que el producto entraría a cada máquina | ticks | — |
| `would_skip_entry_beyond_cap` | Si las dos entradas estimadas superan el tope (`max_ticks`) | — | `true`, `false` |
| `options` | Resultado de cada copia, en el orden pedido | — | ver abajo |

### Campos de cada opción (`options[]`)

| Campo | Qué significa | Unidad |
|---|---|---|
| `machine` | Máquina probada | — |
| `entered` | Si el producto llegó a entrar en la copia | — |
| `stop_reason` | Por qué se detuvo la copia: `entered` (entró), `cap` (tope de ticks), `stalled` (la planta se trabó), `pruned` (llegó a la ventana de la otra sin entrar), `timeout` (sin tiempo), `horizon` (fin de la corrida), `error` | — |
| `entry_tick`, `entry_time` | Cuándo entró (o cuándo se estima que entraría) | ticks, u.t. |
| `op_end_time` | Cuándo terminaría la operación en esa máquina, con el extra al azar real de la copia | u.t. |
| `entry_estimated`, `op_end_estimated` | Si esos valores son estimados (la copia se detuvo antes de que entrara) | — |
| `others` | Cómo les fue a **los demás productos** en la ventana: `window_tick`, `work` (trabajo nominal hecho, u.t.), `wait` (tiempo en planta sin proceso, u.t.), `presence` (tiempo en planta, u.t.), `finished` (cuántos terminaron) | — |
| `ticks_simulated`, `stop_tick` | Ticks simulados y tick de parada | ticks |
| `cap_reached`, `stalled`, `pruned`, `timed_out`, `skipped` | Banderas del motivo de parada | — |
| `duration_ms`, `import_ms`, `advance_ms` | Tiempo de la copia: total, de carga y de simulación | ms reales |
| `diagnostic_file` | Si la copia se trabó: archivo de diagnóstico guardado (ver abajo) | — |
| `error` | Texto del error, si lo hubo | — |
| `timings` | Campo extra que hoy llega vacío (`{}`) | — |

### Ejemplo real

En la misma sesión en vivo, para el producto 200 entre M2 y M5:

```json
{"status": "ok", "skipped_reason": null, "snapshot_tick": 642, "snapshot_time": 199.02, "operation": "O1",
 "window_tick": 1050, "run_order": ["M2", "M5"],
 "timings_ms": {"export": 114.9, "import": 1212.6, "advance": 754.2, "total": 2104.4},
 "loads": {"M2": 0, "M5": 0}, "estimated_entry_ticks": {"M2": 407, "M5": 452}, "would_skip_entry_beyond_cap": false,
 "options": [
  {"machine": "M2", "entered": true, "stop_reason": "entered", "entry_tick": 1050, "entry_time": 325.5,
   "entry_estimated": false, "op_end_time": 548.34, "op_end_estimated": false,
   "others": {"window_tick": 1050, "work": 11.78, "wait": 13.64, "presence": 25.42, "finished": 0},
   "ticks_simulated": 408, "stop_tick": 1050, "pruned": false, "duration_ms": 932.2, "…": "…"},
  {"machine": "M5", "entered": false, "stop_reason": "pruned", "entry_tick": 1095, "entry_time": 339.4,
   "entry_estimated": true, "op_end_time": 549.4, "op_end_estimated": true,
   "others": {"window_tick": 1050, "work": 11.78, "wait": 13.64, "presence": 25.42, "finished": 0},
   "ticks_simulated": 408, "stop_tick": 1050, "pruned": true, "duration_ms": 1034.6, "…": "…"}]}
```

**Lectura línea por línea:**
- `status: ok`: las dos copias corrieron.
- `snapshot_tick: 642`: la foto es del tick 642.
- `estimated_entry_ticks`: se estimó que entraría a M2 en 407 ticks y a M5 en 452, así que `run_order` simuló primero M2.
- Opción M2: el producto entró de verdad (`entered: true`) en el tick 1.050, a las 325,5 u.t., y su operación terminaría a las **548,34**. Esa copia paró ahí: `window_tick: 1050`.
- Opción M5: se simuló hasta el mismo tick 1.050 y el producto todavía no había entrado: se cortó (`pruned`). Su entrada (339,4) y su fin (**549,4**) son **estimados**.
- `others` es igual en las dos: en esta ventana la elección no cambió lo que hicieron los demás productos.
- Conclusión: M2 termina ~1 u.t. antes que M5 y no perjudica a los demás.
- `timings_ms.total: 2104`: todo el what-if tardó 2,1 s reales.

Comparado con candidates (fin estimado M2 535,07, M5 549,27), el what-if dio para M2 un fin 13 u.t. más tarde: es el extra al azar real de esa operación.

### Cuentas útiles

- **Diferencia entre opciones** = `op_end_time` de una − `op_end_time` de la otra (u.t.). Menos es mejor.
- **Efecto sobre los demás** = comparar `others.work` (más es mejor) y `others.wait` (menos es mejor) entre opciones. Solo es justo si los dos `others.window_tick` son iguales.
- **Tiempo real de cada copia** = `import_ms + advance_ms`.

### Trampas

- **Valores estimados mezclados con reales:** mirar siempre `entry_estimated` y `op_end_estimated` antes de comparar.
- **`others` solo es comparable en la misma ventana** (`others.window_tick`); si una copia se quedó sin tiempo, puede estar medida en otro tick.
- **`skipped` con `already-used`:** ya se hizo un what-if para esa decisión; no se repite.
- **`timings` dentro de cada opción** llega vacío; los tiempos útiles están en `duration_ms`, `import_ms` y `advance_ms`.

### Archivos de diagnóstico (copias trabadas)

Si una copia se traba (`stop_reason: stalled`: la planta dejó de avanzar), la plataforma guarda en `results/whatif_diagnostics/` (variable `ACLOPI_WHATIF_DIAG_DIR`) dos archivos con el mismo nombre, `stall_<session_id>_<snapshot_tick>_<máquina>_<hora>`:
- `.csv`: la foto de la planta con que empezó la copia (se puede cargar en NetLogo);
- `.json`: `session_id`, `snapshot_tick`, `product`, `seq`, `options`, `max_ticks`, `budget_ms`, más `machine`, `stall_tick` (tick en que se detectó), `quiet_ticks` (ticks sin cambios) y `machines_processing`.

En este paso no se trabó ninguna copia, así que no hay ejemplo real.
