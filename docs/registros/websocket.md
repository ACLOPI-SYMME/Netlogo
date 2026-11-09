# Mensajes del WebSocket

[← Índice y glosario](README.md)

## Qué es

Un canal abierto entre la plataforma y quien mira una sesión (la página `/ui`, o cualquier programa). Por ahí llega, en tiempo real, todo lo que pasa: la planta avanzando, los eventos, los KPIs, las decisiones del agente y los cambios de estado. El diseño (orden, colas, cierres) está en `docs/websocket.md`; aquí se explica cómo leer cada mensaje.

## Cómo se genera y cuándo está disponible

- Solo **mientras la sesión existe**. Nada de lo que pasa por aquí se guarda tal cual: si nadie estaba conectado, se pierde (salvo lo que también va a la corrida guardada).
- Al conectarse llega primero una foto completa (`snapshot`); después, las novedades.
- El cliente no manda nada; todo se controla por HTTP.

## Cómo verlo

- Conectarse a `ws://<host>:8000/ws/sessions/{session_id}` (por ejemplo, con la librería `websockets` de Python).
- La página `/ui` lo usa para todo lo que muestra en la pestaña Sesión.

## Los mensajes, en el orden en que suelen llegar

| Tipo | Cuándo llega | Lleva `seq` |
|---|---|---|
| `snapshot` | Al conectarse, y después de un `resync` | sí (el último incluido) |
| `run_state` | Cada vez que cambia el estado de la corrida | sí |
| `tick` | En vivo: un bloque cada ~100 ms. También tras un `step` manual | sí |
| `progress` | En rápido: un bloque (1.000 ticks, o menos si para en una decisión) | sí |
| `decision` | Cada vez que llega una decisión del agente (aplicada o tardía) | sí |
| `finished` | Al terminar la corrida (horizonte o set terminado) | sí |
| `run_error` | Si un bloque falla dentro de NetLogo | sí |
| `resync` | Si el cliente se atrasó y se descartaron mensajes, o tras un reinicio | no |
| `heartbeat` | Si pasaron 5 s sin ningún otro mensaje | no |
| `closed` | Al cerrarse la sesión (o si no existe); después se corta la conexión | no |
| `scenario_event` | **Ya no se envía** (escenarios no disponibles, ver [escenarios.md](escenarios.md)) | — |

`seq` es un número correlativo por sesión, igual para todos los clientes. Un salto en `seq` quiere decir que se perdieron mensajes (solo pasa justo antes de un `resync`). Ojo: en el mensaje `decision`, `seq` es este número, **no** la operación ([decisiones.md](decisiones.md#trampas)).

## Campos por tipo

**`snapshot`**

| Campo | Qué significa |
|---|---|
| `tick` | Tick actual de la sesión |
| `session` | La información de la sesión, igual que `GET /sessions/{id}` ([sesiones-y-estado.md](sesiones-y-estado.md)) |
| `layout` | La geometría de la planta, igual que `GET /sessions/{id}/layout` |
| `state`, `state_tick` | La foto de la planta y su tick. Pueden faltar (por ejemplo, en rápido) o ser de unos ticks antes |
| `kpis` | Los últimos KPIs calculados ([kpis.md](kpis.md)) |
| `recent_events` | Los últimos 500 eventos ([eventos.md](eventos.md)) |
| `scenario`, `scenario_events` | Siempre `{"id": "S0", "params": {}}` y `[]` |

**`run_state`**

| Campo | Qué significa | Valores |
|---|---|---|
| `run_state` | Estado de la corrida | `idle` (sin correr), `running_live`, `running_fast`, `waiting_decision` (rápido, esperando al agente), `paused`, `finished`, `failed` |
| `mode`, `speed` | Modo y velocidad de la corrida en curso o pausada | `live`/`fast`; 0,5, 1, 2, 4; `null` si no corre |
| `reason` | Por qué terminó o falló | `horizon`, `all_products_done`, `agent_unavailable`, o `null` |
| `pending_decisions` | Decisiones que la corrida está esperando | conteo |
| `tick` | Tick del cambio | ticks |

**`tick`** (modo en vivo)

| Campo | Qué significa | Unidad |
|---|---|---|
| `source` | `run` en una corrida; `step` en un avance manual | — |
| `tick`, `advanced` | Tick al final del bloque y cuántos avanzó (a 1×: 3) | ticks |
| `speed` | Velocidad | 0,5 / 1 / 2 / 4 |
| `rate` | Ticks por segundo medidos en el último segundo; comparar con 32 × velocidad | ticks/s |
| `lag_ms` | Cuánto se atrasó el bloque respecto de su hora prevista | ms reales |
| `events` | Eventos nuevos del bloque | — |
| `kpis` | KPIs; solo ~1 vez por segundo (en los demás bloques falta) | — |
| `state` | Foto de la planta, para dibujarla | — |

**`progress`** (modo rápido)

| Campo | Qué significa | Unidad |
|---|---|---|
| `tick`, `advanced` | Tick al final del bloque y cuántos avanzó | ticks |
| `finished_products` | Productos terminados hasta ahora | conteo |
| `ticks_per_s` | Velocidad medida de la corrida rápida | ticks/s |
| `block_ms` | Cuánto tardó el bloque | ms reales |
| `events`, `kpis`, `state` | Igual que en `tick` (`state` como mucho una vez por segundo) | — |

**`decision`**: `product`, `product_type`, `seq_op`, `operation`, `machine`, `level`, `reason`, `late`, `latency_ms`, `tick`. Mismos significados que en [decisiones.md](decisiones.md) (aquí `level` = `decision_level`).

**`finished`**: `tick`, `reason` (`horizon` o `all_products_done`), `kpis` (los finales). Le sigue un `run_state` con `finished`.

**`run_error`**: `error` (el texto del error). La corrida pasa a `idle`.

**`resync`**: `reason` (`client_too_slow`: la cola del cliente se llenó; `reset`: la sesión volvió al tick 0) y `dropped` (mensajes descartados). Le sigue un `snapshot`.

**`heartbeat`**: `server_time` (Unix time del servidor).

**`closed`**: `code` y `reason`. `code` vale `session_lost` (se cayó el worker), `session_expired` (inactividad), `session_deleted` (se borró), `session_not_found`, `platform_starting` o `server_shutdown`.

## Ejemplo real

Corrida en vivo a 1× (recortado; `state` y `kpis` omitidos):

```json
{"type": "run_state", "seq": 1, "run_state": "running_live", "mode": "live", "speed": 1.0,
 "reason": null, "pending_decisions": 0, "tick": 0}
{"type": "tick", "seq": 2, "source": "run", "tick": 3, "advanced": 3, "speed": 1.0, "rate": null,
 "lag_ms": 15.0, "events": [], "kpis": {"…": "…"}, "state": {"…": "…"}}
{"type": "decision", "seq": 139, "product": 200, "product_type": "T", "seq_op": 1, "operation": "O1",
 "machine": "M2", "level": "llm", "reason": "mock llm: best finish", "late": false, "latency_ms": 1282.0, "tick": 411}
{"type": "run_state", "seq": 217, "run_state": "paused", "mode": "live", "speed": 1.0, "tick": 642, "…": "…"}
{"type": "closed", "code": "session_deleted", "reason": "the session was closed (DELETE)"}
```

Corrida rápida con decisiones:

```json
{"type": "progress", "seq": 2, "tick": 367, "advanced": 367, "finished_products": 0, "ticks_per_s": null,
 "block_ms": 453.0, "events": [{"tick": 366, "event": "ProductEntersMachine", "…": "…"}], "kpis": {"…": "…"}}
{"type": "run_state", "seq": 3, "run_state": "waiting_decision", "pending_decisions": 1, "tick": 367, "…": "…"}
{"type": "run_state", "seq": 4, "run_state": "running_fast", "pending_decisions": 0, "tick": 367, "…": "…"}
{"type": "decision", "seq": 5, "product": 200, "machine": "M2", "level": "code-obvious", "tick": 367, "…": "…"}
{"type": "finished", "seq": 129, "tick": 10635, "reason": "all_products_done", "kpis": {"finished": 5, "…": "…"}}
```

**Lectura línea por línea del `tick` en vivo:**
- `seq: 2`: segundo mensaje de la sesión (el 1 fue el `run_state`).
- `source: run`: viene de una corrida, no de un avance manual.
- `tick: 3`, `advanced: 3`: el bloque avanzó 3 ticks y la planta quedó en el tick 3.
- `rate: null`: todavía no hay un segundo de historia para medir. En los bloques siguientes vale ~32 (por ejemplo, 31,98).
- `lag_ms: 15`: el bloque salió 15 ms después de su hora prevista.
- `events: []`: en esos 3 ticks no pasó nada.

## Cuentas útiles

- **Velocidad real en vivo** = `rate`; debería rondar 32 × `speed`.
- **Mensajes por segundo** en vivo: ~10,7 (`tick` cada ~94 ms a 1×). En el ejemplo: 214 `tick` en ~20 s.
- **Tiempo que la corrida rápida pasó esperando al agente:** entre cada `run_state` `waiting_decision` y el `running_fast` siguiente.
- **Mensajes `run_state` en rápido con regla 4:** dos por decisión (espera y reanudación). En el ejemplo, 64 para 31 decisiones.

## Trampas

- **En rápido con decisiones, los bloques no son de 1.000 ticks:** paran en cada decisión (`advanced` 367, 645, 38…).
- **`ticks_per_s` suele ser `null` en rápido con decisiones:** cada decisión reinicia la medición de velocidad.
- **`kpis` no viene en todos los `tick`:** solo ~1 vez por segundo. Usar el último recibido.
- **El `run_state` de reanudación llega antes que el `decision`** de la misma decisión (en el ejemplo, `seq` 4 y 5): la corrida ya siguió cuando se publica la decisión.
- **Tras un `resync` hay que reemplazar todo** (estado y lista de eventos) con el `snapshot` siguiente.
- **Un cliente que se conecta tarde no recibe las decisiones anteriores**: el `snapshot` no las trae. Están en las métricas y, al terminar, en la corrida guardada.
