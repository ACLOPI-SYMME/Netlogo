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

## 4. Ralentización en corridas largas (P6): coste cuadrático en los productos terminados

- **Dónde:** `Product.Movement`, `ask products [ let product.ahead count products in-cone 10 50 ... if (product.state = "Movement" and product.ahead <= 1) [...] ]`.
- **Problema:** los productos terminados no se eliminan; quedan todos apilados en (2,2), con estado `"death"`. En cada tick, cada producto, terminado o no, calcula `count products in-cone 10 50` **antes** de comprobar su estado. Entre productos apilados en el mismo punto, cada uno cuenta a todos los demás, así que el coste crece con el cuadrado de los terminados.
- **Medición (L4, contenedor Linux, regla 3, semilla 42, 100.000 ticks):** de 0,72–0,85 ms/tick entre los ticks 15.000 y 40.000 a 1,47 ms/tick en el tick 100.000, con 83 productos terminados, todos en (2,2). Sin contar el calentamiento de la JVM, el ajuste `ms/tick = 0,755 + 1,21e-4 · death²` da R² = 0,96; el lineal da R² = 0,88. Las demás variables (productos totales, filas de `EventFrameInfo` y de `DataFrameInfo`) crecen a la vez y dan ajustes parecidos; lo que apunta a los terminados es el mecanismo, no la estadística.
- **Corrección propuesta (no aplicada):** calcular `product.ahead` solo dentro de `if (product.state = "Movement") [...]`. El `ask products` sigue recorriendo los mismos agentes en el mismo orden aleatorio y `in-cone` no consume números aleatorios, así que la línea base no debería cambiar; hay que verificarlo con `compare_baseline.py`. En cambio, filtrar el `ask` (`ask products with [Product.State != "death"]`) cambiaría el tamaño del agentset que se baraja y **rompería** la igualdad con la línea base.

## 5. Plataforma: llamadas a NetLogo desde hilos de Python distintos del principal

- **Error (L4, contenedor Linux):** cualquier `report` hecho desde un hilo de Python que no es el principal falla, incluso con un solo hilo:
  `java.lang.NullPointerException: Cannot invoke "java.lang.ClassLoader.loadClass(String)" because "this.normalClassLoader" is null` en `org.nlogo.generate.CustomClassLoader.loadClass`, durante la compilación del reporter.
- **Causa probable (no verificada):** el compilador de NetLogo carga las clases que genera con el *context class loader* del hilo. Los hilos que JPype conecta a la JVM lo tienen en `null`.
- **Consecuencia:** hoy cada workspace se usa desde el hilo principal de su proceso. La organización por procesos funciona; la organización por hilos no.

## 6. Plataforma: finales de línea de los CSV según el sistema operativo

NetLogo escribe los CSV con el separador de línea del sistema: CRLF en Windows y LF en Linux. La línea base se generó en Windows. `compare_baseline.py` compara el SHA-256 del contenido con los finales de línea normalizados a LF, de modo que la regresión vale en las dos plataformas.
