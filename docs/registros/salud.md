# Salud de la plataforma

[← Índice y glosario](README.md)

## Qué es

Tres consultas para saber si la plataforma está viva y lista: `/health/live` (¿el proceso responde?), `/health/ready` (¿se pueden crear sesiones?) y `/health` (el detalle: workers, sesiones y agente). Las usan Docker y la nube para reiniciar o enviar tráfico, y sirven para diagnosticar.

## Cómo se genera y cuándo está disponible

Siempre, calculadas en el momento de cada consulta. No se guardan. La página consulta `/health` cada 10 s para mostrar el aviso "The agent is not available".

## Cómo verlo

| Consulta | Responde | Código HTTP |
|---|---|---|
| `GET /health/live` | `{"status": "alive"}` | Siempre 200 si el proceso responde |
| `GET /health/ready` | `{"status": "<estado>"}` | 200 si está `ready` o `degraded`; 503 si está `starting`, `failed` o `stopping` |
| `GET /health` | El detalle (abajo) | Siempre 200 |

## Campos de `GET /health`

| Campo | Qué significa | Unidad | Valores |
|---|---|---|---|
| `status` | Estado general | — | `starting` (cargando los modelos, unos 70 s), `ready`, `degraded` (algún worker caído), `failed`, `stopping` |
| `uptime_s` | Tiempo desde que arrancó la API | s | — |
| `startup_s` | Cuánto tardó en quedar lista | s | `null` mientras arranca |
| `sessions.active`, `sessions.max` | Sesiones abiertas y máximo (= workers de sesión) | conteo | — |
| `workers[]` | Por worker: `slot` (número), `role` (`session` o `whatif`), `ready`, `state` (`starting`, `free`, `busy`, `restarting`, `failed`, `stopped`), `pid`, `rss_mib` (memoria, MiB), `restarts` (veces que se reinició), `session_id` (sesión que atiende) | — | — |
| `agent` | Estado del agente. **No afecta a `/health/ready`** | — | ver abajo |

Campos de `agent`:

| Campo | Qué significa | Valores |
|---|---|---|
| `configured` | Si hay un agente configurado (`ACLOPI_AGENT_URL`) | `true`, `false` |
| `status` | Si responde | `ok`, `down`, `unknown` (todavía no se probó), `not_configured` |
| `last_check`, `last_ok` | Última prueba y última vez que respondió bien | Unix time (s) |
| `last_error` | Último error | texto o `null` |
| `decide_sent`, `decide_failed` | Peticiones `/decide` enviadas y fallidas desde el arranque | conteo |

## Ejemplo real

Justo después de arrancar (2 workers de sesión y 2 de what-if):

```json
{"status": "ready", "uptime_s": 71.7, "startup_s": 70.46, "sessions": {"active": 0, "max": 2},
 "agent": {"configured": true, "status": "ok", "last_check": 1794220312.13, "last_ok": 1794220312.13,
           "last_error": null, "decide_sent": 0, "decide_failed": 0},
 "workers": [{"slot": 0, "role": "session", "ready": true, "state": "free", "pid": 6580, "rss_mib": 358.6,
              "restarts": 0, "session_id": null},
             {"slot": 2, "role": "whatif", "ready": true, "state": "free", "pid": 26080, "rss_mib": 498.4,
              "restarts": 0, "session_id": null}, "…"]}
```

**Lectura:** la plataforma está lista (`ready`) y tardó 70 s en arrancar. No hay sesiones abiertas de 2 posibles. El agente responde (`ok`). Cada worker usa entre 360 y 500 MiB y ninguno se reinició.

## Trampas

- **`ready` no garantiza que haya lugar:** si `sessions.active` = `sessions.max`, crear una sesión responde 503.
- **El agente caído no saca a la plataforma de `ready`:** se ve en `agent.status: down`. En ese estado, las corridas rápidas con regla 4 no se pueden iniciar y en vivo decide la regla 3.
- **`restarts` mayor que 0** indica que un worker se cayó o se colgó; la sesión que tenía pasó a `lost`.
- En la configuración por defecto hay 5 workers de sesión y 2 de what-if; el ejemplo usó menos.
