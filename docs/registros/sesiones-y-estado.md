# La sesión y la foto de la planta

[← Índice y glosario](README.md)

Tres fuentes de la sesión **en curso**: su ficha (`GET /sessions/{id}`), la foto de la planta en este tick (`/state`) y la geometría fija de la planta (`/layout`). Ninguna se guarda: existen mientras existe la sesión.

## Ficha de la sesión (`SessionInfo`)

### Qué es, cuándo y cómo verla

Los parámetros de la sesión y el estado de su corrida. La devuelve `POST /sessions` al crearla, `GET /sessions/{id}` en cualquier momento y `GET /sessions` (todas, también las cerradas hace poco); también viaja dentro del `snapshot` del WebSocket. La página muestra partes: el id, la semilla usada y el estado.

### Campos

| Campo | Qué significa | Unidad | Valores |
|---|---|---|---|
| `session_id` | Identificador | — | 32 caracteres hexadecimales |
| `status` | Si la sesión sigue viva | — | `active`, `lost` (se cayó su worker), `expired` (cerrada por inactividad) |
| `lost_reason` | Si está `lost` o `expired`, por qué | texto | — |
| `parameters` | `seed`, `rule`, `modeling_type`, `horizon_ticks` | — | ver [corridas.md](corridas.md) |
| `seed_source` | `user` o `random` | — | — |
| `strategy` | Regla 4: `agent`, `b1`, `b1b`, `none` | — | `null` con reglas 1–3 |
| `ticks` | Último tick conocido | ticks | — |
| `finished` | Si la corrida terminó | — | — |
| `run_state` | Estado de la corrida | — | `idle`, `running_live`, `running_fast`, `waiting_decision`, `paused`, `finished`, `failed` |
| `run_reason` | Por qué terminó o falló | — | `horizon`, `all_products_done`, `agent_unavailable`, `null` |
| `mode`, `speed` | Modo y velocidad de la corrida en curso o pausada | — | `null` si no corre |
| `pending_decisions` | En rápido: decisiones que la corrida espera | conteo | — |
| `warnings` | Avisos al crear la sesión | — | por ejemplo `agent_unavailable` (el agente no responde; en vivo actuará la regla 3) |
| `product_set_id`, `products_total`, `products_hash` | Set de productos usado, su largo y su huella | — | `null` sin set |
| `scenario`, `scenario_summary` | Siempre S0 y `{applied: 0, skipped: 0}` ([escenarios.md](escenarios.md)) | — | — |
| `last_run_id` | Última corrida guardada de esta sesión | — | — |
| `watchers` | Clientes conectados por WebSocket | conteo | — |
| `worker_slot` | Número del worker que la atiende | — | — |
| `created_at`, `last_activity` | Creación y último pedido | Unix time (s) | — |

### Ejemplo real (al terminar la corrida rápida)

```json
{"session_id": "34cf16b45b8745feaedba86430dcc617", "status": "active",
 "parameters": {"seed": 42, "rule": 4, "modeling_type": "Stochastic", "horizon_ticks": 20000},
 "ticks": 10635, "finished": true, "run_state": "finished", "run_reason": "all_products_done",
 "strategy": "agent", "pending_decisions": 0, "warnings": [], "seed_source": "user",
 "product_set_id": "251c64c8e403434daedf9577668305f5", "products_total": 5, "products_hash": "56fbcd4c…",
 "last_run_id": "acfcb7cbb35a43119f472d1fe812f81f", "mode": null, "speed": null, "watchers": 1,
 "worker_slot": 0, "created_at": 1794220312.47, "last_activity": 1794220368.22, "…": "…"}
```

Lectura: la sesión sigue viva (`active`) aunque la corrida terminó (`finished`); su corrida quedó guardada como `last_run_id`; había 1 cliente mirando.

### Trampas

- **`status` es de la sesión; `run_state` es de la corrida.** Una sesión `active` puede tener la corrida `finished`.
- **Una sesión se cierra sola** tras 30 min sin pedidos (`ACLOPI_SESSION_IDLE_TIMEOUT_S`): pasa a `expired` y su corrida, si estaba a medias, se guarda como `stopped`.

## Foto de la planta (`GET /sessions/{id}/state`)

### Qué es, cuándo y cómo verla

Dónde está cada producto y qué hace cada máquina en el tick actual. Es lo que dibuja la página. Se pide con `GET /sessions/{id}/state` en cualquier momento (durante una corrida, entre dos bloques) y viaja como `state` en los mensajes del WebSocket. Leerla no altera la simulación.

### Campos principales

| Campo | Qué significa | Valores |
|---|---|---|
| `tick`, `time` | Momento de la foto | ticks, u.t. |
| `finished` | Productos terminados | conteo |
| `terminado` | Si el modelo ya ejecutó su cierre (escribir sus CSV) | `"No"`, `"Si"` |
| `products_created` | Productos creados | conteo |
| `fixed_product_sequence`, `product_sequence_seed` | Si los productos salen de una secuencia fija sacada de la semilla, y de cuál | — |
| `product_list_active`, `product_list_length`, `product_list_next` | Con un set: si está activo, su largo y la posición del próximo producto en entrar (desde 1) | — |
| `segments` | Productos por tramo del riel (W1, W2…) | conteo |
| `gates` | Estado de las compuertas: `node`, `kind` (`merge`, …), `active` | — |
| `machines[]` | Por máquina: `id`, `name`, `state` (`Machine.Processing` o `Idle`), `operation` y `product` en curso, `remaining` (u.t. que le faltan), `next_completion` (hora de fin, u.t.; 100000000 si está libre), `queue` (productos en cola), `attractiveness` (valor interno de la regla 3) | — |
| `products[]` | Por producto vivo: `id`, `type`, `state` (`Waiting`, `Movement`, `Processing.Product`, …), `x`, `y`, `last_node`, `next_node`, `next_operation`, `heading_workstation` (máquina a la que va), `sequence_order` (operación actual, desde 0), `operations` (lista completa), `created` (u.t.), `ai_next_machine` y `ai_decision_seq` (última decisión del agente y para qué operación), `decision_source` (`agent`, `rule3-fallback`, `single-option` o vacío) | — |

Ejemplo real (corrida en vivo, tick 642, recortado):

```json
{"tick": 642, "time": 199.02, "terminado": "No", "finished": 0, "products_created": 1,
 "machines": [{"id": 186, "name": "M1", "state": "Machine.Processing", "operation": "O8", "product": 200,
               "remaining": 14.75, "next_completion": 213.77, "queue": [], "attractiveness": 63492.06},
              {"id": 187, "name": "M2", "state": "Idle", "operation": null, "product": null,
               "remaining": null, "next_completion": 100000000, "queue": [], "attractiveness": 1000000}],
 "products": [{"id": 200, "type": "T", "state": "Waiting", "x": 115, "y": 106, "next_operation": "O8",
               "heading_workstation": "M1", "sequence_order": 0, "operations": ["O8", "O1", "O1", "O2", "O4", "O9"],
               "created": 100.13, "ai_next_machine": "M2", "ai_decision_seq": 1, "decision_source": ""}]}
```

Lectura: el producto 200 (tipo T) está en M1 haciendo O8 y le faltan 14,75 u.t.; el agente ya decidió que su operación 1 (O1) será en M2 (`ai_next_machine`, `ai_decision_seq`).

**Trampas:** un producto que está siendo procesado puede figurar con `state: "Waiting"` (como en el ejemplo); para saber si está en una máquina, mirar `machines[].product`. `next_completion: 100000000` significa "libre", no una hora real.

## Geometría de la planta (`GET /sessions/{id}/layout`)

Fija: no cambia durante la sesión. Viaja en el `snapshot`. Sirve para dibujar la planta.

| Campo | Qué es |
|---|---|
| `nodes` | Los nodos del riel: `id`, `x`, `y` (94 en el modelo) |
| `conveyors` | Los tramos entre nodos: `from`, `to`, `shape`, `default_position`, `active` |
| `curves` | Las curvas: `turn`, `radius` |
| `machines` | Las 7 máquinas: `id`, `name`, `x`, `y` |
| `sensors` | Los sensores: `id`, `sensor_id`, `x`, `y` |
| `switches` | Los nodos donde el riel se divide (`diverge`) o se junta |
