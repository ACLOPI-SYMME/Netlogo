# Problemas conocidos del modelo

Problemas detectados en `model/Paper.nlogo` que **no se corrigen** para no alterar el comportamiento validado de la simulación (línea base en `tests/fixtures/baseline/`, reglas 1–3, semilla 42, Stochastic). Los números de línea de los puntos 1–3 corresponden a la rama `model/l2-platform-reporters`. Los puntos 5 y 6 son problemas de la plataforma, no del modelo.

## 1. Columna 18 del CSV de Data siempre vale 0 (`"waiting"` en minúscula)

- **Dónde:** `PrintData`, línea 261:
  `sum [simulated.time - last productrealstart] of products with [Product.State != "death" and product.state = "waiting"]`.
- **Problema:** las comparaciones de texto en NetLogo distinguen mayúsculas y el estado real es `"Waiting"`. El filtro nunca encuentra productos, así que la columna 18 vale 0 en todas las filas. Esto se comprobó en las tres reglas de la línea base.
- **Riesgo si se corrige sin más:** algunos productos pasan a `"Waiting"` en los sensores antes de entrar a su primera máquina, y en ese momento `ProductRealStart` todavía está vacío. Con el filtro corregido, `last productrealstart` se evaluaría sobre `[]` y la simulación se detendría con un error de ejecución.
- **Corrección posible (pendiente de decisión):** filtrar también `not empty? ProductRealStart`, o definir qué debe medir la columna para esos productos.

## 2. Llegada de productos: solo 21 oportunidades de lanzamiento en 10.000 ticks

- **Dónde:** `Go`, línea 134:
  `if (simulated.time mod 100 <= 0.2 and count products with [Product.State != "death"] < 10 and counter = 0) [create.product ...]`.
- **Problema:** `Simulated.Time` avanza 0,31 por tick y se redondea a 2 decimales. La condición `mod 100 <= 0.2` solo se cumple **21 veces** en 10.000 ticks (en 100,13; 300,08; 500,03; …; 3100,0). Además hacen falta menos de 10 productos vivos y la zona de entrada vacía, así que se crean todavía menos productos.
- **Efecto observado (semilla 42, Stochastic):**

  | Regla | Productos terminados | WIP final |
  |---|---|---|
  | 1 – Random Machine | 1 | 10 |
  | 2 – Nearest Machine | 2 | 10 |
  | 3 – Potential Fields | 5 | 6 |

  El throughput es muy bajo en las tres reglas, y con las reglas 1 y 2 el WIP queda en el tope de 10.
- **Pendiente:** confirmar si la intención era una llegada cada 100 unidades de tiempo, por ejemplo con un temporizador en lugar de `mod`.

## 3. `ProductExitsMachine` escribe `"XXX"` / `"YYY"` en el CSV de Events

- **Dónde:** `EventMachineExit`, líneas 196–197.
- **Problema:** en los eventos de salida, las columnas 6 (orden de secuencia) y 7 (operación) del CSV contienen los textos fijos `"XXX"` y `"YYY"`. El CSV no dice qué operación terminó.
- **Mitigación en L2:** el `event-buffer` de la plataforma (`platform-events`) registra la operación que realmente terminó (`item (CurrentSequenceOrder - 1) ProductOperations`). El CSV no se cambió, para que siga siendo idéntico a la línea base.

## 4. ✅ RESUELTO (L4b, rama `model/l4b-p6-fix`). Ralentización en corridas largas (P6): coste cuadrático en los productos terminados

- **Corrección aplicada:** en `Product.Movement`, `product.ahead` (`count products in-cone 10 50`) se calcula solo dentro de `if (product.state = "Movement") [...]`. El `ask products` no se filtra, así que se baraja el mismo agentset en el mismo orden.
- **Verificación, en Windows y en el contenedor Linux:**
  - `compare_baseline.py` con las 3 reglas: idéntico a la línea base;
  - los 29 tests pasan;
  - regresión larga (`pytest -m slow`): regla 3, 100.000 ticks, semillas 42 y 7, con KPIs y SHA-256 de Events y Data idénticos a `tests/fixtures/long/`, que se generaron antes del cambio;
  - en todos los puntos de control del perfil (cada 5.000 ticks), los productos y las filas de `EventFrameInfo` y `DataFrameInfo` son los mismos.
- **Resultado (contenedor con los límites de L4, regla 3, semilla 42):** la corrida de 100.000 ticks baja de 104,2 s a 46,0 s (2,27× más rápida). Con 83 productos terminados, el coste pasa de 1,47 a 0,33 ms/tick. El coste por tick ya no crece con los productos terminados.

Descripción original del problema:

- **Dónde:** `Product.Movement`, `ask products [ let product.ahead count products in-cone 10 50 ... if (product.state = "Movement" and product.ahead <= 1) [...] ]`.
- **Problema:** los productos terminados no se eliminan; quedan todos apilados en (2,2), con estado `"death"`. En cada tick, cada producto, terminado o no, calcula `count products in-cone 10 50` **antes** de comprobar su estado. Entre productos apilados en el mismo punto, cada uno cuenta a todos los demás, así que el coste crece con el cuadrado de los terminados.
- **Medición (L4, contenedor Linux, regla 3, semilla 42, 100.000 ticks):** de 0,72–0,85 ms/tick entre los ticks 15.000 y 40.000 a 1,47 ms/tick en el tick 100.000, con 83 productos terminados, todos en (2,2). Sin contar el calentamiento de la JVM, el ajuste `ms/tick = 0,755 + 1,21e-4 · death²` da R² = 0,96; el lineal da R² = 0,88. Las demás variables (productos totales, filas de `EventFrameInfo` y de `DataFrameInfo`) crecen a la vez y dan ajustes parecidos; lo que apunta a los terminados es el mecanismo, no la estadística.
- **Por qué no se filtró el `ask`:** con `ask products with [Product.State != "death"]` cambiaría el tamaño del agentset que se baraja y se **rompería** la igualdad con la línea base.

## 5. Plataforma: llamadas a NetLogo desde hilos de Python distintos del principal

- **Error (L4, contenedor Linux):** cualquier `report` hecho desde un hilo de Python que no es el principal falla, incluso con un solo hilo:
  `java.lang.NullPointerException: Cannot invoke "java.lang.ClassLoader.loadClass(String)" because "this.normalClassLoader" is null` en `org.nlogo.generate.CustomClassLoader.loadClass`, durante la compilación del reporter.
- **Causa probable (no verificada):** el compilador de NetLogo carga las clases que genera con el *context class loader* del hilo. Los hilos que JPype conecta a la JVM lo tienen en `null`.
- **Consecuencia:** hoy cada workspace se usa desde el hilo principal de su proceso. La organización por procesos funciona; la organización por hilos no.

## 6. Plataforma: finales de línea de los CSV según el sistema operativo

NetLogo escribe los CSV con el separador de línea del sistema: CRLF en Windows y LF en Linux. La línea base se generó en Windows. `compare_baseline.py` compara el SHA-256 del contenido con los finales de línea normalizados a LF, de modo que la regresión vale en las dos plataformas.

## 7. ✅ RESUELTO (P11, rama `model/p11-printdata`). `PrintData` fallaba sin productos vivos

**Qué pasaba.** `PrintData`, que agrega una fila al CSV de Data cada `Interval.Logs` u.t. (`Go`, línea 173), calcula medias sobre los productos vivos. Con un set de productos que se termina (`docs/product-sets.md`) puede no quedar ninguno, y NetLogo falla con `Can't find the mean of a list with no numbers`. Con la llegada normal de productos nunca pasa, porque siempre hay alguno vivo.

**Cálculos afectados**, todos en `PrintData`:

| Línea (antes del cambio) | Cálculo | Columnas de Data (desde 0) |
|---|---|---|
| 281, 283 | `mean [xcor]` y `mean [ycor]` de los vivos | 7 y 9 |
| 282, 284 | Desviación estándar de x e y (`mean` dentro de `sqrt`) | 8 y 10 |
| 319 | Relación media de operaciones completadas: suma ÷ `count` de los vivos (división por 0) | Bloque 2, última columna |
| 427–430 | Las mismas medias y desviaciones del bloque 5 (KPI) | Las cuatro columnas correspondientes del bloque 5 |

El resto ya funciona con un conjunto vacío:
- las sumas y los conteos dan 0;
- la entropía itera una lista vacía;
- `EventPassing` está protegido con `any?`;
- `PotentialFields` y las colas usan listas vacías;
- `ExportData` solo escribe.

En Python, `aclopi/sim/kpis.py` ya devolvía `mean_flow_time = None` sin terminados (`ifelse-value any?`).

**Cambio.** Cada uno de esos valores es `ifelse-value (any? products with [Product.State != "death"]) [expresión original] [0]`. Esas columnas valen **0** en las filas de Data escritas cuando no hay productos vivos, lo que solo pasa al final de una corrida con set de productos.

**Garantía:** con productos vivos la expresión es la original y `any?` no usa números aleatorios, así que la línea base no cambia (`compare_baseline.py` OK).

**Plataforma.** Las sesiones con lista siguen terminando en el `go` exacto en que termina el último producto (`SimulationSession.step_product_list`, `run_reason: "all_products_done"`). Ya no es para evitar este error, sino para que la corrida termine en el tick correcto. Test: `tests/test_product_list.py::test_p11_printdata_with_no_product_alive`.
