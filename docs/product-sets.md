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
