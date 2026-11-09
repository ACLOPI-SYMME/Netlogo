# Sets de productos

[← Índice y glosario](README.md)

## Qué es

Una lista fija de productos (tipo y priority, en orden de entrada) guardada con un nombre. Una sesión creada con un set hace entrar exactamente esos productos, en ese orden, y la corrida termina cuando terminan todos. Sirve para comparar reglas con la misma carga de trabajo. El diseño está en `docs/product-sets.md`.

## Cómo se genera y cuándo está disponible

- Se crea a mano: en la página (pestaña **Product set** → "Save") o con `POST /product-sets`.
- Disponible **siempre**, hasta que se borre. Con DynamoDB se guarda en la tabla **`aclopi_product_sets`** (clave `id`) y persiste; sin DynamoDB vive en memoria y se pierde al reiniciar la API.
- La sesión guarda **su propia copia**: editar o borrar el set después no cambia las sesiones ni las corridas que ya lo usaron. La corrida guardada también trae la lista (`products`).

## Cómo verlo

| Dónde | Qué hace |
|---|---|
| `GET /product-sets` | Lista de sets, **sin** los productos |
| `GET /product-sets/{id}` | Un set con sus productos |
| `GET /product-sets/{id}/csv` | El set como CSV (`type,priority`) |
| `POST /product-sets`, `PUT /product-sets/{id}`, `DELETE /product-sets/{id}` | Crear, reemplazar, borrar |
| `POST /product-sets/parse-csv` | Valida un CSV subido y devuelve la lista (no la guarda) |
| `POST /product-sets/generate` | Los productos que el modelo generaría con una semilla (no los guarda) |
| Página, pestaña **Product set** | Editor, "Upload CSV", "Download CSV", "Generate from seed", "Save", "Open", "Delete" |

## Campos

| Campo | Qué significa | Valores |
|---|---|---|
| `id` | Identificador | 32 caracteres hexadecimales |
| `name` | Nombre | 1–200 caracteres |
| `products` | La lista, en orden de entrada; cada uno con `type` y `priority` | 1 a 30 productos; `type` A, I, P, B, E, L, T; `priority` 60–100 (80 si no se da). La priority no la usa ninguna regla ni el agente; la página no la muestra y envía solo el tipo |
| `total` | Cantidad de productos | conteo |
| `counts` | Cantidad por tipo | `{"A": …, "I": …, "P": …, "B": …, "E": …, "L": …, "T": …}` |
| `hash` | Huella (SHA-256) de la lista. Igual a `products_hash` de las sesiones y corridas que la usaron | 64 caracteres hexadecimales |
| `created_at`, `updated_at` | Creación y última modificación | Unix time (s) |

`POST /product-sets/generate` responde además `seed` y `seed_source` (`user` o `random`). `parse-csv` con errores responde 422 con `errors: [{"line": n, "error": "…"}]`.

## Ejemplo real

```json
{"id": "251c64c8e403434daedf9577668305f5", "name": "Ejemplo docs", "total": 5,
 "counts": {"A": 1, "I": 1, "P": 0, "B": 1, "E": 1, "L": 1, "T": 0},
 "hash": "56fbcd4c1edbcab65c0acc688e0495594f6d831ed2a2964f2e7ad2598ab7a604",
 "created_at": 1794220312.305876, "updated_at": 1794220312.305876,
 "products": [{"type": "A", "priority": 70}, {"type": "E", "priority": 90}, {"type": "I", "priority": 80},
              {"type": "B", "priority": 60}, {"type": "L", "priority": 100}]}
```

**Lectura:** el set "Ejemplo docs" tiene 5 productos, uno de cada tipo A, I, B, E y L (ninguno P ni T). Entran en el orden de la lista: primero un A con priority 70. La corrida rápida del ejemplo lo usó: su `products_hash` es este `hash`.

## CSV de un set

Columnas `type,priority`, una fila por producto, en orden de entrada:

```
type,priority
A,70
E,90
```

Al subir un CSV se acepta `,` o `;` como separador, UTF-8 con o sin BOM, y el tipo en mayúsculas o minúsculas. `priority` es opcional (80 por defecto).

## Cuentas útiles y trampas

- **Mismo set** = mismo `hash`, aunque tengan otro nombre o `id`.
- **La lista de `GET /product-sets` no trae los productos**; hay que pedir cada set.
- **Una corrida sin set** no tiene `product_set_id` ni `products_hash`: sus productos salieron de la semilla.
- **Un set creado inline** (`products` al crear la sesión, o "Lista actual" en la página) no tiene `product_set_id`, pero sí `products_hash`.
