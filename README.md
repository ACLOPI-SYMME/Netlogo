# ACLOPI Annecy – Plataforma de simulación

Gemelo digital de una planta (monorriel) en NetLogo 6.4.0 (`model/Paper.nlogo`), ejecutado en modo headless desde Python con pynetlogo.

## Requisitos

- Windows 11
- Python 3.12 de 64 bits (el venv debe crearse con `py -3.12`, no con el Python por defecto del sistema)
- NetLogo 6.4.0 instalado en `C:\Program Files\NetLogo 6.4.0`

## Configuración del entorno (PowerShell)

Todos los comandos se ejecutan desde la raíz del repositorio.

Crear el entorno virtual:

```powershell
py -3.12 -m venv .venv
```

Activarlo (si PowerShell bloquea el script, ejecuta antes `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`):

```powershell
.\.venv\Scripts\Activate.ps1
```

Instalar las dependencias:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

El último comando instala el paquete del proyecto, `aclopi`, en modo editable para que los scripts y los tests puedan importarlo.

Crear el archivo `.env` a partir de la plantilla y ajustar las rutas si NetLogo está en otro sitio:

```powershell
Copy-Item .env.example .env
```

## Smoke test

Comprueba que NetLogo arranca en modo headless, carga el modelo, ejecuta `setup` y 100 ticks:

```powershell
python scripts\smoke_test.py
```

Las carpetas de salida `Results/Data` y `Results/Events` se crean dentro de `model/`, porque NetLogo resuelve las rutas relativas respecto a la carpeta del modelo.

## Validación y regresión

Corridas completas (10.000 ticks) de las reglas 1, 2 y 3 con semilla 42 en Stochastic, con verificación de determinismo:

```powershell
.\scripts\run_all_rules.ps1
```

Comparación de esas corridas con la línea base versionada en `tests/fixtures/baseline/` (KPIs, SHA-256 de Events y Data columna por columna):

```powershell
python scripts\compare_baseline.py
```

Tests (estructura de los reporters de plataforma, no interferencia de las lecturas y regresión contra la línea base; tarda alrededor de 1 minuto):

```powershell
python -m pytest -v
```

La regresión larga (regla 3, 100.000 ticks, semillas 42 y 7, contra `tests/fixtures/long/`) está marcada como lenta y queda fuera de la ejecución normal. Se corre aparte (unos 2 minutos):

```powershell
python -m pytest -m slow -v
```

`pytest.ini` desactiva `faulthandler`, que en Windows imprimiría como "access violation" excepciones que la JVM provoca y maneja internamente; no afecta el resultado de los tests.

## Interfaz de plataforma del modelo

Reporters de solo lectura para Python. Devuelven JSON en un string (`json.loads(str(netlogo.report(...)))`) y no consumen números aleatorios:

- `platform-layout`: nodos, conveyors (incluidas las curvas), máquinas, sensores y compuertas. Se lee una vez, después de `setup`.
- `platform-state`: estado compacto de segmentos, compuertas, máquinas y productos vivos.
- `platform-events`: eventos registrados desde la última llamada a `platform-clear-events`.

Tiempo de lectura de `platform-state`:

```powershell
python scripts\benchmark_platform_state.py
```

## Sesiones de simulación (`aclopi.sim`)

`SimulationSession` encapsula una simulación en su propio workspace de NetLogo y en su propia carpeta de salida (`results/sessions/<session_id>/`), de modo que las exportaciones de varias sesiones no se pisan. Un mismo proceso puede tener varias sesiones, siempre que se usen desde un solo hilo.

```python
from aclopi.sim import SimulationSession

with SimulationSession() as s:
    s.setup(seed=42, rule=3, modeling_type="Stochastic", horizon_ticks=10000)
    s.step(100)          # avanza hasta 100 ticks en una sola llamada
    estado = s.state()   # platform-state como dict
    eventos = s.events() # lee y vacía el buffer de eventos
    s.run_to_end()
    print(s.kpis())
```

What-if: `path = s.export_world()` y luego `otra.import_world(path)` en una o varias sesiones (o directamente `s.clone_to(otra)`). El mundo exportado conserva el estado del generador aleatorio, así que el clon continúa exactamente igual que el original.

El horizonte de la corrida es la global `horizon-ticks` del modelo (por defecto 10000), que `setup(..., horizon_ticks=...)` asigna después de `setup`.

Benchmarks de la sesión (clonado en el tick 3000 y corridas por bloques):

```powershell
python scripts\benchmark_session.py --part clone
python scripts\benchmark_session.py --part blocks
```

## Workers (`aclopi.workers`)

Cada simulación corre en su propio proceso worker (NetLogo solo funciona desde el hilo principal de un proceso). `WorkerPool` arranca 5 workers de sesión y 2 de what-if, y se comunica con ellos por colas:

```python
from aclopi.workers import WorkerPool

with WorkerPool() as pool:
    h = pool.acquire_session("demo")
    h.request("setup", seed=42, rule=3)
    h.request("step", n=100)            # máximo 2000 ticks por pedido
    with pool.whatif_from_session("demo") as w:
        w.request("step", n=1000)
    pool.release_session("demo")
```

El diseño, la regla de duración de los pedidos y el manejo de caídas están en `docs/workers.md`.

## API REST (`aclopi.api`)

API HTTP (FastAPI) sobre el pool de workers. El contrato para la Línea A está en `contracts/openapi.json`, y el diseño, los errores y la configuración en `docs/api.md`.

Qué significa cada dato que produce la plataforma (corridas, decisiones, métricas, KPIs, eventos, WebSocket, logs) y cómo leerlo: [`docs/registros/README.md`](docs/registros/README.md).

**Siempre un solo proceso con un solo worker de uvicorn.** Cada proceso de API arranca su propio pool (7 JVM, ~3,3 GB). Por eso no hay que usar `uvicorn --workers N`: varios workers de uvicorn o varias APIs sobre la misma carpeta multiplicarían las JVM y la memoria. Un archivo de bloqueo (`results/workers/api.lock`) impide arrancar una segunda instancia.

### En Windows

```powershell
python -m aclopi.api
```

- Escucha en `http://localhost:8000`, y la documentación interactiva está en `http://localhost:8000/docs`.
- `GET /health/ready` responde 503 mientras arranca el pool (alrededor de 1–1,5 min) y 200 cuando está lista. `GET /health` muestra el detalle por worker.
- La configuración va por variables de entorno (`ACLOPI_API_PORT`, `ACLOPI_N_SESSION_WORKERS`, `ACLOPI_SESSION_IDLE_TIMEOUT_S`, …; ver `docs/api.md`).

Ejemplo:

```powershell
$s = Invoke-RestMethod -Method Post http://localhost:8000/sessions -ContentType application/json -Body '{"seed": 42, "rule": 3}'
Invoke-RestMethod -Method Post "http://localhost:8000/sessions/$($s.session_id)/step?n=2000"
Invoke-RestMethod "http://localhost:8000/sessions/$($s.session_id)/kpis"
Invoke-RestMethod -Method Delete "http://localhost:8000/sessions/$($s.session_id)"
```

**Corridas continuas y tiempo real (L5.3).** `POST /sessions/{id}/run` con `{"mode": "live", "speed": 1}` (ritmo de 32 ticks/s × velocidad) o con `{"mode": "fast"}` (sin límite de velocidad). Luego, `/pause` y `/resume`. El estado, los eventos y los KPIs llegan por WebSocket en `ws://localhost:8000/ws/sessions/{id}`; el formato está en `docs/websocket.md`.

Para probarlo a mano, la página **`http://localhost:8000/ui`** permite crear una sesión, correrla en vivo o en rápido, pausarla, reanudarla, reiniciarla y cerrarla. Dibuja la planta y los productos.

Para regenerar el contrato después de cambiar la API (un test falla si quedó desactualizado):

```powershell
python scripts\export_openapi.py
```

### En el contenedor

Con los mismos límites de L4 (`--cpus=4 --cpuset-cpus=0-3 --memory=6g --memory-swap=6g`) y el puerto 8000 publicado:

```powershell
docker build -f docker/Dockerfile -t aclopi-sim .
.\docker\run_api.ps1                                      # en primer plano; Ctrl+C la detiene
.\docker\run_api.ps1 -Detach -Restart unless-stopped      # en segundo plano, con reinicio automático
```

- **Logs:** se ven con `docker logs aclopi-api`; cada línea es un objeto JSON con `session_id`.
- **Healthcheck:** el `HEALTHCHECK` de la imagen usa `/health/live`. El balanceador de la nube debe usar `/health/ready`.

**Política de reinicio recomendada.** Si algún worker no arranca dentro de `ACLOPI_STARTUP_TIMEOUT_S`, la API apaga el pool y termina con código 3.

| Política | Cuándo usarla |
|---|---|
| `restart: on-failure` (o `--restart=on-failure`) | Reintenta solo cuando la API termina con error. Es la opción conservadora |
| `restart: unless-stopped` | Además, la levanta de nuevo cuando se reinicia Docker o la máquina, salvo que se haya detenido a mano. Es la recomendada para la nube, donde la plataforma se enciende antes del horario laboral |

## Contenedor Linux (Docker)

Imagen con Python 3.12, NetLogo 6.4.0 para Linux (descargado de `downloads.netlogo.org` con su checksum verificado) y el paquete `aclopi`:

```powershell
docker build -f docker/Dockerfile -t aclopi-sim .
```

`docker/run.ps1` ejecuta un comando en el contenedor con los límites de las mediciones (`--cpus=4 --cpuset-cpus=0-3 --memory=6g --memory-swap=6g`) y monta `results/`:

```powershell
.\docker\run.ps1 bash scripts/l4/regression.sh
```

Las mediciones de concurrencia de L4 están en `scripts/l4/` y dejan sus resultados en `results/l4/`.

Los problemas conocidos del modelo que no se corrigen están en `docs/known-issues.md`.
