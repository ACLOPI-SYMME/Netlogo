# Set fijo de productos y trabajo completado

## Qué es y por qué existe

Para comparar estrategias de enrutamiento (regla 3, heurística B1, agente LLM) todas deben
recibir los **mismos productos de entrada**: el mismo tipo, en el mismo orden y con la misma
prioridad. En el modelo original no pasa: el tipo (`one-of PosibleProducts`) y la prioridad
(`random`) salen del generador aleatorio global, que se desordena en cuanto una estrategia
decide distinto (medido en A1 con `scripts/a1/measure_rng.py`: con la semilla 42, el producto
204 ya nace con otro tipo).

Con el **set fijo**, el producto número `n` (el n-ésimo creado en la corrida) tiene siempre el
mismo tipo y la misma prioridad para una semilla dada, pase lo que pase en la planta.

La forma de medir no cambia (modo continuo: semilla + ticks, se cuentan los productos
procesados) y la regla de llegada tampoco.

## Cómo se genera

- `n` = valor de `products-created` al crear el producto; el primero es `n = 1`.
- **Sub-semilla del producto n:**

  `sub_semilla(n) = (product-sequence-seed × 1000003 + n) mod 2³¹`  (reporter `Product.Sequence.Seed n`)

  Para una misma semilla de secuencia es distinta para cada `n < 2³¹` (no se repite entre
  productos) y siempre es una semilla válida de NetLogo (0 … 2³¹−1), también con semillas
  negativas. Dos semillas distintas solo podrían compartir una sub-semilla con `n ≥ 1000003`,
  muy por encima del máximo de productos de una corrida.
- Dentro de `with-local-randomness`: `random-seed sub_semilla(n)`, luego `one-of PosibleProducts`
  (tipo) y `random (100 - 60 + 1) + 60` (prioridad): los mismos sorteos, en el mismo orden, que
  el código original (reporter `Product.Sequence.Item n` → `[tipo prioridad]`).
- El generador del modelo no se usa ni se altera para tipo y prioridad.
- Se calcula cuando hace falta (al crear el producto): no hay arreglo ni estimación previa, y
  nunca se agota.

## El interruptor

| Dónde | Valor |
|---|---|
| Modelo (`Setup`) | `fixed-product-sequence? = false`, `product-sequence-seed = 0`: el modelo crea productos exactamente como el original |
| `SimulationSession.setup(...)` | **encendido por defecto** (`fixed_product_sequence=True`) y `product-sequence-seed` = semilla de la corrida. La plataforma, los workers, la API y los experimentos lo usan siempre, sin que el usuario haga nada |
| `SimulationSession.setup(..., fixed_product_sequence=False)` | apagado: modelo original. Solo para las regresiones contra la línea base: `validate_headless.py` (que alimenta `compare_baseline.py`), `make_long_fixtures.py` / `test_long_regression.py`, `test_session.py::test_horizon_10000_matches_baseline`, `rule4_checks.py` (A1) y `scripts/a2/measure_arrivals.py` |

`SimulationSession.reset()` conserva el valor; `import_world` lo lee del mundo importado
(`RunParameters.fixed_product_sequence`). NetLogo no puede leer la semilla de la corrida, por
eso Python fija `product-sequence-seed` después de `setup` (también cuando el interruptor está
apagado, para que `platform-product-sequence` muestre la secuencia de esa semilla).

**Una corrida con el set fijo no es igual a la línea base con la misma semilla.** El tipo y la
prioridad salen de otro generador y el generador del modelo deja de consumir esos dos sorteos
por producto, así que desde el primer producto todo lo demás cambia. Las regresiones contra la
línea base deben apagar el interruptor.

## Máximo de productos por corrida

La regla de llegada crea a lo sumo un producto por cada 100 unidades de tiempo simulado:

`máximo = horizonte × 0,31 / 100 + 1`  (≈ 311 con 100.000 ticks)

## Lecturas desde Python

- `platform-state` incluye `fixed_product_sequence`, `product_sequence_seed` y
  `products_created`.
- `platform-product-sequence [desde hasta]` devuelve los productos `n = desde..hasta` de la
  secuencia de `product-sequence-seed`, calculados con la misma función que la creación:

  ```json
  [{"n": 1, "type": "I", "priority": 84}, {"n": 2, "type": "E", "priority": 64}]
  ```

  No consume azar y se puede llamar en cualquier momento (también a mitad de corrida).

## Trabajo completado (KPI `work_completed`)

En `aclopi/sim/kpis.py`, junto a los KPIs existentes (que no cambian). Se mide en **unidades de
tiempo de proceso nominal**, no en número de operaciones:

- cada operación terminada suma su tiempo nominal (`OperationDuration`: 200 para O1–O7, 100
  para O8 y O9 en M1);
- cada operación en curso al final suma la fracción ya procesada de su nominal:
  `(Simulated.Time − inicio) / (Next.Completion − inicio) × nominal`, acotada a [0, 1];
- cuenta todos los productos creados (terminados y en curso).

Se usa el tiempo **nominal** y no el sorteado para que la parte aleatoria de los tiempos de
proceso no premie ni castigue a una estrategia: hacer una operación vale lo mismo aunque le haya
tocado un tiempo largo.

También se agrega `created` (productos creados = terminados + en curso).

**Tiempo medio de flujo (`mean_flow_time`), decisión tomada:** se mide desde el inicio de la
primera operación (`first ProductRealStart`, cuando el producto entra a M1 para O8) hasta la
última finalización (`last ProductRealCompletion`, fin de O9), y solo sobre productos
terminados. **No** se mide desde `ProductCreationTime` y se mantiene así a propósito: es la
definición acordada en la validación headless y la que usan la línea base y las regresiones.
La diferencia con medirlo desde la creación es pequeña y casi constante (~13,6 u.t., el viaje
desde el punto de creación hasta M1 en las corridas medidas; ver
`scripts/a2/measure_fixed_sequence.py`).

## Lo que el set fijo NO iguala (riesgo asumido P9)

Solo se igualan tipo, orden y prioridad de los productos. **No** se igualan entre estrategias:
- los tiempos de proceso sorteados al entrar a máquina (`random-exponential`, generador del modelo);
- el orden de movimiento de los productos (los `ask` recorren agentes en orden aleatorio);
- el tick en que se crea cada producto (depende del estado de la planta: menos de 10 productos
  activos y la zona de entrada libre).

Es un riesgo asumido (problema conocido P9): dos estrategias con la misma semilla ven los mismos
productos, pero no los mismos tiempos de proceso.

## Verificación

- `tests/test_product_sequence.py`: interruptor, fórmula, mismos productos con reglas 1, 3 y 4
  (decisor al azar), misma semilla = misma corrida, otra semilla = otro set,
  `platform-product-sequence` coincide con lo creado y no altera la simulación, distribución de
  tipos en 1.000 productos, trabajo completado con un estado conocido. Versiones de 10.000 ticks
  en la suite normal y de 100.000 con `-m slow`.
- `python scripts/a1/measure_rng.py --products-only --sequence on --rules 1 3 4 --horizon 100000`.
