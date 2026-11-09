# WebSocket de sesión (L5.3)

`ws://<host>:<puerto>/ws/sessions/{session_id}`

Transmite en tiempo real lo que pasa en una sesión. Es lo que consume la interfaz web.

- **Control por HTTP.** El cliente **no envía nada**: crear, correr, pausar o reiniciar la sesión se hace con la API HTTP (`docs/api.md`). Si envía algo, se ignora.
- **Varios clientes.** Pueden mirar la misma sesión a la vez y reciben exactamente los mismos mensajes.
- **Desconexión.** Desconectarse no afecta la corrida.

La página de prueba `GET /ui` usa todo lo que se describe aquí.

## Orden de los mensajes

1. **Primero, siempre `snapshot`:** una foto completa de la sesión.
2. **Después, las actualizaciones** (`tick`, `progress`, `decision`, `run_state`, `finished`, `run_error`), todas posteriores a la foto.
3. **Si el cliente se atrasa** (ver "Cliente lento"): `resync` y luego un `snapshot` nuevo.
4. **Si no hubo nada que enviar durante 5 s:** `heartbeat`.
5. **Al cerrarse la sesión:** `closed` con el motivo, y el servidor cierra la conexión.

Todos los mensajes son objetos JSON con `type`. Los que publica la sesión (`tick`, `progress`, `decision`, `run_state`, `finished`, `run_error`) llevan además `seq`, correlativo por sesión e igual para todos los clientes. Un salto en `seq` significa que el cliente perdió mensajes, cosa que solo ocurre antes de un `resync`. `snapshot.seq` es el último `seq` que la foto ya incluye.

## Mensajes

### `snapshot`

```json
{"type": "snapshot", "seq": 41, "tick": 1290, "state_tick": 1290,
 "session": { ...SessionInfo, igual que GET /sessions/{id}... },
 "layout": { ...platform-layout, igual que GET /sessions/{id}/layout... },
 "state": { ...platform-state, igual que GET /sessions/{id}/state... },
 "kpis": { ...igual que GET /sessions/{id}/kpis... },
 "recent_events": [ {"tick": 1288, "event": "...", "who": 230, ...}, ... ],
 "scenario": {"id": "S0", "params": {}},
 "scenario_events": []}
```

- **`scenario` y `scenario_events`:** los escenarios no están disponibles en la plataforma (`docs/scenarios.md`): siempre valen S0 y `[]`. Se mantienen por compatibilidad.

- **`recent_events`:** los últimos 500 eventos de la sesión (desde el último `reset`). El cliente reemplaza su lista con estos.
- **`state` y `state_tick`:** solo vienen si hay un estado conocido. En modo rápido no se transmite el estado, así que pueden faltar o ser anteriores a `tick`.
- **`kpis`:** son los últimos calculados (como mucho ~1 s de antigüedad durante una corrida).

### `tick`: bloque del modo en vivo, o step manual con clientes mirando

```json
{"type": "tick", "seq": 42, "source": "run", "tick": 1293, "advanced": 3, "speed": 1.0,
 "rate": 32.1, "lag_ms": 2.4,
 "events": [ {"tick": 1291, "event": "...", ...} ],
 "kpis": { ... },
 "state": { ...platform-state... }}
```

- **Cadencia:** en vivo hay un `tick` cada ~100 ms, con `advanced` ticks (velocidad 1×: 3 ticks cada 94 ms).
- **`source`:** vale `"run"` en una corrida y `"step"` en un `POST /step` manual. El step manual no trae `rate`, `lag_ms`, `speed` ni `kpis`, y su `events` va vacío: los eventos de un step manual llegan en el siguiente bloque de corrida, o por `GET /events`.
- **`rate`:** ticks/s medidos en el último segundo, para comparar con 32 × velocidad.
- **`lag_ms`:** cuánto se atrasó este bloque respecto de su hora prevista. Si el worker se atrasa más de 1 s, retoma el ritmo desde ese momento en lugar de acelerar para ponerse al día.
- **`events`:** son los eventos **nuevos** del bloque (event-buffer), sin repetidos.
- **`kpis`:** viene aproximadamente una vez por segundo, y siempre en el último bloque.

Formato de un evento:

```json
{"tick": 1291, "event": "...", "who": 230, "product_type": "...", "location": "...",
 "operation": "...", "next_operation": "...", "destination": "...", "time": 400.21}
```

### `progress`: bloque del modo rápido

```json
{"type": "progress", "seq": 90, "tick": 23000, "advanced": 1000, "finished_products": 12,
 "ticks_per_s": 2150.4, "block_ms": 465.0,
 "events": [ ...los eventos del bloque... ],
 "kpis": { ... }}
```

- **Cadencia:** un mensaje por bloque de `ACLOPI_FAST_BLOCK_TICKS` ticks (1000 por defecto).
- **`state` como mucho una vez por segundo** (L5.4), y siempre en el último bloque. Con eso el canvas de `/ui` muestra la corrida rápida como un video acelerado. Si un bloque tarda más de 1 s, todos los bloques traen `state`.
- **`events`:** llegan **todos**, en lote (~18 eventos por cada 1000 ticks). La API además los conserva para la persistencia de L5.6.
- **`kpis`:** viene aproximadamente una vez por segundo.

### `scenario_event`: ya no se envía

Los escenarios no están disponibles en la plataforma (`docs/scenarios.md`), así que ninguna sesión publica este mensaje. El formato queda descrito en `docs/scenarios.md` para los experimentos.

### `run_state`: cambio de estado de la corrida

```json
{"type": "run_state", "seq": 43, "run_state": "paused", "mode": "live", "speed": 1.0, "tick": 1293}
```

- **Estados:** `run_state` vale `idle`, `running_live`, `running_fast`, `waiting_decision` (rápido con decisor, esperando al agente), `paused`, `finished` o `failed`.
- **`reason`:** por qué terminó, por ejemplo `agent_unavailable` en `failed`. `pending_decisions` dice cuántas decisiones se esperan.
- **`mode` y `speed`:** son los de la corrida en curso o pausada, y valen `null` en `idle` y `finished`.

### `decision`: se aplicó (o llegó tarde) una decisión del agente (L5.5)

```json
{"type": "decision", "seq": 61, "product": 201, "product_type": "A", "seq_op": 1, "operation": "O2",
 "machine": "M3", "level": "llm", "reason": "M3 termina antes que M5", "late": false, "latency_ms": 3412.0,
 "tick": 1113}
```

- `product_type` y `operation` (la operación decidida) vienen de la petición enviada al agente; `reason` es la razón que dio el agente (puede ser `null`).
- La página lo usa para el panel "Últimas decisiones" (las 50 más nuevas arriba, con filtro por nivel).
- Las métricas agregadas están en `GET /sessions/{id}/metrics` (`decisions`). Nota: el campo `seq` del mensaje es el número de mensaje del WebSocket, y el `seq` de la operación decidida va en **`seq_op`**.

### `finished`: la corrida llegó al horizonte

```json
{"type": "finished", "seq": 120, "tick": 10000, "reason": "horizon", "kpis": { ...KPIs finales... }}
```

`reason` vale `horizon`, o `all_products_done` con un set de productos (L5.6). Le sigue un `run_state` con `finished` y el mismo `reason`.

### `run_error`: un bloque falló dentro de NetLogo

```json
{"type": "run_error", "seq": 77, "error": "NetLogoException: ..."}
```

La corrida se detiene (`run_state` pasa a `idle`) y el worker sigue vivo.

### `resync`: el cliente perdió mensajes

```json
{"type": "resync", "reason": "client_too_slow", "dropped": 33}
```

Le sigue **inmediatamente** un `snapshot`, y el cliente debe reemplazar su estado y su lista de eventos.

| `reason` | Cuándo ocurre |
|---|---|
| `client_too_slow` | La cola del cliente se llenó (ver abajo) |
| `reset` | La sesión se reinició con `POST /reset` y vuelve al tick 0 |

### `heartbeat`

```json
{"type": "heartbeat", "server_time": 1793098812.123}
```

Se envía si no hubo otro mensaje en 5 s, por ejemplo con la sesión en `idle` o `paused`. Si un cliente no recibe nada durante ~15 s, debe considerar perdida la conexión y reconectarse. El navegador no ve los pings del protocolo; el servidor sí los usa para detectar clientes caídos (cada 10 s, con 10 s de espera).

### `closed`: la sesión terminó para este cliente

```json
{"type": "closed", "code": "session_lost", "reason": "worker process exited unexpectedly (exit code 1)"}
```

Después el servidor cierra la conexión con este código:

| `code` | Código de cierre | Cuándo |
|---|---|---|
| `session_lost` | 4410 | El worker se cayó o se colgó. `GET /sessions/{id}` muestra el motivo y los demás endpoints responden 410 |
| `session_expired` | 4410 | La sesión se cerró por inactividad |
| `session_deleted` | 4404 | Se borró con `DELETE /sessions/{id}` |
| `session_not_found` | 4404 | El id no existe, por ejemplo al conectarse |
| `platform_starting` | 4503 | La plataforma todavía está arrancando |
| `server_shutdown` | 1001 | La API se está apagando |

Al conectarse a una sesión que ya está perdida, expirada o que no existe, el cliente recibe solo el `closed`.

## Cliente lento

- **Colas separadas.** Cada cliente tiene su propia cola de `ACLOPI_WS_QUEUE` mensajes (32 por defecto) y su propia tarea de envío. El worker y los demás clientes nunca esperan a un cliente.
- **Si la cola se llena:** se descartan los mensajes encolados, que son estados intermedios y no hacen falta, y el cliente recibe `resync` y un `snapshot` con el estado más reciente y los últimos 500 eventos. Así recupera los eventos que no llegó a recibir.
- **Si un envío no se completa en 10 s:** se cierra la conexión de ese cliente.

## Tamaños y ancho de banda (medidos)

Ver `results/l5/bench_live.json`:

Medidos en el contenedor, con regla 3, Stochastic y 60 s a 1×:

| Mensaje | Tamaño medio |
|---|---|
| `tick` | ~2,8 KB |
| `snapshot` | ~15,8 KB (con el layout) |
| `progress` | ~3,3 KB (con eventos y KPIs) |
| `run_state` | ~90 B |
| `finished` | ~370 B |

Una sesión en vivo a 1× usa **~27–28 KB/s por cliente**, unos 10,7 mensajes por segundo. Una corrida rápida usa ~5 KB/s.
