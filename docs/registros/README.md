# Registros de la plataforma

Esta carpeta explica **todos los datos que produce la plataforma**: qué es cada uno, cuándo aparece, dónde se ve, qué significa cada campo y cómo leerlo sin equivocarse. Está escrita para quien no conoce el código ni el modelo NetLogo.

Los ejemplos son **reales**. Salen de una sola ejecución de la plataforma del 9 de noviembre de 2026, con el agente simulado (`aclopi.agent_mock`):
- una corrida rápida con la regla 4 y una lista de 5 productos;
- una corrida en vivo de unos 20 s a velocidad 1×;
- una consulta de candidates y un what-if en esa sesión.

Las respuestas completas quedaron en `results/docs_examples/`, que no está en git. Los documentos muestran recortes.

## Índice

| Archivo | Fuente | Dónde se ve |
|---|---|---|
| [corridas.md](corridas.md) | Corridas guardadas | `GET /runs`, `GET /runs/{id}`, tabla `aclopi_runs`, pestaña Runs, CSV de una corrida |
| [decisiones.md](decisiones.md) | Decisiones del agente | `GET /runs/{id}/decisions`, tabla `aclopi_decisions`, panel "Latest decisions", "Decisions", CSV de decisiones, registro del agente (`decisions.jsonl`) |
| [metricas.md](metricas.md) | Métricas de una sesión | `GET /sessions/{id}/metrics` (grupos `decisions` y `whatif`) |
| [kpis.md](kpis.md) | Indicadores de la planta | `GET /sessions/{id}/kpis`, `kpis` de las corridas y de los mensajes del WebSocket |
| [eventos.md](eventos.md) | Eventos del modelo | `GET /sessions/{id}/events`, `events` de los mensajes del WebSocket |
| [websocket.md](websocket.md) | Mensajes en tiempo real | `ws://…/ws/sessions/{id}` (todos los tipos) |
| [candidates-y-whatif.md](candidates-y-whatif.md) | Respuestas de candidates y what-if | `GET /sessions/{id}/candidates`, `POST /sessions/{id}/what-if`, archivos de diagnóstico |
| [sesiones-y-estado.md](sesiones-y-estado.md) | La sesión y la foto de la planta | `GET /sessions`, `GET /sessions/{id}`, `/state`, `/layout` |
| [sets-de-productos.md](sets-de-productos.md) | Listas de productos guardadas | `/product-sets`, tabla `aclopi_product_sets`, CSV de un set |
| [salud.md](salud.md) | Estado de la plataforma | `/health`, `/health/ready`, `/health/live` |
| [logs.md](logs.md) | Logs de los procesos | `docker compose logs`, una línea JSON por mensaje |
| [csv-del-modelo.md](csv-del-modelo.md) | CSV que escribe el propio modelo | `Results/Data` y `Results/Events` |
| [escenarios.md](escenarios.md) | Campos de escenario | Solo en corridas antiguas |

Para el diseño de cada parte, ver además `docs/api.md`, `docs/websocket.md`, `docs/agent-api.md` y `docs/whatif.md`. Esta carpeta explica cómo **leer** los datos; esos documentos explican cómo **funciona** cada parte.

## Glosario

Los términos se usan en todos los archivos sin volver a explicarlos.

**La planta y el modelo**

| Término | Qué es |
|---|---|
| Modelo | El gemelo digital de la planta, escrito en NetLogo (`model/Paper.nlogo`). La plataforma lo ejecuta sin ventana y lee sus datos |
| Planta | Un monorriel con 7 máquinas (M1–M7), 94 nodos y 19 compuertas. Los productos viajan por el riel de máquina en máquina |
| Producto | Una pieza que entra a la planta, hace una lista de operaciones y sale. Hay 7 tipos: A, I, P, B, E, L y T. Cada tipo tiene su propia lista de operaciones |
| `who` / `product` | El número que identifica a un producto dentro del modelo. Los productos se numeran desde 200 en adelante (200, 201, …), porque los números menores son de nodos, máquinas y sensores |
| Operación | Un paso de trabajo: O1 a O9. O8 y O9 solo se hacen en M1 (al entrar y al salir de la planta); O1 a O7 se hacen en M2–M7, y cada una la pueden hacer varias máquinas |
| `seq` / `seq_op` | La posición de una operación dentro de la lista de operaciones del producto, contando desde 0. Ojo: según la fuente, el mismo número se llama `seq` o `seq_op` (ver [decisiones.md](decisiones.md)) |
| `priority` | Un número de 60 a 100 que tiene cada producto. El modelo lo guarda; la plataforma lo muestra y lo pasa al agente |
| Producto terminado | Uno que hizo todas sus operaciones. En el modelo queda con estado `"death"` |
| WIP | *Work in process*: productos que están en la planta y todavía no terminaron |

**El tiempo**

| Término | Qué es |
|---|---|
| Tick | Un paso de la simulación. El modelo avanza de a un tick |
| u.t. | Unidad de tiempo simulado. **1 tick = 0,31 u.t.** El tiempo simulado se llama `Simulated.Time` en el modelo y `time` o `simulated_time` en la plataforma |
| Duración de las operaciones | O8 y O9 (en M1): 100 u.t., unos 323 ticks. O1–O7 (M2–M7): 200 u.t., unos 645 ticks, más un extra al azar de 10 u.t. en promedio (modo Stochastic) |
| Horizonte | El tick en que termina una corrida (`horizon_ticks`, 10.000 por defecto) |
| Unix time | Hora real en segundos desde el 1 de enero de 1970 (UTC). Ejemplo: `1794220312.47` es el 9 de noviembre de 2026, 10:31:52 UTC. Se usa en `created_at`, `finished_at`, etc. |
| ms | Milisegundos de tiempo **real**, no simulado |

**La plataforma**

| Término | Qué es |
|---|---|
| Sesión | Una copia del modelo cargada en un proceso (un *worker*), lista para correr. Se crea con `POST /sessions` y se identifica con `session_id` |
| Corrida | Una ejecución de la sesión desde el tick 0 hasta que termina, falla o se detiene. Al terminar se guarda como un registro con `run_id` |
| Modo en vivo (`live`) | La corrida avanza a ritmo fijo para mirarla: 32 ticks por segundo a velocidad 1× (64 a 2×, 128 a 4×, 16 a 0,5×) |
| Modo rápido (`fast`) | La corrida avanza lo más rápido posible. Con la regla 4, se detiene en cada decisión a esperar al agente |
| Worker | Un proceso que tiene un modelo NetLogo cargado. Hay workers de sesión (uno por sesión) y workers de what-if (para las copias) |
| Semilla (`seed`) | El número que fija el azar de la simulación. Con la misma semilla, las mismas opciones y la misma lista de productos, la corrida sale igual |
| Set de productos | Una lista fija de productos (tipo y priority) que entra a la planta en ese orden. Sin set, los productos se generan con la semilla |
| Modo Stochastic | El único que usa la plataforma: las operaciones de M2–M7 duran su tiempo más un extra al azar |

**Las reglas y el agente**

| Término | Qué es |
|---|---|
| Regla | Cómo se elige a qué máquina va un producto al terminar una operación. 1: máquina al azar; 2: la más cercana; 3: campos potenciales; 4: el agente IA |
| Agente | El servicio que decide en la regla 4. Primero aplica código; si el caso no es obvio, pregunta a un LLM, y puede pedir un what-if. Para el usuario, la regla 4 **es** el agente |
| LLM | Modelo de lenguaje (por ejemplo, Claude) que el agente consulta en los casos dudosos |
| Agente simulado | `aclopi.agent_mock`: un reemplazo del agente para pruebas. Decide al azar entre los niveles y siempre elige la máquina que termina antes. Sus razones empiezan con "mock" |
| Decisión | La respuesta del agente: a qué máquina va el producto para su siguiente operación |
| Nivel (`decision_level`) | Quién decidió dentro del agente: `code-obvious`, `llm`, `llm-what-if`, `code-fallback` o `heuristic` (ver [decisiones.md](decisiones.md)) |
| Candidates | El cálculo de las máquinas posibles para una operación, con cuándo llegaría, empezaría y terminaría el producto en cada una |
| What-if | "¿Qué pasaría si…?": la plataforma copia la planta tal como está, simula en paralelo las dos opciones (máquina A y máquina B) y compara |
| Latencia | Cuánto tardó algo en tiempo real (ms). Para una decisión: desde que la plataforma pidió la decisión hasta que llegó |
| Tardía (`late`) | Una decisión que llegó cuando el producto ya había seguido su camino. No se aplica: en su lugar decidió la regla 3 |

**Estadística**

| Término | Qué es |
|---|---|
| `mean` | Promedio |
| `p95` | Percentil 95: el 95 % de los valores está por debajo de este número |
| `max` | Máximo |
| `n` | Cuántos valores entraron en el cálculo |
