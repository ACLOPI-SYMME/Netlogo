# Decisiones del agente

[← Índice y glosario](README.md)

## Qué es

Con la regla 4, cada vez que un producto debe elegir máquina para su siguiente operación, la plataforma le pregunta al agente. Cada respuesta que llega queda registrada como **una fila**: qué producto, qué operación, qué máquina eligió el agente, quién decidió dentro del agente (el código o el LLM), por qué, cuánto tardó y si llegó a tiempo. Sirve para entender por qué una corrida salió como salió y para medir al agente.

## El flujo de una decisión

```
 1. El producto ENTRA a una máquina (tick = request_tick)
      │   ¿su siguiente operación la pueden hacer varias máquinas?
      ├── no → el modelo asigna la única posible ("single-option"). NO hay fila.
      └── sí → el modelo deja una petición pendiente
 2. La plataforma la lee al final del bloque y envía POST /decide al agente  ← empieza a contar latency_ms
 3. El agente decide (decision_level):
      ├── code-obvious : el código ve una máquina claramente mejor
      ├── llm          : caso dudoso; decide el LLM
      ├── llm-what-if  : caso muy parejo; el LLM pidió un what-if y decidió con él
      ├── code-fallback: el LLM falló o respondió algo inválido; decide el código
      └── heuristic    : estrategias b1 / b1b (sin LLM; solo experimentos)
 4. El agente envía POST /sessions/{id}/next-machine                          ← termina latency_ms (tick)
 5. La plataforma se lo pasa al modelo:
      ├── result "ok"  → se aplica: el producto irá a esa máquina      (late: false)
      └── el producto ya siguió su camino → NO se aplica              (late: true)
              en ese caso, cuando el producto terminó su operación, el modelo
              eligió con la regla 3 ("rule3-fallback")
```

**El plazo.** La decisión tiene que llegar antes de que el producto termine la operación que está haciendo (paso 1), porque en ese momento sale de la máquina y necesita destino:

| Máquina donde está el producto | Plazo en ticks | A 1× (32 ticks/s) | A 4× |
|---|---|---|---|
| M1 (O8, O9: 100 u.t.) | ≈ 323 | ≈ 10 s | ≈ 2,5 s |
| M2–M7 (O1–O7: 200 u.t. + extra al azar, 10 u.t. en promedio) | ≈ 645 + extra (≈ 32 en promedio) | ≈ 20 s o algo más | ≈ 5 s |

**En vivo puede haber tardías; en rápido no.** En rápido la corrida **se detiene** en cada petición y espera al agente (estado `waiting_decision`), así que la respuesta siempre llega a tiempo. Si el agente no responde en 90 s, la corrida falla con `agent_unavailable` y no hay fila.

**Lo que no deja fila:**
- las asignaciones `single-option` (una sola máquina posible): se cuentan en las métricas (`single_option`), no aquí;
- un agente real que, en vivo, ve que ya no le alcanza el tiempo y no responde: el modelo usa la regla 3 y la petición queda como "sin respuesta" en las métricas;
- una respuesta inválida (máquina que no existe o que no puede hacer la operación): la plataforma la rechaza con error 422 y no la guarda.

## Cómo se genera y cuándo está disponible

- **Durante la corrida**, en memoria de la sesión, cada vez que llega un `next-machine` aplicado o tardío. Se ven en vivo por el WebSocket (mensaje `decision`) y en `GET /sessions/{id}/metrics` (lista `log`).
- **Al terminar la corrida**, se guardan todas juntas con la corrida (tabla **`aclopi_decisions`**, clave `run_id` + `seq`; o en memoria sin DynamoDB). Desde ese momento, `GET /runs/{id}/decisions`.

## Cómo verlo

| Dónde | Qué muestra |
|---|---|
| `GET /runs/{run_id}/decisions` | Todas las decisiones de una corrida guardada, en orden |
| Página, pestaña Session, panel **"Latest decisions"** | Las 50 más nuevas de la corrida en curso, arriba la más nueva, con filtro por nivel |
| Página, pestaña Runs, botón **"Decisions"** | Todas las de una corrida guardada, de a 50 por página, con filtro por nivel y "Download CSV" |
| DynamoDB | Tabla `aclopi_decisions` |

Las dos tablas de la página tienen las columnas: Tick, Product (type), Operation, Chosen machine, Level, Reason (corta; la completa al pasar el mouse), Latency, Late.

## Campos (`GET /runs/{id}/decisions`, tabla `aclopi_decisions`)

| Campo | Qué significa | Unidad | Valores posibles |
|---|---|---|---|
| `seq` | **Número de fila** dentro de la corrida (0, 1, 2…), en el orden en que llegaron. **No es la operación** | conteo | 0… |
| `run_id` | Corrida a la que pertenece (solo en DynamoDB, que lo usa como clave) | — | — |
| `tick` | Tick en que la plataforma recibió la decisión del agente | ticks | — |
| `request_tick` | Tick en que el producto entró a la máquina y se generó la petición | ticks | — |
| `product` | Producto (`who`) | — | 200… |
| `product_type` | Tipo de producto | — | A, I, P, B, E, L, T; `null` en decisiones guardadas antes del 9 nov 2026 |
| `operation` | Operación que se decidió (la siguiente del producto) | — | O1…O9; `null` en decisiones guardadas antes del 9 nov 2026 |
| `seq_op` | Posición de esa operación en la lista del producto | — | 0… |
| `strategy` | Estrategia de la sesión | — | `agent`, `b1`, `b1b` |
| `decision_level` | Quién decidió dentro del agente | — | `code-obvious`, `llm`, `llm-what-if`, `code-fallback`, `heuristic` (ver el flujo) |
| `machine` | Máquina elegida por el agente | — | M1…M7 |
| `reason` | Explicación del agente, hasta 500 caracteres | texto | Del agente simulado: "mock …". Del agente real: por ejemplo "obvious: gaps 120 / 140 u.t." o el texto del LLM |
| `latency_ms` | Desde que la plataforma envió `/decide` hasta que recibió `next-machine` | ms reales | — |
| `agent_latencies` | Tiempos que informa el propio agente: `total_ms` (su tiempo total), `llm_ms` (lista, uno por llamada al LLM), `what_if_ms` (si pidió un what-if). Puede tener otros campos | ms reales | o `null` |
| `late` | Si llegó tarde | — | `true`, `false` |
| `result` | Respuesta del modelo al aplicarla | — | `ok` (aplicada). Tardías: `product-finished` (el producto ya terminó), `stale-seq` (la operación ya pasó), `not-in-machine` (el producto ya salió de la máquina), `seq-mismatch` (el producto está en otra operación) |

## Ejemplo real

Corrida rápida (regla 4, agente simulado, 5 productos): 31 decisiones. Las dos primeras y una del LLM:

```json
[{"seq": 0, "tick": 367, "request_tick": 366, "product": 200, "product_type": "A", "operation": "O1", "seq_op": 1,
  "strategy": "agent", "decision_level": "code-obvious", "machine": "M2",
  "reason": "mock code-obvious: best finish", "latency_ms": 453.0,
  "agent_latencies": {"total_ms": 367.1, "llm_ms": null, "what_if_ms": null}, "late": false, "result": "ok"},
 {"seq": 1, "tick": 1012, "request_tick": 1011, "product": 201, "product_type": "E", "operation": "O1", "seq_op": 1,
  "decision_level": "code-obvious", "machine": "M5", "latency_ms": 438.0, "late": false, "result": "ok", "…": "…"},
 {"seq": 2, "tick": 1050, "request_tick": 1049, "product": 200, "product_type": "A", "operation": "O1", "seq_op": 2,
  "decision_level": "llm", "machine": "M2", "reason": "mock llm: best finish", "latency_ms": 984.0,
  "agent_latencies": {"total_ms": 955.6, "llm_ms": [572.4], "what_if_ms": null}, "late": false, "result": "ok"}]
```

Corrida en vivo (1×), su única decisión:

```json
{"seq": 0, "tick": 411, "request_tick": 366, "product": 200, "product_type": "T", "operation": "O1", "seq_op": 1,
 "decision_level": "llm", "machine": "M2", "latency_ms": 1282.0, "late": false, "result": "ok", "…": "…"}
```

**Lectura línea por línea de la tercera fila de la corrida rápida (`seq: 2`):**
- `seq: 2`: es la tercera decisión de la corrida.
- `request_tick: 1049`: en ese tick el producto 200 entró a una máquina (aquí M2, para su primera O1) y pidió destino para la operación siguiente.
- `operation: O1`, `seq_op: 2`: se decidía su segunda O1, que es la operación número 2 de su lista (`O8, O1, O1, …`).
- `decision_level: llm`, `reason`: el caso no era obvio; decidió el LLM (simulado).
- `agent_latencies.llm_ms: [572.4]`: una llamada al LLM de 572 ms; el agente tardó 956 ms en total.
- `latency_ms: 984`: para la plataforma, 984 ms. La diferencia con los 956 ms del agente es el viaje por la red.
- `tick: 1050`: la decisión se registró un tick después de la petición: en rápido la corrida estaba detenida esperando.
- `machine: M2`, `result: ok`, `late: false`: se aplicó; el producto se queda en M2 para esa operación.

## Cuentas útiles

- **Ticks de respuesta** = `tick − request_tick`. Cuánto avanzó la planta mientras el agente pensaba.
  - En vivo, el ejemplo: 411 − 366 = **45 ticks**.
  - En rápido es siempre 1 (la corrida espera), así que no dice nada del agente.
- **Margen respecto del plazo** = plazo − ticks de respuesta. En el ejemplo en vivo, el producto estaba en M1 (plazo ≈ 323): le sobraron ≈ 278 ticks.
- **Velocidad estimada** = `(tick − request_tick) / (latency_ms / 1000)`, en ticks por segundo. Sirve para saber a qué velocidad iba la corrida (1× = 32 ticks/s).
  - En el ejemplo: 45 / 1,282 = **35 ticks/s ≈ 1×**. No da exacto porque la petición se lee al final de un bloque de ~3 ticks y la decisión se aplica entre bloques.
  - En rápido no tiene sentido (da 1 / 0,45 s ≈ 2 ticks/s).
- **Tiempo de red** ≈ `latency_ms − agent_latencies.total_ms`.
- **Por nivel:** contar filas por `decision_level` (la página tiene el filtro). En la corrida del ejemplo: code-obvious 19, llm 8, llm-what-if 3, code-fallback 1.
- **Tardías:** filas con `late: true`. `result` dice por qué.

## Trampas

- **`seq` cambia de significado según dónde se mire.** Es el error más común:

  | Dónde | `seq` es | La operación está en |
  |---|---|---|
  | `GET /runs/{id}/decisions`, tabla `aclopi_decisions`, CSV de la corrida | número de fila | `seq_op` |
  | Mensaje `decision` del WebSocket | número de mensaje del WebSocket | `seq_op` |
  | `POST /decide` (plataforma → agente) y `POST /next-machine` (agente → plataforma) | la operación | `seq` |
  | `GET /sessions/{id}/metrics`, lista `decisions.log` | la operación | `seq` |
  | Registro del agente real (`decisions.jsonl`) | la operación | `seq` |

- **`tick` no es cuándo decidió el agente**, sino cuándo lo recibió la plataforma.
- **`late: true` no es un error del registro**: la decisión llegó, pero el producto ya se había ido. Ese producto siguió la regla 3 en esa operación.
- **Una tardía no es lo mismo que una sin respuesta.** Las sin respuesta no tienen fila; se ven solo en las métricas (`unanswered`).
- **`single-option` no tiene fila.** Si un producto pasa por 6 operaciones y solo 2 tenían varias máquinas posibles, verás 2 filas.
- **Con el agente simulado**, los niveles salen al azar (la máquina es siempre la que termina antes) y las razones empiezan con "mock". No sirven para evaluar al agente.

## CSV de decisiones

"Decisions" → **"Download CSV"** genera `decisions-<8 primeros caracteres del run_id>.csv`, con **todas** las decisiones de la corrida en orden cronológico, sin importar el filtro de nivel:

| Columna | Campo |
|---|---|
| `tick` | `tick` |
| `product` | `product` |
| `product_type` | `product_type` |
| `operation` | `operation` |
| `machine` | `machine` |
| `level` | `decision_level` |
| `reason` | `reason` (entre comillas si tiene comas) |
| `latency_ms` | `latency_ms` |
| `late` | `late` (`true` / `false`) |

El CSV de la corrida (botón "CSV") trae otro bloque de decisiones, con `seq`, `request_tick` y `seq_op` pero sin tipo ni operación: ver [corridas.md](corridas.md#csv-de-una-corrida-botón-csv-en-la-pestaña-runs).

## Registro del lado del agente real (`decisions.jsonl`)

El agente real (`aclopi.agent`, servicio `agent` de Docker Compose) guarda su propia versión de cada decisión, con lo que vio para decidir. **El agente simulado no lo escribe.**

- **Dónde:** `results/agent/decisions.jsonl` (variable `ACLOPI_AGENT_LOG`), una línea JSON por decisión; y `GET {agente}/decisions?session_id=…` (las últimas 5.000, solo dentro de la red interna).
- **Cuándo:** al terminar cada decisión, la haya podido enviar o no.
- **Sin ejemplo real:** en este paso solo se corrió el agente simulado.

| Campo | Qué significa | Valores |
|---|---|---|
| `session_id`, `product`, `seq`, `strategy`, `mode`, `tick` | De la petición `/decide`. Aquí `seq` **es la operación** y `tick` es el `request_tick` | — |
| `level` | Igual que `decision_level` | ver arriba; `null` si no decidió |
| `triage` | Cómo clasificó el código el caso | `obvious` (lo decide el código), `uncertain` (LLM sin what-if), `very_close` (LLM, que puede pedir what-if) |
| `context_source` | De dónde sacó el contexto | `decide` (de la petición), `state` (pidió el estado de la planta) |
| `operation`, `current_machine`, `now` | Operación a decidir, máquina donde está el producto, `Simulated.Time` (u.t.) | — |
| `candidates` | Por máquina posible: `machine`, `finish`, `finish_plus_next`, `delta_finish`, `delta_finish_plus_next`, `available_in`, `travel` (u.t.; ver [candidates-y-whatif.md](candidates-y-whatif.md)) | — |
| `gap_finish`, `gap_finish_plus_next` | Diferencia entre la mejor y la segunda máquina (u.t.) | — |
| `discarded` | Máquinas descartadas por estar muy atrás | lista |
| `what_if_offered`, `what_if_requested`, `what_if_options`, `what_if_reason` | Si se le ofreció al LLM pedir un what-if, si lo pidió, con qué dos máquinas y por qué | — |
| `what_if` | Resumen de la respuesta del what-if: `status`, `skipped_reason`, y por opción `machine`, `op_end_time`, `op_end_estimated`, `others`, `skipped` | o `null` |
| `machine`, `reason` | Decisión | — |
| `estimated_start`, `estimated_finish` | Inicio y fin estimados en la máquina elegida (u.t.) | — |
| `latencies` | Tiempos internos (ms) | — |
| `response` | Código HTTP con que la plataforma respondió el `next-machine` | 200, 409 (tardía), 422 (inválida) |
| `rejected` | Si fue 409 o 422: el código de error | — |
| `error` | Si algo falló | texto |
| `total_ms` | Duración total de la decisión en el agente | ms |
