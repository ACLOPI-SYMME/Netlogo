# Sets de productos (L5.6)

El orden y el tipo de los productos que entran a la planta pueden venir de una **lista definida por el usuario**, en lugar de la semilla.

- **Cada producto** tiene `type` ∈ {A, I, P, B, E, L, T} (los `PosibleProducts` del modelo) y `priority`, un entero de 60 a 100 (80 por defecto).
- **Orden de entrada:** es el de la lista.
- **Momento de cada entrada:** lo sigue decidiendo el modelo como siempre: cada 100 u.t., si hay menos de 10 productos activos y la zona de entrada a M1 está libre (procedimiento `Go`).
- **La semilla** sigue controlando todo el resto del azar.

## Cambio en el modelo (rama `model/product-list`)

Es el único cambio. Reutiliza la vía de creación del set fijo de la Línea A (`fixed-product-sequence?`, `docs/product-sequence.md`).

| Qué | Dónde (`model/Paper.nlogo`) |
|---|---|
| Globales `product-list?` (interruptor) y `product-list` (lista de `[tipo priority]` que asigna Python) | líneas 56–58 |
| `Setup`: `product-list? false` y `product-list []` | líneas 140–141 |
| `Go`: con el interruptor, el producto n toma el tipo de `item (n − 1) product-list`; si la lista se acabó, no se crea nada. Sin el interruptor, el código es el de antes (set fijo u `one-of PosibleProducts`) | líneas 158–164 |
| `Create.product`: con el interruptor, `priority` = `last item (n − 1) product-list` | línea 542 |
| `platform-state`: `product_list_active`, `product_list_length` y `product_list_next` (= `products-created`, el índice desde 0 del siguiente producto de la lista) | líneas 3115–3117 |

- **Sin consumo de azar.** La lista no usa el generador principal para el tipo ni para la priority, igual que el set fijo.
- **"Generar desde semilla"** usa el reporter que ya existía, `platform-product-sequence [desde hasta]` (Línea A). `SimulationSession.product_sequence(seed, count)` cambia `product-sequence-seed` solo durante la lectura y después lo restaura; no hizo falta un reporter nuevo.

## Python

`SimulationSession.setup(..., product_list=[(tipo, priority), ...])`:
- valida la lista con `validate_product_list`: de 1 a 1000 productos, tipo válido y priority entera de 60 a 100;
- la asigna después de `setup` y enciende el interruptor. La lista tiene prioridad sobre el set fijo.

## Garantías (probadas)

| Garantía | Cómo se prueba | Resultado |
|---|---|---|
| Con el interruptor apagado, el modelo es idéntico al de antes | `compare_baseline.py` y `tests/test_product_sequence.py` | OK |
| La secuencia de la semilla 42 cargada como lista da exactamente los mismos productos (who, tipo, priority) y los mismos KPIs en 10.000 ticks que el set fijo de la semilla 42 | `tests/test_product_list.py::test_list_from_the_seed_equals_the_fixed_sequence` | OK |
| Una lista de 5 crea exactamente esos 5, en ese orden, y ninguno más | `tests/test_product_list.py` | OK |

## Fin de corrida y KPIs

- **Fin de corrida con lista** (vivo y rápido): la corrida termina cuando **todos** los productos de la lista terminaron, con `run_reason: "all_products_done"` y `finished.reason` en el WebSocket, o al llegar al horizonte (`"horizon"`), lo que pase primero.
- **Detención exacta:** las sesiones con lista avanzan con `SimulationSession.step_product_list`, que se detiene en el `go` exacto en que termina el último producto y nunca avanza después.
- **Por qué hace falta:** `PrintData` (en `Go`, línea 173) calcula medias sobre los productos vivos y falla cuando no queda ninguno. **Riesgo residual** (solo se arregla tocando el modelo): si el `go` en que termina el último producto coincide con un tick de `PrintData` (1 de cada ~322 ticks), el error ocurre en ese mismo `go` y la corrida se detiene con `run_error`.

KPIs nuevos (`aclopi/sim/kpis.py`, `GET /kpis`):

| KPI | Significado |
|---|---|
| `products_total` | Largo de la lista (`null` sin lista) |
| `all_done` | Todos los productos de la lista se crearon y terminaron |
| `makespan_time` | Última `ProductRealCompletion` de los productos terminados, desde el inicio de la corrida (`null` si no terminaron todos) |
| `makespan_ticks` | `makespan_time / 0,31`, redondeado |

## API

| Ruta | Qué hace |
|---|---|
| `POST /product-sets`, `GET /product-sets`, `GET`/`PUT`/`DELETE /product-sets/{id}` | Sets con `name` y `products` `[{type, priority}]` en orden, de 1 a 1000 productos. `type` acepta minúsculas |
| `POST /product-sets/parse-csv` (multipart, campo `file`) | Convierte un CSV en una lista validada, sin guardarla. Columnas `type` y `priority` (opcional, 80); separador `,` o `;`; UTF-8 con o sin BOM. Con errores responde 422 con `errors: [{line, error}]`, donde `line` es la línea del archivo (la cabecera es la 1) |
| `GET /product-sets/{id}/csv` | Exporta el set (`type,priority`) |
| `POST /product-sets/generate` `{seed?, count}` | La lista que el modelo genera con esa semilla (set fijo; operación corta en un worker de what-if prestado). Sin `seed` se sortea una y se devuelve |
| `POST /sessions` | Acepta `product_set_id` **o** `products` (en línea). Sin ninguno, se comporta como antes (set generado con la semilla). La sesión guarda una **copia**: editar el set después no la cambia. `SessionInfo` incluye `product_set_id`, `products_total` y `products_hash` (sha256 de la lista) |

Almacenamiento: en memoria (`InMemoryProductSetStore`); en L5.7 pasa a DynamoDB.

## Semilla opcional

- **Semilla dada:** en `POST /sessions`, `seed` es opcional. Si viene, debe ser un entero entre −2147483648 y 2147483647; si no, 422.
- **Semilla ausente:** la plataforma la sortea con `secrets`, no con el azar del modelo.
- **Registro:** la semilla usada se guarda **siempre** en `parameters.seed`, junto con `seed_source` (`user` o `random`), así cualquier corrida se puede repetir.
- **Página `/ui`:**
  - checkbox "Agregar semilla", desmarcado por defecto, con un tooltip;
  - el campo es obligatorio y se valida si el checkbox está marcado;
  - al crear la sesión muestra "Semilla usada: N" con un botón para copiarla;
  - "Generar desde semilla" sigue el mismo patrón.
