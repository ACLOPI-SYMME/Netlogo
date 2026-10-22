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
```

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

Los problemas conocidos del modelo que no se corrigen están en `docs/known-issues.md`.
