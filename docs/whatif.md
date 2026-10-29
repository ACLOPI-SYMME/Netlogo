# What-if y candidates (L5.4)

Estos dos endpoints permiten al código del agente (Línea A) evaluar una decisión pendiente de la regla 4 antes de tomarla. El gancho de decisión está descrito en `docs/rule4-decision-hook.md`.

## Contexto y plazos

- **Cuándo decide el agente.** Mientras el producto se procesa en una máquina: la petición se crea al **entrar** a la máquina y la respuesta se usa cuando la operación termina.
- **Plazo de decisión en vivo.** Es lo que le falta al producto en su máquina actual menos ~2 s de margen: **~8 s desde M1** y **~18 s desde M2–M7**.
- **Duración del what-if.** Como mucho 5 s (`ACLOPI_WHATIF_TIMEOUT_S`), así que cabe en esos plazos.
- **Meta de concurrencia.** **5 sesiones simultáneas**, con 2 workers de what-if compartidos.
- **Sesiones válidas.** Solo las de **regla 4**. La regla 4 sin decisor es exactamente la regla 3.

## `GET /sessions/{id}/candidates?product=&seq=`

Devuelve las máquinas candidatas para la operación `seq` del producto `product`, con su carga y su espera estimada.

- **Parámetros:** los dos son obligatorios. `seq` es la operación pendiente, `CurrentSequenceOrder + 1`.
- **Cálculo:** lo hace `aclopi.sim.candidates.compute_candidates` sobre `platform-state`, dentro del worker de la sesión. No consume azar ni altera la simulación, y mientras la sesión corre se atiende entre bloques.
- **Pedido inválido:** responde 200 con `valid: false` y `reason` (`unknown-or-finished-product`, `invalid-seq`, `seq-mismatch` o `not-in-machine`).
- **Stub provisional:** las firmas de `aclopi/sim/candidates.py` son las acordadas con la Línea A:
  - `compute_candidates(state, product, seq, static, params=CandidateParams())`;
  - `read_model_static(session)`;
  - `candidates_for_session(session, product, seq, static)`.

  El esquema (`aclopi/contracts/candidates.py`) es un stub escrito por la plataforma, porque no estaba en `main`. La Línea A lo reemplaza; la API admite campos extra, así que un esquema más rico no rompe el contrato.

```json
{"product": 201, "seq": 1, "operation": "O1", "tick": 1012, "time": 313.72, "valid": true, "reason": null,
 "candidates": [
   {"machine": "M3", "load": 0, "busy": false, "remaining_time": 0.0, "estimated_wait": 0.0, "operation_time": 210.0},
   {"machine": "M2", "load": 1, "busy": false, "remaining_time": 0.0, "estimated_wait": 210.0, "operation_time": 210.0}]}
```

| Campo | Significado |
|---|---|
| `load` | Productos en cola en la máquina o con ella como destino (`Heading.Workstation`), sin contar el que está procesando ni el propio producto |
| `estimated_wait` | Lo que le falta al trabajo en curso más los tiempos de proceso de esa carga. En Stochastic se suma la media del término aleatorio (+10 en M2–M7). No incluye el viaje |
| `operation_time` | Tiempo de proceso de la operación de este producto en esa máquina |

La lista viene ordenada por `estimated_wait`.

## `POST /sessions/{id}/what-if`

```json
{"product": 201, "seq": 1, "options": ["M2", "M3"], "max_ticks": 2000}
```

- **`options`:** exactamente **2 máquinas distintas**, elegidas por el código del agente. Si son iguales, o si no son exactamente dos, la API responde 422.
- **`max_ticks`:** tope de ticks por copia, de 1 a 5000 (2000 por defecto).

### Qué hace

1. **¿Ya probado?** Si en esta sesión ya hubo un what-if para el mismo (`product`, `seq`), responde `skipped` con `already-used`.
2. **Worker libre.** Toma prestado un worker de what-if **sin cola**: si no hay uno libre, responde `skipped` con `no-free-worker` en pocos milisegundos.
3. **Foto y validación.** El worker de la sesión, entre dos bloques, valida las dos opciones con `platform-check-next-machine`, mide la carga de las dos máquinas y toma **una sola foto** (export) del mundo. La sesión real no se detiene: en vivo sigue corriendo.
4. **Copias, una tras otra.** Cada copia se ejecuta en el worker prestado: importa la foto, fuerza la opción con `platform-set-next-machine` y avanza.
   - Corre primero la opción con menor espera estimada.
   - Dentro de la copia nunca se llama al agente: las demás decisiones las toma el código de la regla 3, y las peticiones de la copia no salen del worker.
5. **Parada de cada copia:**

   | `stop_reason` | Cuándo |
   |---|---|
   | `entered` | El producto **entra** a la máquina probada. Se leen el tick, el tiempo de entrada y el fin de la operación (`Next.Completion`), que se fija al entrar, con su parte aleatoria incluida |
   | `cap` | Llegó a `max_ticks` sin entrar |
   | `stalled` | Bloqueo: en 300 ticks ningún producto se movió y ninguna máquina estuvo procesando |
   | `pruned` | Solo la segunda copia: llegó a la ventana común sin entrar, así que ya es peor que la primera |
   | `timeout` | Se acabó el plazo de 5 s |
   | `horizon` | Terminó la corrida |

   Si el producto no entró, la entrada y el fin se **estiman** (`entry_estimated`) y la copia queda marcada. La estimación es: tiempo de la parada + lo que le falta al trabajo en curso de la máquina + los tiempos de los productos en su cola o en camino. No incluye el viaje del producto, así que es una cota inferior.

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
| `finished` | Productos terminados dentro de la ventana |
| `score` | `work − wait`; mayor es mejor |

### Respuesta (siempre 200, salvo validación)

```jsonc
{"status": "ok",                     // ok | timeout | skipped | error
 "skipped_reason": null,             // no-free-worker | already-used | plant-saturated
 "snapshot_tick": 1012, "snapshot_time": 313.72, "operation": "O1",
 "window_tick": 1987, "run_order": ["M3", "M2"],
 "timings_ms": {"export": 98, "import": 1010, "advance": 1630, "total": 2850},
 "would_skip_saturated": false, "loads": {"M2": 1, "M3": 0}, "saturation_queue": 3,
 "options": [                        // en el orden del pedido
   {"machine": "M2", "entered": true, "stop_reason": "entered",
    "entry_tick": 1987, "entry_time": 615.97, "entry_estimated": false,
    "op_end_time": 829.1, "op_end_estimated": false,
    "others": {"window_tick": 1987, "work": 431.2, "wait": 38.4, "finished": 0, "score": 392.8},
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
| 422 | – | Formato inválido (no son 2 opciones, opciones iguales, `max_ticks` fuera de rango) |

### Planta saturada (POR CONFIRMAR, solo se registra)

- **Criterio propuesto:** las **dos** máquinas probadas tienen `N` o más productos en cola o en camino hacia ellas (`ACLOPI_WHATIF_SATURATION_QUEUE`; ver el resumen de `scripts/l5/whatif_saturation.py`).
- **Datos:** salen de `platform-state` (`heading_workstation` de cada producto y `product` de cada máquina), sin consumir azar. No hizo falta agregar nada al modelo.
- **Comportamiento actual:** el what-if **no** se salta. Se registra `would_skip_saturated: true` en la respuesta y en las métricas. Para que se salte (`skipped` con `plant-saturated`) hay que poner `ACLOPI_WHATIF_SATURATION_ENFORCE=1`.

## `GET /sessions/{id}/metrics`

`{"whatif": {...}}`, para la sección 3.4 del plan:

| Grupo | Campos |
|---|---|
| Pedidos | `requests`, `ok`, `timeout`, `error`, `invalid` |
| Saltados | `skipped` por motivo, `would_skip_saturated` |
| Opciones | `options_run`, `entered`, `cap_reached`, `stalled`, `pruned`, `options_timed_out` |
| Tiempos (media, p95, máx., n) | `duration_ms`, `export_ms`, `import_ms`, `advance_ms` |
| Ticks (media, p95, máx., n) | `ticks_to_entry`, `ticks_simulated` |

## Configuración

| Variable | Por defecto | |
|---|---|---|
| `ACLOPI_WHATIF_TIMEOUT_S` | 5 | Tiempo máximo del pedido completo |
| `ACLOPI_WHATIF_STALL_TICKS` | 300 | Ticks sin movimiento ni proceso para declarar un bloqueo |
| `ACLOPI_WHATIF_CHUNK_TICKS` | 150 | Ticks entre lecturas de control de la copia |
| `ACLOPI_WHATIF_SATURATION_QUEUE` | 3 | N del criterio de planta saturada |
| `ACLOPI_WHATIF_SATURATION_ENFORCE` | 0 | 1 = saltar el what-if si la planta está saturada |
| `ACLOPI_WHATIF_DIAG_DIR` | `results/whatif_diagnostics` | Fotos de los bloqueos |

## Diseño previsto para L5.5 (todavía no implementado)

- **Latidos en modo rápido.** Mientras se espera una decisión, el worker enviará latidos para que el vigilante de 15 s no lo mate.
- **Agente que no responde en modo rápido.** Si pasan ~90 s sin respuesta, la corrida se marca como **fallida**: no sigue con la regla 3. Si la lanzó un usuario desde `/ui`, verá "agente no disponible".
- **Agente que no responde en vivo.** El modelo aplica la regla 3 por su cuenta y la plataforma mostrará el % de `rule3-fallback`.
