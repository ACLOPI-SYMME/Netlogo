# KPIs (indicadores de la planta)

[← Índice y glosario](README.md)

## Qué es

Los indicadores de cómo va la planta: cuántos productos terminaron, cuánto tardaron, cuánto trabajó cada máquina y, con un set de productos, en cuánto tiempo terminó todo el set (*makespan*). Se calculan leyendo el modelo **sin alterarlo**: leerlos no cambia la simulación.

## Cómo se genera y cuándo está disponible

- **Siempre**, para el tick actual de la sesión: `GET /sessions/{id}/kpis` los calcula en el momento, también durante una corrida (el worker atiende el pedido entre dos bloques).
- **Durante una corrida**, más o menos una vez por segundo, dentro de los mensajes `tick` y `progress` del WebSocket, y siempre en el último bloque y en `finished`.
- **Al terminar**, la corrida guardada se queda con los últimos: campo `kpis` (sin `simulated_time`) más `utilization` aparte ([corridas.md](corridas.md)).

## Cómo verlo

- `GET /sessions/{id}/kpis`.
- Página, pestaña Sesión, cuadro **KPIs**; y en la pestaña Corridas, columnas Ticks, Makespan, Flujo medio, Trabajo, Terminados y Creados, y la comparación.

## Campos

| Campo | Qué mide | Unidad | Valores |
|---|---|---|---|
| `ticks` | Tick en que se calcularon | ticks | — |
| `simulated_time` | Tiempo simulado en ese tick (`ticks × 0,31`) | u.t. | — |
| `created` | Productos que entraron a la planta hasta ahora (`finished + wip`) | conteo | — |
| `finished` | Productos terminados | conteo | — |
| `wip` | Productos en la planta, sin terminar | conteo | — |
| `throughput` | Productos terminados por unidad de tiempo: `finished / simulated_time` | productos por u.t. | 0 al inicio |
| `mean_flow_time` | Tiempo medio de un producto terminado, **desde que empezó su primera operación** (no desde que entró a la planta) hasta que terminó la última | u.t. | `null` si no terminó ninguno |
| `utilization` | Por máquina: fracción del tiempo que estuvo procesando. Una operación en curso cuenta hasta el momento del cálculo | 0 a 1 | `{"M1": …, …, "M7": …}` |
| `work_completed` | Trabajo hecho, medido en **tiempo nominal** de las operaciones: 200 u.t. por cada O1–O7 completada y 100 por cada O8–O9; una operación en curso suma la fracción que lleva. Usa el tiempo nominal, no el real, para que el azar de los tiempos no premie ni castigue a una regla | u.t. de trabajo nominal | — |
| `products_total` | Con un set: cuántos productos tiene | conteo | `null` sin set |
| `all_done` | Con un set: si todos los productos entraron y terminaron | — | `true`, `false` (siempre `false` sin set) |
| `makespan_time` | Con un set y `all_done`: cuándo terminó el último producto, desde el inicio | u.t. | `null` si no |
| `makespan_ticks` | Lo mismo en ticks: `makespan_time / 0,31`, redondeado | ticks | `null` si no |

## Ejemplo real

Al final de la corrida rápida con 5 productos (`GET /sessions/{id}/kpis`):

```json
{"ticks": 10635, "simulated_time": 3296.85, "finished": 5, "wip": 0, "created": 5,
 "throughput": 0.0015165991780032456, "mean_flow_time": 2005.824,
 "utilization": {"M1": 0.304, "M2": 0.324, "M3": 0.446, "M4": 0.376, "M5": 0.643, "M6": 0.196, "M7": 0.0},
 "work_completed": 7200.0, "products_total": 5, "all_done": true,
 "makespan_ticks": 10018, "makespan_time": 3105.58}
```

Y a los 20 s de la corrida en vivo (sin set):

```json
{"ticks": 642, "simulated_time": 199.02, "finished": 0, "wip": 1, "created": 1, "throughput": 0.0,
 "mean_flow_time": null, "utilization": {"M1": 0.428, "M2": 0.0, "…": "…"}, "work_completed": 85.25,
 "products_total": null, "all_done": false, "makespan_ticks": null, "makespan_time": null}
```

**Lectura línea por línea de la primera:**
- `ticks: 10635`, `simulated_time: 3296.85`: 10.635 × 0,31 = 3.296,85 u.t.
- `created: 5`, `finished: 5`, `wip: 0`: los 5 productos del set entraron y terminaron.
- `throughput: 0,0015`: 5 / 3.296,85. Equivale a un producto cada ~659 u.t.
- `mean_flow_time: 2005,8`: en promedio, un producto tardó ~2.006 u.t. (~6.470 ticks) entre su primera operación y la última.
- `utilization.M5: 0,643`: M5 procesó el 64 % del tiempo; `M7: 0.0`: nunca se usó.
- `work_completed: 7200`: los 5 productos hicieron trabajo nominal por 7.200 u.t. (por ejemplo, un producto con O8, cuatro operaciones O1–O7 y O9 suma 100 + 4 × 200 + 100 = 1.000).
- `all_done: true`, `makespan_ticks: 10018`: el último producto terminó en el tick 10.018. La corrida siguió hasta el 10.635 porque termina en el `go` en que el último producto **sale** de la planta, un poco después de su última operación.

## Cuentas útiles

- **Tiempo medio por producto en ticks** = `mean_flow_time / 0,31`.
- **Máquina más cargada** = la de mayor `utilization`.
- **Ritmo de trabajo** = `work_completed / simulated_time` (u.t. de trabajo nominal por u.t. simulada; cuántas máquinas trabajaron en promedio, contando el trabajo a tiempo nominal).
- **Comparar reglas con un set:** `makespan_ticks` (menos es mejor) y, si no terminó (`all_done: false`), `finished` y `work_completed`.

## Trampas

- **`mean_flow_time` no cuenta la espera antes de la primera operación** (el viaje desde la entrada hasta M1). No es "tiempo en planta".
- **`makespan_*` es `null` hasta que termine todo el set.** En la tabla de corridas aparece "no terminó".
- **`makespan_ticks` puede ser menor que `ticks`** de la corrida: el makespan es la última operación, y la corrida termina cuando el producto sale.
- **`throughput` es por u.t., no por tick ni por segundo real.** Por tick: multiplicar por 0,31.
- **Con la llegada normal de productos (sin set) entran pocos productos** en 10.000 ticks (ver el punto 2 de `docs/known-issues.md`). Valores bajos de `throughput` son normales.
- **En una corrida detenida a mitad**, los `kpis` guardados pueden ser de unos ticks antes ([corridas.md](corridas.md#trampas)).
