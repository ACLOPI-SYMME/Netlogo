# Contrato plataforma ↔ agente (L5.5) — PROPUESTA para la revisión de la Línea A

En el repo no había un esquema acordado para `/decide` ni para `next-machine`: `docs/rule4-decision-hook.md` y `contracts/` solo definen el gancho del modelo. La plataforma lo propone aquí; el código está en `aclopi/contracts/agent.py`. El agente simulado (`aclopi/agent_mock/`) lo implementa.

## Cuándo se llama al agente

Con la **regla 4**, cuando un producto **entra** a una máquina y su siguiente operación tiene varias máquinas posibles, el modelo deja una petición en `decision-queue` (`docs/rule4-decision-hook.md`). Con una sola máquina posible no hay petición, y el registro lo marca como `single-option`.

- **La plataforma siempre llama al agente** si la sesión tiene `strategy` = `b1`, `b1b` o `agent`. El filtro de los casos obvios vive dentro del agente.
- **`strategy: "none"`** es la regla 4 sin decisor (igual a la regla 3): no se llama a nadie.

## Plataforma → agente: `POST {ACLOPI_AGENT_URL}/decide`

```json
{"session_id": "…", "product": 201, "seq": 1, "strategy": "agent", "mode": "live",
 "ticks_per_second": 32.0, "tick": 1011, "simulated_time": 313.41,
 "operation": "O1", "origin": "M1", "candidates": ["M2", "M3", "M5", "M7"]}
```

| Campo | Significado |
|---|---|
| `mode` | `live` o `fast` |
| `ticks_per_second` | 32 × velocidad en vivo; `null` en rápido, donde la corrida espera |
| `tick`, `simulated_time` | Momento de la petición, que es la entrada a la máquina |
| `operation`, `origin`, `candidates` | Datos extra de la petición del modelo |

- **Respuesta esperada:** **202** inmediato. El agente decide después.
- **Si falla o tarda más de 2 s** (`ACLOPI_AGENT_DECIDE_TIMEOUT_S`), se registra y **no se reintenta**:
  - en vivo, el modelo aplica la regla 3 al terminar la máquina (`rule3-fallback`);
  - en rápido, la corrida espera; ver "Modo rápido".

## Agente → plataforma: `POST /sessions/{id}/next-machine`

```json
{"product": 201, "seq": 1, "machine": "M3", "decision_level": "llm",
 "reason": "texto corto", "latencies": {"total_ms": 3400, "llm_ms": [3100]}}
```

- **`decision_level`:** `code-obvious`, `code-fallback`, `llm`, `llm-what-if` o `heuristic`.
- **`latencies`:** opcional.
- **Aplicación:** se aplica en el worker con `platform-set-next-machine`, entre bloques.

| Respuesta | Cuándo |
|---|---|
| 200 `{"applied": true, "tick", "late": false, "run_state", "pending_decisions"}` | Se aplicó |
| 409 `decision_not_pending` | La seq es vieja o ya no está pendiente (por ejemplo, el producto terminó la operación). Se registra como **late** |
| 422 `invalid_option` | Máquina no capaz o desconocida. Una máquina fuera de M1–M7 se rechaza al validar el cuerpo |
| 409 `rule4_required` | La sesión no tiene regla 4 |

## Agente → plataforma: datos para decidir

- `GET /sessions/{id}/candidates?product=&seq=` (ver `docs/whatif.md`).
- `POST /sessions/{id}/what-if` (ver `docs/whatif.md`).

## Token compartido

- **Cuando está definida `ACLOPI_AGENT_TOKEN`:** `next-machine`, `candidates` y `what-if` exigen `Authorization: Bearer <token>`, y responden 401 si falta o no coincide. La plataforma manda el mismo encabezado en `/decide` y en `/health`.
- **Sin la variable (desarrollo):** no se exige.
- **Logs:** el token nunca se escribe.

## Salud: `GET {ACLOPI_AGENT_URL}/health`

- **Consulta:** la API la hace cada 30 s (`ACLOPI_AGENT_HEALTH_INTERVAL_S`). Un 200 es `ok`; cualquier otra respuesta o un timeout de 2 s es `down`.
- **Dónde aparece:** en `GET /health`, campo `agent`. **No afecta** a `/health/ready`.
- **Sesiones con `b1`, `b1b` o `agent` y el agente caído:**
  - `POST /sessions` se permite, con `warnings: ["agent_unavailable"]`;
  - `POST /run` en **vivo** se permite;
  - `POST /run` en **rápido** responde **503 `agent_unavailable`**. La estrategia se fija al crear la sesión, pero el modo recién al correr, por eso el rechazo va en `POST /run`.

## Modo en vivo

- **Recogida de peticiones:** después de cada bloque, el worker lee y vacía `decision-queue` y entrega las peticiones con el mensaje del bloque.
- **Envío:** la API llama a `/decide` sin esperar la respuesta (cliente asíncrono), así el ritmo de 32 ticks/s no cambia.
- **Sin pausa:** la simulación nunca se detiene. Si el agente no responde a tiempo, el modelo aplica la regla 3 al terminar la máquina, y la plataforma lo cuenta como `rule3-fallback`.

## Modo rápido

- **Avance:** el worker avanza con `platform-run-until-decision` hasta que hay una petición o se acaba el bloque. Con peticiones pasa a `waiting_decision`, que es un estado y no un pedido largo: sigue atendiendo pedidos y envía un latido cada 2 s.
- **Reanudación:** no avanza hasta recibir `next-machine` para **todas** las peticiones pendientes, incluidas las que salieron en el mismo tick.
- **Plazo:** lo controla la API. El vigilante de 15 s solo mira la actividad del worker, que sigue con latidos, así que esperar al agente no cuenta como cuelgue.
- **Sin respuesta en `ACLOPI_FAST_DECISION_TIMEOUT_S` (90 s):**
  - la corrida termina con `run_state: "failed"` y `reason: "agent_unavailable"`; **no** sigue con la regla 3;
  - el WebSocket envía `run_state` con ese motivo;
  - `/ui` muestra "Agente no disponible: la corrida se detuvo".

## Registro y métricas

- **Registro por decisión aplicada o tardía**, por sesión y en memoria: tick, tick de la petición, producto, seq, estrategia, nivel, máquina, motivo, latencia (de `/decide` a `next-machine`) y si llegó tarde.
- **`Decision.Source` de cada asignación del modelo** (`agent`, `rule3-fallback`, `single-option`): sale del `decision-log` que el worker lee después de cada bloque.
- **`GET /sessions/{id}/metrics` → `decisions`:**
  - aplicadas, tarde y sin respuesta;
  - conteo y % por nivel;
  - `sources`;
  - `rule3_fallback_pct`, solo sobre las asignaciones con varias máquinas (`agent` + `rule3-fallback`);
  - `single_option`;
  - latencia media, p95 y máxima;
  - `log`.
- **WebSocket:** mensaje `decision`, ver `docs/websocket.md`.

## Agente simulado (`python -m aclopi.agent_mock`, puerto 8100)

| Estrategia | Comportamiento |
|---|---|
| `b1` / `b1b` | Responde enseguida con la mejor candidata por `finish`. `b1b` usa `finish_plus_next` si viene, si no `finish`. Nivel `heuristic` |
| `agent` | Nivel sorteado con pesos configurables (`ACLOPI_MOCK_FRACTIONS`; por defecto `code-obvious` 0,5, `llm` 0,3, `llm-what-if` 0,15, `code-fallback` 0,05) |

Niveles de `agent`:

| Nivel | Qué hace |
|---|---|
| `code-obvious` | Inmediato |
| `llm` | Espera 3–4 s (`ACLOPI_MOCK_LLM_DELAY_S`) |
| `llm-what-if` | Espera ~3 s, pide un what-if con las 2 mejores por `finish` (`budget_ms` 10000 en vivo y 15000 en rápido), espera ~1,5 s y elige la de menor `op_end_time`. En vivo, si `own_remaining` en segundos menos 2 s no alcanza para ~12 s, decide como `llm`. Si el what-if responde `skipped` o `timeout`, decide sin él |
| `code-fallback` | La mejor por `finish` |

Otras opciones: `ACLOPI_MOCK_DOWN=decide|health|all` para que esos endpoints no respondan, y `ACLOPI_MOCK_SEED` para que sus sorteos sean reproducibles.

## Variables

| Variable | Por defecto | |
|---|---|---|
| `ACLOPI_AGENT_URL` | – | URL del agente; sin ella, las estrategias con decisor no tienen a quién llamar |
| `ACLOPI_AGENT_TOKEN` | – | Token compartido |
| `ACLOPI_AGENT_DECIDE_TIMEOUT_S` | 2 | Tiempo máximo de `/decide` y `/health` |
| `ACLOPI_AGENT_HEALTH_INTERVAL_S` | 30 | Cada cuánto se consulta `/health` |
| `ACLOPI_FAST_DECISION_TIMEOUT_S` | 90 | Espera máxima de una corrida rápida por sus decisiones |
