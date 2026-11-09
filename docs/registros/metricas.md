# Métricas de una sesión

[← Índice y glosario](README.md)

## Qué es

Contadores y tiempos de una sesión, en dos grupos: **`decisions`** (cómo le fue al agente: cuántas decisiones, de qué nivel, cuántas tardías, cuánto tardó) y **`whatif`** (cuántos what-if se pidieron, cómo terminaron y cuánto tardaron). Sirve para ver de un vistazo el comportamiento del agente sin recorrer decisión por decisión.

## Cómo se genera y cuándo está disponible

- Se actualiza **en vivo**, mientras la sesión exista: cada decisión y cada what-if suman a los contadores.
- Acumula **toda la vida de la sesión**: un reinicio (`reset`) **no** la pone a cero.
- Al terminar una corrida se copia a la corrida guardada como `decisions_summary` (sin `log`) y `whatif_summary` ([corridas.md](corridas.md)).
- Desaparece al cerrar la sesión.

## Cómo verlo

- `GET /sessions/{id}/metrics` → `{"whatif": {...}, "decisions": {...}}`.
- La página la consulta cada 2 s y muestra un resumen en el apartado "Agent" del panel Indicators de la pestaña Session.

## Grupo `decisions`

| Campo | Qué significa | Unidad | Valores |
|---|---|---|---|
| `strategy` | Estrategia de la sesión | — | `agent`, `b1`, `b1b`, `none`; `null` con las reglas 1–3 |
| `requests_sent` | Peticiones enviadas al agente = decisiones registradas + pendientes | conteo | — |
| `decide_failed` | Envíos de `/decide` que fallaron (el agente no contestó el envío) | conteo | — |
| `applied` | Decisiones aplicadas (no tardías) | conteo | — |
| `late` | Decisiones tardías | conteo | — |
| `unanswered` | Peticiones sin respuesta todavía (o que nunca la tendrán) | conteo | — |
| `by_level` | Aplicadas por nivel | conteo | claves: `code-obvious`, `llm`, `llm-what-if`, `code-fallback`, `heuristic` |
| `by_level_pct` | Lo mismo en % de `applied` | % | — |
| `sources` | Cómo asignó el modelo cada destino con la regla 4 | conteo | claves: `agent` (usó la decisión del agente), `rule3-fallback` (no había decisión a tiempo: usó la regla 3), `single-option` (había una sola máquina posible) |
| `rule3_fallback_pct` | % de asignaciones con varias máquinas posibles que terminaron en regla 3: `rule3-fallback / (agent + rule3-fallback)` | % | `null` si no hubo ninguna |
| `single_option` | Igual a `sources["single-option"]` | conteo | — |
| `latency_ms` | Latencia de las aplicadas: `mean`, `p95`, `max`, `n` | ms reales | `null` si no hubo |
| `log` | Lista de las decisiones (aplicadas y tardías): `tick`, `request_tick`, `product`, `seq` (**la operación**), `machine`, `decision_level`, `late`, `latency_ms`, `reason` | — | ver [decisiones.md](decisiones.md) |

## Grupo `whatif`

| Campo | Qué significa | Unidad |
|---|---|---|
| `requests` | What-if pedidos | conteo |
| `ok`, `timeout`, `error` | Terminados con ese `status` | conteo |
| `invalid` | Rechazados por datos inválidos (por ejemplo, la decisión ya no estaba pendiente, o la sesión no es de regla 4) | conteo |
| `skipped` | No corridos, por motivo: `no-free-worker` (no había worker de what-if libre), `already-used` (ya se hizo uno para esa misma decisión), `entry-beyond-cap` (las dos opciones entrarían más allá del tope de ticks) | conteo por motivo |
| `would_skip_entry_beyond_cap` | Cuántos se habrían saltado por `entry-beyond-cap` si ese criterio estuviera activo (hoy solo se registra) | conteo |
| `options_run` | Copias simuladas (2 por what-if completo) | conteo |
| `entered` | Copias en que el producto llegó a entrar a la máquina probada | conteo |
| `cap_reached` | Copias que llegaron al tope de ticks (`max_ticks`) | conteo |
| `stalled` | Copias que se trabaron (la planta dejó de avanzar) | conteo |
| `pruned` | Copias cortadas al llegar a la ventana de la otra sin haber entrado | conteo |
| `options_timed_out` | Copias cortadas por falta de tiempo | conteo |
| `duration_ms` | Duración total de cada what-if (`mean`, `p95`, `max`, `n`) | ms reales |
| `export_ms` | Tiempo de sacar la foto de la planta | ms reales |
| `import_ms` | Tiempo de cargar la foto en los workers de what-if (suma de las dos copias) | ms reales |
| `advance_ms` | Tiempo simulando (suma de las dos copias) | ms reales |
| `ticks_to_entry` | En las copias en que el producto entró: ticks desde la foto hasta la entrada | ticks |
| `ticks_simulated` | Ticks simulados por copia | ticks |

Los campos de tiempo valen `null` si todavía no hubo ningún what-if.

## Ejemplo real

Corrida rápida (regla 4, agente simulado, 5 productos), recortado:

```json
{"decisions": {"strategy": "agent", "requests_sent": 31, "decide_failed": 0, "applied": 31, "late": 0,
               "unanswered": 0,
               "by_level": {"code-obvious": 19, "llm": 8, "llm-what-if": 3, "code-fallback": 1},
               "by_level_pct": {"code-obvious": 61.3, "llm": 25.8, "llm-what-if": 9.7, "code-fallback": 3.2},
               "sources": {"agent": 31, "single-option": 5}, "rule3_fallback_pct": 0.0, "single_option": 5,
               "latency_ms": {"mean": 1179.4, "p95": 5313.0, "max": 7515.0, "n": 31},
               "log": [{"tick": 367, "request_tick": 366, "product": 200, "seq": 1, "machine": "M2",
                        "decision_level": "code-obvious", "late": false, "latency_ms": 453.0, "reason": "…"}]},
 "whatif": {"requests": 3, "ok": 3, "timeout": 0, "error": 0, "invalid": 0, "options_run": 6, "entered": 3,
            "pruned": 3, "cap_reached": 0, "stalled": 0, "options_timed_out": 0,
            "skipped": {"no-free-worker": 0, "already-used": 0, "entry-beyond-cap": 0},
            "duration_ms": {"mean": 5489.3, "p95": 6703.5, "max": 6703.5, "n": 3},
            "ticks_to_entry": {"mean": 859.7, "p95": 1160.0, "max": 1160.0, "n": 3}, "…": "…"}}
```

**Lectura línea por línea:**
- `requests_sent: 31`, `applied: 31`, `late: 0`, `unanswered: 0`: todas las peticiones tuvieron respuesta a tiempo (en rápido, lo esperable).
- `by_level`: 19 casos obvios para el código, 8 los decidió el LLM, 3 el LLM con what-if, 1 cayó al código por fallo del LLM.
- `sources`: el modelo usó la decisión del agente 31 veces y hubo 5 asignaciones con una sola máquina posible, que no pasaron por el agente. **36 asignaciones en total.**
- `rule3_fallback_pct: 0.0`: ninguna vez tuvo que decidir la regla 3.
- `latency_ms.p95: 5313`: el 95 % de las decisiones tardó menos de 5,3 s (el LLM simulado se configuró lento a propósito).
- `whatif.requests: 3`: corresponden a las 3 decisiones `llm-what-if`. `options_run: 6`: dos copias cada uno. `entered: 3` y `pruned: 3`: en cada what-if, una copia llegó a entrar y la otra se cortó al llegar a la ventana.

## Cuentas útiles

- **Asignaciones totales con regla 4** = `sources.agent + sources["rule3-fallback"] + sources["single-option"]`.
- **% de decisiones del LLM** = `by_level_pct.llm + by_level_pct["llm-what-if"]`.
- **% de tardías** = `late / (applied + late)`.
- **Tiempo medio por copia de what-if** ≈ `(import_ms.mean + advance_ms.mean) / 2`.

## Trampas

- **Acumula toda la sesión.** Después de un `reset`, los contadores siguen sumando. Para una corrida, mirar la corrida guardada y su lista de decisiones; con una sola corrida por sesión es lo mismo.
- **`sources` puede ir atrasado** respecto de `applied`: se lee del modelo al final de cada bloque. En la corrida en vivo del ejemplo, borrada justo después de su única decisión, quedó `applied: 1` con `sources: {}`.
- **`unanswered` incluye las que todavía se están pensando**, no solo las perdidas. Al final de una corrida, si sigue mayor que 0, esas peticiones nunca tuvieron respuesta.
- **En `log`, `seq` es la operación**; en las decisiones guardadas es el número de fila ([decisiones.md](decisiones.md#trampas)).
- **`ticks_simulated` cuenta todas las copias; `ticks_to_entry` solo las que entraron**, por eso sus `n` pueden diferir.
