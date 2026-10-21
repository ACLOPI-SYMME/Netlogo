# Problemas conocidos del modelo

Problemas detectados en `model/Paper.nlogo` que **no se corrigen** para no alterar el comportamiento validado de la simulación (línea base en `tests/fixtures/baseline/`, reglas 1–3, semilla 42, Stochastic). Los números de línea corresponden a la rama `model/l2-platform-reporters`.

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
