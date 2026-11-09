# Logs de los procesos

[← Índice y glosario](README.md)

## Qué es

Los mensajes que escriben los programas mientras funcionan: pedidos HTTP recibidos, sesiones creadas, corridas guardadas, errores. Sirven para diagnosticar problemas (¿por qué se cayó una sesión?, ¿qué pidió el agente?). No son datos de la simulación.

## Cómo se genera y cuándo está disponible

- Cada proceso escribe **una línea JSON por mensaje** en su salida de errores (*stderr*): la API, cada worker, el agente simulado y el agente real.
- Disponibles **mientras exista el contenedor** (Docker guarda lo que el proceso escribió). No se guardan en la base de datos.

## Cómo verlo

Con Docker Compose (`docs/deploy-local.md`):

```powershell
docker compose logs platform          # la API y sus workers
docker compose logs agent-mock        # el agente simulado
docker compose logs agent             # el agente real (perfil "agent")
docker compose logs -f platform       # seguir en vivo
```

**Filtrar por sesión** (las líneas que mencionan una sesión llevan su `session_id`):

```powershell
docker compose logs --no-log-prefix platform | Select-String '"session_id": "34cf16b45b8745feaedba86430dcc617"'
```

Para un análisis más fino, guardar el log en un archivo y leerlo línea por línea como JSON (por ejemplo, con Python o `jq`).

## Campos de una línea

| Campo | Qué significa | Siempre | Valores |
|---|---|---|---|
| `ts` | Hora del mensaje | sí | fecha y hora UTC con milisegundos (ISO 8601) |
| `level` | Gravedad | sí | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `logger` | Parte del programa que lo escribió | sí | por ejemplo `aclopi.api.app` (pedidos HTTP), `aclopi.api.registry` (sesiones y corridas), `aclopi.api.ws` (WebSocket), `aclopi.workers.worker`, `aclopi.workers.pool`, `aclopi.sim.session` (el modelo), `uvicorn.error` (el servidor web), `httpx` (llamadas salientes, por ejemplo al agente) |
| `msg` | El mensaje | sí | texto |
| `session_id` | Sesión a la que se refiere | sí (puede ser `null`) | 32 caracteres hexadecimales |
| `service` | Qué servicio es | solo agentes | `agent`, `agent-mock` |
| `worker` | Qué worker (en sus propias líneas: `session0[g0]` = worker de sesión 0, generación 0; la generación sube con cada reinicio) | a veces | — |
| `method`, `path`, `status_code`, `elapsed_ms` | En los pedidos HTTP: método, ruta, código de respuesta y duración (ms) | en `aclopi.api.app` | — |
| `op`, `client`, `phase` | Operación del worker, cliente, fase de arranque | a veces | — |
| `exc` | Detalle técnico de un error (*traceback*) | solo en errores | texto |

## Ejemplo real

Al crear la sesión de la corrida rápida (cuatro líneas seguidas):

```json
{"ts": "2026-11-09T10:31:52.465+00:00", "level": "INFO", "logger": "aclopi.workers.worker", "msg": "setup seed=42 rule=4 modeling_type=Stochastic horizon_ticks=20000 scenario=S0 (0 events)", "session_id": "34cf16b45b8745feaedba86430dcc617", "worker": "session0[g0]"}
{"ts": "2026-11-09T10:31:52.474+00:00", "level": "INFO", "logger": "aclopi.api.registry", "msg": "Session created on worker session0", "session_id": "34cf16b45b8745feaedba86430dcc617", "worker": "session0"}
{"ts": "2026-11-09T10:31:52.475+00:00", "level": "INFO", "logger": "aclopi.api.app", "msg": "POST /sessions 201", "session_id": "34cf16b45b8745feaedba86430dcc617", "method": "POST", "path": "/sessions", "status_code": 201, "elapsed_ms": 160.96}
{"ts": "2026-11-09T10:31:52.486+00:00", "level": "INFO", "logger": "uvicorn.error", "msg": "127.0.0.1:59849 - \"WebSocket /ws/sessions/34cf16b45b8745feaedba86430dcc617\" [accepted]", "session_id": "34cf16b45b8745feaedba86430dcc617"}
```

**Lectura línea por línea:**
1. El worker de sesión 0 cargó la sesión en el modelo: semilla 42, regla 4, horizonte 20.000, sin escenario.
2. La API registró la sesión en ese worker.
3. La API respondió el `POST /sessions` con 201 (creada) en 161 ms.
4. Un cliente (aquí, el script de ejemplos) se conectó al WebSocket de esa sesión.

## Trampas

- **La hora está en UTC**, no en la hora local.
- **Muchas líneas no tienen sesión** (`session_id: null`): el arranque, la salud, los pedidos generales.
- **`httpx` es muy ruidoso**: en la ejecución de ejemplo fueron 740 de 1.083 líneas (cada llamada al agente y del agente a la plataforma). Filtrar por `logger` ayuda.
- **El token del agente nunca aparece en los logs.**
- **Si el contenedor se recrea, sus logs anteriores se pierden.**
