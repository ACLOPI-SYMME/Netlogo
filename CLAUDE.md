# Proyecto ACLOPI Annecy – Plataforma de simulación

## Contexto
- Gemelo digital de una planta (monorriel) modelado en NetLogo 6.4.0: `model/Paper.nlogo`.
- 94 nodos, 19 compuertas, 7 máquinas (M1–M7), 7 tipos de producto. Un tick = 0,31 unidades de tiempo simulado. Corrida = 10.000 ticks; al llegar a 10.000, `go` ejecuta `ExportData` (CSV en `Results/Data` y `Results/Events`) y hace `stop`.
- La única decisión del modelo es a qué máquina va un producto al terminar una operación. El chooser `Reactivity.rule` tiene: "Rule 1 - Random Machine", "Rule 2 - Nearest Machine", "Rule 3 - Potential Fields".
- Los productos terminados quedan con estado "death".
- El modelo se ejecuta headless desde Python con pynetlogo (JPype). Una JVM por proceso Python.

## Entorno
- Windows 11 para desarrollo local; más adelante, contenedores Linux.
- Python 3.12 64 bits, venv en `.venv` creado con `py -3.12 -m venv .venv` (no usar el Python por defecto del sistema, que es 3.15).
- NetLogo instalado en `C:\Program Files\NetLogo 6.4.0`; usar su JVM incluida (`runtime\bin\server\jvm.dll`).
- Rutas configurables por variables de entorno (`NETLOGO_HOME`, `JVM_PATH`) con un `.env`. Nunca rutas fijas en el código.

## Convenciones
- Código, nombres y comentarios en inglés; documentación en español.
- Python con type hints, `pathlib`, `logging` (no `print` en librerías), `pytest` para tests.
- Estructura: `model/`, `aclopi/sim/` (wrapper de NetLogo: `SimulationSession`, KPIs), `aclopi/api/` (FastAPI, más adelante), `scripts/` (scripts de validación y benchmark), `tests/`, `results/` (salidas, en .gitignore).
- El paquete Python se llama `aclopi` (no `platform`, que choca con el módulo estándar de Python) y se instala en el venv con `pip install -e .`.
- No modificar `model/Paper.nlogo` salvo que el prompt lo pida explícitamente.
- Antes de usar un nombre de variable o procedimiento de NetLogo, verificarlo leyendo `model/Paper.nlogo`; no inventar nombres.

## Forma de trabajo
- La planificación se hace fuera de este repo; los prompts llegan con tareas acotadas. No avances a tareas que el prompt no pida.
- Cuando un prompt pida analizar antes de implementar, responde el análisis y espera confirmación antes de escribir código.
- Ejecuta tú mismo los scripts y tests que escribas y muéstrame la salida real; no des por hecho que funcionan.
- Si algo falla por el entorno (rutas de NetLogo, JVM, permisos), dime qué falló y qué propones antes de cambiar la configuración.
- Usa PowerShell para los comandos.
