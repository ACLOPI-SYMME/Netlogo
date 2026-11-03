# API REST (L5.2)

API HTTP (FastAPI) sobre el `WorkerPool` de L5.1 (`docs/workers.md`). Código en `aclopi/api/`. El contrato para la Línea A está en `contracts/openapi.json`, que se genera con `python scripts/export_openapi.py`; un test comprueba que el archivo versionado coincide con la app.

## Un solo proceso, un solo worker de uvicorn

Cada proceso de la API arranca su propio pool: 7 procesos con su JVM, unos 3,3 GB. Si se usan varios workers de uvicorn (`--workers N`), o dos APIs sobre la misma carpeta de trabajo, se arrancan varios pools, con el doble de JVM y de memoria. Para evitarlo:

- `python -m aclopi.api` fija `workers=1`, sin `reload` y sin opción para cambiarlo. No hay que lanzar la app con `uvicorn ... --workers`.
- Al arrancar, la API toma el archivo `<ACLOPI_WORK_DIR>/api.lock`, que guarda el pid, el host y la hora de inicio del proceso:
  - si otra instancia viva lo tiene, el arranque falla con un mensaje claro y el código de salida es 3;
  - un archivo que dejó un proceso muerto, u otro contenedor que comparte `results/`, se detecta como viejo y se reemplaza.

Para atender más usuarios se agregan workers al pool (`ACLOPI_N_SESSION_WORKERS`), no procesos de API.

## Arranque y salud

El pool arranca en segundo plano al levantar la API (lifespan), así que uvicorn responde desde el primer segundo. Las fases de la plataforma son:

| Fase | Significado |
|---|---|
| `starting` | Los workers están cargando y precalentando. `POST /sessions` responde 503 `platform_starting` ("plataforma iniciando"). |
| `ready` | Los 7 workers están listos. |
| `degraded` | Ya arrancó, pero algún worker se está reiniciando o falló. Se aceptan sesiones mientras haya workers libres. |
| `failed` | Algún worker no arrancó dentro de `ACLOPI_STARTUP_TIMEOUT_S`. |
| `stopping` | La API se está apagando. |

Si el arranque falla, el log JSON indica qué worker falló y por qué. Luego el pool se apaga ordenadamente y el proceso termina con **código 3**. En la nube, la política de reinicio de Docker es la que reintenta (ver README).

| Ruta | Respuesta | Uso |
|---|---|---|
| `GET /health/live` | 200 mientras el proceso responde, también durante el arranque | `HEALTHCHECK` del Dockerfile |
| `GET /health/ready` | 200 con `ready` o `degraded`; 503 con `starting`, `failed` o `stopping` | Balanceador de la nube |
| `GET /health` | Siempre 200 | Detalle: fase, sesiones activas y, por worker: rol, listo, estado, pid, memoria, reinicios y sesión |

`/health` lee el estado del pool sin hablar con los workers, así que responde aunque estén ocupados.

## Endpoints

| Método y ruta | Descripción |
|---|---|
| `POST /sessions` | Crea una sesión (`seed`, `rule` 1\|2\|3, `modeling_type`, `horizon_ticks`) en un worker libre y hace el setup. Devuelve 201 `SessionInfo` |
| `GET /sessions` | Todas las sesiones: activas, perdidas y expiradas |
| `GET /sessions/{id}` | Parámetros, último tick conocido, si terminó, estado, motivo de la pérdida y última actividad |
| `POST /sessions/{id}/step?n=` | Avanza hasta `n` ticks (1–2000); se detiene en el horizonte |
| `POST /sessions/{id}/reset` | Repite el setup con los mismos parámetros |
| `GET /sessions/{id}/state` | `platform-state` |
| `GET /sessions/{id}/events` | Eventos desde la llamada anterior. **No es idempotente**: leerlos vacía el buffer |
| `GET /sessions/{id}/layout` | `platform-layout` |
| `GET /sessions/{id}/kpis` | KPIs del estado actual; no altera la simulación |
| `DELETE /sessions/{id}` | Cierra la sesión, detiene su corrida y libera su worker (204) |
| `POST /sessions/{id}/run` | Corrida continua: `{"mode": "live", "speed": 0.5\|1\|2\|4}` o `{"mode": "fast"}` (L5.3) |
| `POST /sessions/{id}/pause` | Pausa una corrida (409 si no está corriendo) |
| `POST /sessions/{id}/resume` | Reanuda con el mismo modo y velocidad (409 si no está en pausa) |
| `WS /ws/sessions/{id}` | Transmisión en tiempo real (formato en `docs/websocket.md`) |
| `GET /sessions/{id}/candidates?product=&seq=` | Candidatas de una decisión pendiente, con su carga y su espera estimada (L5.4, `docs/whatif.md`) |
| `POST /sessions/{id}/what-if` | Prueba 2 asignaciones de una decisión en copias de la simulación, dentro de `budget_ms` (por defecto 10 s, de 2 a 15 s; el agente lo calcula con su plazo de decisión: desde M2–M7 cabe ~10 s, desde M1 no cabe con las llamadas al LLM). Solo regla 4; `docs/whatif.md` |
| `GET /sessions/{id}/metrics` | Métricas de what-if de la sesión |

**Regla 4.** `POST /sessions` acepta `rule: 4` (AI Agent). Sin decisor se comporta exactamente como la regla 3.

**KPIs** (`GET /kpis`, mensajes del WebSocket):

| KPI | Definición |
|---|---|
| `finished`, `wip`, `created` | Productos terminados, en proceso y creados (`created` = terminados + en proceso) |
| `throughput` | Terminados ÷ `Simulated.Time` |
| `mean_flow_time` | Media de (última finalización − **inicio de la primera operación**, `ProductRealStart`) de los terminados. **Se mide desde la primera operación, no desde la creación** (`docs/product-sequence.md`) |
| `utilization` | Tiempo ocupado ÷ `Simulated.Time`, por máquina |
| `work_completed` | Trabajo de proceso en tiempo **nominal** (`OperationDuration`): la operación en curso suma la fracción procesada |
| `GET /ui` | Página HTML mínima de prueba (fuera del contrato OpenAPI) |

## Corridas continuas (L5.3)

La corrida la ejecuta el worker dentro de su propio bucle, en bloques cortos: nunca es un pedido largo. Entre bloques el worker sigue atendiendo `state`, `kpis`, pausa y export para what-if.

- **En vivo:** el ritmo objetivo es 32 ticks/s × velocidad. Hay un bloque cada ~100 ms (`ACLOPI_LIVE_UPDATE_MS`) y, después de cada bloque, un mensaje con el estado y los eventos nuevos. El ritmo lo marca el worker, no el cliente.
- **Rápido:** sin límite de velocidad, en bloques de `ACLOPI_FAST_BLOCK_TICKS` ticks (1000 por defecto). Por cada bloque se envían el progreso y los eventos del bloque, sin el estado completo.
- **Resultados:** no dependen de la velocidad ni del tamaño de bloque. Una corrida hasta el final da los mismos KPIs que `SimulationSession` directo con la misma semilla (lo verifica `tests/test_live.py`).

Estados (`run_state` en `SessionInfo`, junto con `mode` y `speed`):

```
idle ──run──► running_live / running_fast ──pause──► paused ──resume──► (mismo modo y velocidad)
  ▲              │  run con otro modo o velocidad: cambia sin detenerse
  │ reset        ▼ horizonte (también por un step manual)
  └─────────── finished
```

| Pedido | idle | running_* | paused | finished |
|---|---|---|---|---|
| `step` | ✔ | 409 | ✔ | 200 con `advanced: 0` |
| `run` | ✔ | ✔ (cambia modo o velocidad) | ✔ | 409 |
| `pause` / `resume` | 409 / 409 | ✔ / 409 | 409 / ✔ | 409 / 409 |
| `events` (HTTP) | ✔ | 409 (los eventos van por WebSocket) | ✔ | ✔ |
| `reset`, `state`, `kpis`, `layout`, `DELETE` | ✔ | ✔ | ✔ | ✔ |

**Corridas rápidas simultáneas.** Como mucho `ACLOPI_MAX_FAST_RUNS` (1 por defecto). Pasado el límite, `run` (o `resume` de una corrida rápida pausada) responde 503 `fast_run_limit`. Las corridas en vivo no tienen este límite. El objetivo es que una corrida rápida, que ocupa un núcleo entero, no frene a las sesiones en vivo. **Para corridas de experimentos sin usuarios en vivo** (por ejemplo, la Línea A con regla 4) se puede subir, por ejemplo a 4.

**Vigilante.** Si una sesión corriendo no envía ningún mensaje durante 15 s (`RUN_WATCHDOG_S` × `ACLOPI_TIMEOUT_SCALE`), la API trata al worker como colgado: lo mata y la sesión queda perdida (410). Los bloques duran mucho menos de 1 s. En L5.5, el estado `waiting_decision` (esperando al agente) deberá enviar un latido para no caer en este límite.

Notas:
- `ticks` y `finished` de `SessionInfo` son el último valor conocido. Todo avance pasa por la API, así que el valor es exacto, y leerlo no consulta al worker.
- Las operaciones de diagnóstico de los workers (`command`, `report`) no existen en la API, y el pool siempre se crea con `debug=False`.
- Un `step` sobre una sesión que ya terminó responde 200 con `advanced: 0`.

## Errores

El cuerpo es `{"code": ..., "detail": ..., "session_id": ...}`. La excepción es 422, que usa el formato estándar de FastAPI.

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `session_not_found` | Id desconocido o sesión ya borrada |
| 409 | `invalid_run_state` | El pedido no está permitido en el estado de la corrida (p. ej. `step` mientras corre) |
| 410 | `session_lost` | El worker de la sesión se cayó o se colgó. `detail` dice el motivo |
| 410 | `session_expired` | La sesión se cerró por inactividad |
| 422 | – | Parámetros inválidos (`n` fuera de 1–2000, regla, tipo de modelado, campos de más) |
| 500 | `simulation_error` | Error de NetLogo o del worker, con su mensaje. El worker sigue vivo |
| 503 | `platform_starting` | La plataforma está iniciando |
| 503 | `no_free_worker` | Todos los workers de sesión están ocupados |
| 503 | `fast_run_limit` | Ya hay `ACLOPI_MAX_FAST_RUNS` corridas rápidas en curso |
| 503 | `worker_unavailable` | El worker se cayó durante la creación, o la plataforma no está lista (`failed` o `stopping`) |
| 504 | `worker_timeout` | El worker no respondió a tiempo. El pool lo reinicia y la sesión queda perdida, así que el siguiente pedido da 410 |

Las sesiones perdidas o expiradas siguen apareciendo en `GET /sessions` y responden 410 hasta que se borran con `DELETE` o pasan 24 h (como máximo se guardan 1000).

## Concurrencia

- Las llamadas a los workers son bloqueantes y corren en hilos (`anyio.to_thread`, como máximo 32 a la vez), nunca en el event loop.
- Cada sesión tiene un `asyncio.Lock`, así sus pedidos se ejecutan de a uno y en orden de llegada. Sesiones distintas avanzan en paralelo.
- Si el cliente se desconecta, el pedido en curso termina igual y el candado se libera.
- Para no entregar un worker muerto, un worker que se mató por timeout sigue figurando como ocupado hasta que el monitor del pool lo reinicia.

## Inactividad

Una sesión sin actividad durante `ACLOPI_SESSION_IDLE_TIMEOUT_S` segundos (1800 por defecto) se cierra sola: su corrida se detiene y su worker queda libre.

Qué cuenta como actividad:
- **Pedidos HTTP:** cualquier pedido a la sesión, incluido `GET /sessions/{id}`. `GET /sessions` no cuenta.
- **Clientes WebSocket:** cuentan **solo mientras la sesión está en `running_live` o `running_fast`**. En `idle`, `paused` o `finished` solo cuentan los pedidos HTTP, así una pestaña olvidada no retiene un worker para siempre.
- **Corrida sin nadie:** una sesión que corre sin nadie mirando ni pidiendo nada se cierra igual cuando vence el plazo.

Una sesión con un pedido en curso nunca se cierra.

## Configuración (variables de entorno)

| Variable | Por defecto | Descripción |
|---|---|---|
| `ACLOPI_API_HOST` | `0.0.0.0` | Interfaz donde escucha |
| `ACLOPI_API_PORT` | `8000` | Puerto |
| `ACLOPI_N_SESSION_WORKERS` | `5` | Workers de sesión |
| `ACLOPI_N_WHATIF_WORKERS` | `2` | Workers de what-if |
| `ACLOPI_SESSION_IDLE_TIMEOUT_S` | `1800` | Segundos sin pedidos antes de cerrar una sesión |
| `ACLOPI_STARTUP_TIMEOUT_S` | `300` | Tiempo máximo para que arranquen todos los workers |
| `ACLOPI_TIMEOUT_SCALE` | `1.0` | Multiplica los timeouts por operación de `protocol.py` |
| `ACLOPI_JVM_ARGS` | `-Xmx768m` | Argumentos de la JVM de cada worker |
| `ACLOPI_WORK_DIR` | `results/workers` | Carpeta de trabajo del pool y del lock |
| `ACLOPI_LOG_LEVEL` | `INFO` | Nivel de log |
| `ACLOPI_MAX_FAST_RUNS` | `1` | Corridas rápidas simultáneas (subirlo, p. ej. a 4, para experimentos sin usuarios en vivo) |
| `ACLOPI_LIVE_UPDATE_MS` | `100` | Intervalo objetivo entre bloques del modo en vivo |
| `ACLOPI_FAST_BLOCK_TICKS` | `1000` | Ticks por bloque del modo rápido |
| `ACLOPI_FAST_YIELD` | `0` | Pausa entre bloques rápidos, como fracción del tiempo del bloque |
| `ACLOPI_WS_QUEUE` | `32` | Mensajes en cola por cliente WebSocket antes de resincronizarlo |

## Logs

Cada línea es un objeto JSON en stderr con `ts`, `level`, `logger`, `msg` y `session_id`. Según el caso, también llevan `worker`, `method`, `path`, `status_code`, `elapsed_ms` o `phase`.

- **API:** el `session_id` sale de la ruta o, al crear la sesión, de la sesión nueva.
- **Workers:** también escriben JSON, con su nombre en `worker` y el `session_id` de su último setup.
- **Health:** las líneas de acceso de `/health*` van en nivel DEBUG, para que el sondeo del balanceador no llene el log.
- **Líneas generales** (arranque, apagado): llevan `session_id: null`.
