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
| `DELETE /sessions/{id}` | Cierra la sesión y libera su worker (204) |

Notas:
- `ticks` y `finished` de `SessionInfo` son el último valor conocido. Todo avance pasa por la API, así que el valor es exacto, y leerlo no consulta al worker.
- Las operaciones de diagnóstico de los workers (`command`, `report`) no existen en la API, y el pool siempre se crea con `debug=False`.
- Un `step` sobre una sesión que ya terminó responde 200 con `advanced: 0`.

## Errores

El cuerpo es `{"code": ..., "detail": ..., "session_id": ...}`. La excepción es 422, que usa el formato estándar de FastAPI.

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `session_not_found` | Id desconocido o sesión ya borrada |
| 410 | `session_lost` | El worker de la sesión se cayó o se colgó. `detail` dice el motivo |
| 410 | `session_expired` | La sesión se cerró por inactividad |
| 422 | – | Parámetros inválidos (`n` fuera de 1–2000, regla, tipo de modelado, campos de más) |
| 500 | `simulation_error` | Error de NetLogo o del worker, con su mensaje. El worker sigue vivo |
| 503 | `platform_starting` | La plataforma está iniciando |
| 503 | `no_free_worker` | Todos los workers de sesión están ocupados |
| 503 | `worker_unavailable` | El worker se cayó durante la creación, o la plataforma no está lista (`failed` o `stopping`) |
| 504 | `worker_timeout` | El worker no respondió a tiempo. El pool lo reinicia y la sesión queda perdida, así que el siguiente pedido da 410 |

Las sesiones perdidas o expiradas siguen apareciendo en `GET /sessions` y responden 410 hasta que se borran con `DELETE` o pasan 24 h (como máximo se guardan 1000).

## Concurrencia

- Las llamadas a los workers son bloqueantes y corren en hilos (`anyio.to_thread`, como máximo 32 a la vez), nunca en el event loop.
- Cada sesión tiene un `asyncio.Lock`, así sus pedidos se ejecutan de a uno y en orden de llegada. Sesiones distintas avanzan en paralelo.
- Si el cliente se desconecta, el pedido en curso termina igual y el candado se libera.
- Para no entregar un worker muerto, un worker que se mató por timeout sigue figurando como ocupado hasta que el monitor del pool lo reinicia.

## Inactividad

Una sesión sin pedidos durante `ACLOPI_SESSION_IDLE_TIMEOUT_S` segundos (1800 por defecto) se cierra sola y su worker queda libre. Cualquier pedido a la sesión cuenta como actividad, incluido `GET /sessions/{id}`. `GET /sessions` no cuenta. Una sesión con un pedido en curso nunca se cierra.

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

## Logs

Cada línea es un objeto JSON en stderr con `ts`, `level`, `logger`, `msg` y `session_id`. Según el caso, también llevan `worker`, `method`, `path`, `status_code`, `elapsed_ms` o `phase`.

- **API:** el `session_id` sale de la ruta o, al crear la sesión, de la sesión nueva.
- **Workers:** también escriben JSON, con su nombre en `worker` y el `session_id` de su último setup.
- **Health:** las líneas de acceso de `/health*` van en nivel DEBUG, para que el sondeo del balanceador no llene el log.
- **Líneas generales** (arranque, apagado): llevan `session_id: null`.
