# Workers de simulación (`aclopi.workers`)

Base del backend: la API (L5.2) solo habla con las simulaciones a través de este paquete.

## Por qué procesos

NetLogo solo funciona desde el hilo principal de un proceso de Python (ver `docs/known-issues.md`, punto 5). Por eso cada simulación vive en su propio proceso worker, con su propia JVM (JPype carga la JVM dentro del proceso, así que no hay procesos `java` aparte). Dentro del worker se usa `SimulationSession` siempre desde su hilo principal. El proceso que gestiona los workers (la futura API) sí puede usar hilos o asyncio, porque NetLogo no vive en él.

Configuración por defecto: 5 workers de sesión + 2 de what-if, cada uno con `-Xmx768m`.

## Módulos

| Módulo | Contenido |
|---|---|
| `protocol.py` | Formato de mensajes, operaciones, timeouts por operación y excepciones |
| `worker.py` | Proceso worker: carga, precalentamiento y bucle de pedidos |
| `handle.py` | `WorkerHandle`: pedidos y respuestas por id, seguro con varios hilos |
| `pool.py` | `WorkerPool`: arranque, asignación de sesiones, préstamo de what-if, caídas y apagado |
| `procinfo.py` | Memoria y prioridad de cada proceso (`psutil`) |

## Mensajes

Por cada worker hay dos colas `multiprocessing` (contexto `spawn`): la de pedidos y la de salida. Solo viajan datos simples (`dict`, `list`, `str`, números, `bool`, `None`).

```python
{"id": 17, "op": "step", "args": {"n": 3}}                                                # pedido
{"type": "response", "id": 17, "ok": True, "result": {...}, "elapsed_ms": 4.1}              # respuesta
{"type": "response", "id": 18, "ok": False, "error": {"type": "...", "message": "..."}, ...} # error
{"type": "push", "event": "ready", "data": {...}}                                            # sin pedido previo
```

Las respuestas y los mensajes `push` comparten la cola de salida, así llegan en el orden en que el worker los produjo. En L5.1 el único `push` es `ready` (o `fatal` si el worker no pudo arrancar); el modo en vivo (L5.3) enviará por ahí el estado y los eventos.

Operaciones: `ping`, `setup`, `step`, `state`, `events`, `layout`, `kpis`, `reset`, `export_world`, `import_world`, `shutdown`.

## Regla: ningún pedido dura más de unos pocos segundos

Un worker atiende un pedido a la vez. Mientras lo ejecuta no puede responder nada más, así que el proceso principal no puede distinguir "ocupado" de "colgado". Por eso:

- **Cada operación tiene su propio timeout** (`OP_TIMEOUTS_S`; para `step`, `5 s + 5 ms por tick`).
- **Si un pedido supera su timeout, el worker se considera colgado:** el pedido falla con `WorkerTimeout`, el worker se mata y se reinicia, y su sesión queda marcada como perdida (`SessionLost`).
- **`step` acepta como máximo `MAX_STEP_TICKS` (2000) ticks por pedido.** Un valor mayor se rechaza con un error claro.
- **Las corridas largas (modo rápido, L5.3) las hace el propio worker en bloques dentro de su bucle**, informando el progreso por la cola de salida como mensajes `push`. Nunca se hacen con un único pedido largo.

L5.2 y L5.3 deben respetar esta regla.

## Operaciones de diagnóstico (`command`, `report`)

Ejecutan código NetLogo arbitrario. Existen solo para tests y diagnóstico: el worker las rechaza salvo que el pool se haya creado con `debug=True`. **La API nunca debe crear un pool con `debug=True` ni exponer estas operaciones.**

## Caídas y errores

- **Error dentro de una operación** (por ejemplo, un comando NetLogo inválido): se devuelve como respuesta de error (`WorkerError`) y el worker sigue vivo.
- **`import_world` fallido:** `import-world` borra el mundo antes de leer el archivo. Si el import falla, el worker sigue vivo pero queda sin simulación (`ping` devuelve `configured: false`) hasta un nuevo `setup` o `import_world`. NetLogo en modo headless informa algunos archivos corruptos solo por consola, sin lanzar excepción; `SimulationSession.import_world` comprueba que el mundo cargado sea válido.
- **Worker que muere o se mata:** un hilo monitor espera los *sentinels* de los procesos y lo detecta de inmediato. Los pedidos pendientes fallan con `WorkerCrashed`, la sesión queda en `lost_sessions()` y el worker se reinicia con colas nuevas (una cola puede quedar corrupta si su proceso muere mientras la usa).
- **Proceso principal que muere:** cada worker comprueba en su bucle que el proceso padre siga vivo; si no, cierra su sesión y termina. No quedan procesos huérfanos.

## Prioridad

Los workers de what-if bajan su propia prioridad al arrancar: `nice +10` en Linux y `BELOW_NORMAL_PRIORITY_CLASS` en Windows.

## What-if entre procesos

`export_world` en un worker de sesión devuelve la ruta del archivo, dentro de la carpeta de trabajo del pool (`<work_dir>/pool_<id>/worlds`); `import_world` en un worker de what-if lo carga y lo borra. `WorkerPool.whatif_from_session(session_id)` hace las dos cosas y presta el worker de what-if. Si no hay ninguno libre, lanza `NoFreeWorker` de inmediato: los what-if no se encolan.
