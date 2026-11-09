# Corridas guardadas

[← Índice y glosario](README.md)

## Qué es

Cada corrida que termina, falla o se detiene deja **un registro** con sus parámetros, su resultado y resúmenes de lo que pasó. Sirve para comparar corridas (por ejemplo, la regla 3 contra el agente con la misma semilla y el mismo set) y para repetirlas.

## Cómo se genera y cuándo está disponible

- Se escribe **una vez por corrida**, en el momento en que:
  - la corrida **termina** (`status: "finished"`): llega al horizonte o terminan todos los productos del set;
  - la corrida **falla** (`status: "failed"`): por ejemplo, el agente no respondió en modo rápido;
  - la corrida **se detiene** (`status: "stopped"`): se borró la sesión, se reinició, o la sesión se perdió o expiró.
- Una sesión que se crea y nunca corre no deja registro.
- Disponible **al terminar la corrida**, unos instantes después (se guarda en segundo plano). Nunca durante la corrida.
- Dónde se guarda:
  - con DynamoDB (Docker Compose y la nube): tabla **`aclopi_runs`**, clave `run_id`. Persiste entre reinicios;
  - sin DynamoDB (desarrollo local): en memoria. **Se pierde al reiniciar la API.**

## Cómo verlo

| Dónde | Qué muestra |
|---|---|
| `GET /runs` | Lista, de la más nueva a la más vieja. Filtros: `seed`, `strategy`, `rule`, `product_set_id`, `scenario`; paginación: `limit` (1–500, por defecto 50) y `cursor` |
| `GET /runs/{run_id}` | Un registro completo |
| Página `/ui`, pestaña **Corridas** | Tabla con filtros, "Comparar seleccionadas", "Ver decisiones", "Repetir" y "CSV" |
| DynamoDB | Tabla `aclopi_runs` (ver `docs/deploy-local.md`) |

`GET /runs` responde `{"runs": [...], "next_cursor": "..."}`. Si `next_cursor` no es `null`, hay más: se pide de nuevo con `cursor=<ese valor>`.

## Campos

| Campo | Qué significa | Unidad | Valores posibles |
|---|---|---|---|
| `run_id` | Identificador de la corrida | — | 32 caracteres hexadecimales |
| `session_id` | Sesión que hizo la corrida. Una sesión puede tener varias corridas (después de un reinicio) | — | 32 caracteres hexadecimales |
| `created_at` | Cuándo empezó la corrida | Unix time (s) | — |
| `finished_at` | Cuándo se guardó el registro | Unix time (s) | — |
| `status` | Cómo terminó | — | `finished`, `failed`, `stopped` |
| `reason` | Por qué terminó | — | Con `finished`: `horizon` (llegó al horizonte), `all_products_done` (terminaron todos los productos del set). Con `failed`: `agent_unavailable` (en rápido, el agente no respondió a tiempo). Con `stopped`: `deleted` (se borró la sesión), `reset` (se reinició), `lost: <motivo>` (se cayó el worker), `expired: <motivo>` (la sesión se cerró por inactividad) |
| `ticks` | Tick en que quedó la corrida | ticks | — |
| `rule` | Regla usada | — | 1, 2, 3, 4 |
| `strategy` | Solo con la regla 4: quién decidió | — | `agent` (el agente; lo que crea la página), `b1`, `b1b` (referencias de los experimentos), `none` (sin decisor, solo en tests); `null` con las reglas 1–3 |
| `seed` | Semilla usada | — | entero de −2.147.483.648 a 2.147.483.647 |
| `seed_source` | De dónde salió la semilla | — | `user` (la dio quien creó la sesión), `random` (la sorteó la plataforma) |
| `modeling_type` | Modo del modelo | — | `Stochastic` (el único que usa la página) o `Deterministic` |
| `horizon_ticks` | Horizonte pedido | ticks | 1 a 1.000.000 |
| `mode` | Modo de la corrida | — | `live`, `fast` |
| `product_set_id` | Set guardado que se usó, si se eligió uno | — | id de un set, o `null` |
| `products_hash` | Huella (SHA-256) de la lista de productos. Dos corridas con el mismo valor usaron exactamente la misma lista | — | 64 caracteres hexadecimales, o `null` sin lista |
| `products` | Copia de la lista de productos usada, en orden de entrada (`type`, `priority`) | — | lista, o `null` sin lista |
| `kpis` | Indicadores finales: `ticks`, `finished`, `created`, `wip`, `work_completed`, `mean_flow_time`, `throughput`, `products_total`, `all_done`, `makespan_ticks`, `makespan_time` | ver [kpis.md](kpis.md) | — |
| `utilization` | Fracción del tiempo que cada máquina estuvo procesando | 0 a 1 | `{"M1": …, …, "M7": …}` |
| `decisions_summary` | Resumen de las decisiones del agente. Mismos campos que `decisions` de [metricas.md](metricas.md), sin la lista `log` | — | — |
| `whatif_summary` | Resumen de los what-if. Mismos campos que `whatif` de [metricas.md](metricas.md) | — | — |
| `scenario_id`, `scenario`, `scenario_events`, `scenario_summary` | Escenario de la corrida. Hoy siempre `S0`, `{}` y vacío | — | ver [escenarios.md](escenarios.md) |

## Ejemplo real

La corrida rápida de regla 4 con 5 productos (recortado):

```json
{"run_id": "acfcb7cbb35a43119f472d1fe812f81f",
 "session_id": "34cf16b45b8745feaedba86430dcc617",
 "created_at": 1794220312.815675, "finished_at": 1794220367.9808335,
 "status": "finished", "reason": "all_products_done", "ticks": 10635,
 "rule": 4, "strategy": "agent", "seed": 42, "seed_source": "user",
 "modeling_type": "Stochastic", "horizon_ticks": 20000, "mode": "fast",
 "product_set_id": "251c64c8e403434daedf9577668305f5",
 "products": [{"type": "A", "priority": 70}, {"type": "E", "priority": 90}, "…3 más"],
 "kpis": {"ticks": 10635, "finished": 5, "created": 5, "wip": 0, "work_completed": 7200.0,
          "mean_flow_time": 2005.82, "throughput": 0.0015166, "products_total": 5,
          "all_done": true, "makespan_ticks": 10018, "makespan_time": 3105.58},
 "utilization": {"M1": 0.304, "M2": 0.324, "M3": 0.446, "M4": 0.376, "M5": 0.643, "M6": 0.196, "M7": 0.0},
 "decisions_summary": {"applied": 31, "late": 0, "by_level": {"code-obvious": 19, "llm": 8, "llm-what-if": 3, "code-fallback": 1}, "…": "…"},
 "whatif_summary": {"requests": 3, "ok": 3, "…": "…"}}
```

Y la corrida en vivo, que se detuvo al borrar la sesión:

```json
{"status": "stopped", "reason": "deleted", "ticks": 642, "mode": "live", "seed": 7,
 "products": null, "kpis": {"ticks": 633, "finished": 0, "created": 1, "wip": 1, "…": "…"}}
```

**Lectura línea por línea de la primera:**
- `status: finished`, `reason: all_products_done`: terminó bien, porque los 5 productos del set terminaron. No llegó al horizonte (20.000).
- `ticks: 10635`: en ese tick terminó. `created_at` → `finished_at`: 55 s reales.
- `rule: 4`, `strategy: agent`: decidió el agente (aquí, el simulado).
- `seed: 42`, `seed_source: user`: la semilla la dimos nosotros; con ella y la misma lista se puede repetir.
- `mode: fast`: modo rápido; la corrida esperó al agente en cada decisión.
- `kpis.finished: 5`, `created: 5`, `wip: 0`: entraron 5 productos y los 5 terminaron.
- `kpis.makespan_ticks: 10018` (3105,58 u.t.): el último producto terminó en el tick 10.018. Es la medida principal de los experimentos: **menos es mejor**.
- `kpis.mean_flow_time: 2005,82` u.t.: en promedio, cada producto tardó eso desde que empezó su primera operación hasta que terminó.
- `utilization.M5: 0,643`: M5 estuvo procesando el 64 % del tiempo; M7 no se usó.
- `decisions_summary.applied: 31`: el agente tomó 31 decisiones, ninguna tardía.

## Cuentas útiles

- **Duración real de la corrida:** `finished_at − created_at` (s).
- **Makespan en tiempo:** `makespan_time` (u.t.) ≈ `makespan_ticks × 0,31`.
- **Comparar dos corridas:** solo tiene sentido si tienen la misma `seed` y el mismo `products_hash` (o ambas sin lista). La página agrupa así al comparar.
- **% de decisiones por LLM:** `decisions_summary.by_level_pct.llm + by_level_pct["llm-what-if"]`.

## Trampas

- **`ticks` y `kpis.ticks` pueden diferir.** Los KPIs se calculan como mucho una vez por segundo, así que en una corrida detenida a mitad de camino (en el ejemplo, borrada) son los últimos calculados: `ticks: 642` pero `kpis.ticks: 633`. En una corrida `finished` coinciden.
- **`decisions_summary` cuenta toda la sesión, no solo esta corrida.** Si la sesión se reinició y volvió a correr, el resumen incluye también las decisiones de las corridas anteriores de la misma sesión. La lista de decisiones (`GET /runs/{id}/decisions`) sí es solo de esta corrida. Con una corrida por sesión (lo normal desde la página) coinciden.
- **`makespan_*`, `products_total` y `all_done` solo tienen valor con un set de productos.** Sin set valen `null` y `false`.
- **En memoria, se pierde todo al reiniciar la API.** Solo con DynamoDB las corridas persisten.
- **Orden con DynamoDB:** `GET /runs` lee la tabla por páginas y ordena cada página por fecha; entre páginas el orden puede no ser perfecto.
- **"Repetir" no repite el modo:** crea una sesión nueva con la misma regla, estrategia, semilla, horizonte y lista; el modo (en vivo o rápido) se elige al iniciarla.

## CSV de una corrida (botón "CSV" en la pestaña Corridas)

Un archivo `run-<8 primeros caracteres del run_id>.csv` con dos bloques separados por una línea vacía:

1. **Parámetros y KPIs**, en formato `field,value`, una fila por campo:
   `run_id`, `status`, `reason`, `rule`, `strategy`, `seed`, `seed_source`, `horizon_ticks`, `mode`, `product_set_id`, `products_hash`, `ticks`, `scenario_id`, y luego `kpi.<nombre>` por cada campo de `kpis`.
2. **Decisiones**, con la cabecera `seq,tick,request_tick,product,seq_op,machine,decision_level,late,latency_ms,reason`. Los campos son los de [decisiones.md](decisiones.md); `reason` va entre comillas.

Para un CSV de decisiones con tipo de producto y operación, usar "Ver decisiones" → "Descargar CSV" ([decisiones.md](decisiones.md#csv-de-decisiones)).
