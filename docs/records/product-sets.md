# Product sets

[← Index and glossary](README.md)

## What it is

A fixed list of products (type, in entry order) saved under a name. A session created with a set makes exactly those products enter, in that order, and the run ends when they have all finished. It is used to compare rules with the same workload. The design is in `docs/product-sets.md`.

## How it is produced and when it is available

- It is created by hand: on the page (**Order entry** tab → "Save") or with `POST /product-sets`.
- Available **always**, until it is deleted. With DynamoDB it is stored in the table **`aclopi_product_sets`** (key `id`) and persists; without DynamoDB it lives in memory and is lost when the API restarts.
- The session keeps **its own copy**: editing or deleting the set afterwards does not change the sessions or runs that already used it. The saved run also carries the list (`products`).

## How to see it

| Where | What it does |
|---|---|
| `GET /product-sets` | List of sets, **without** the products |
| `GET /product-sets/{id}` | One set with its products |
| `GET /product-sets/{id}/csv` | The set as CSV (`type,priority`) |
| `POST /product-sets`, `PUT /product-sets/{id}`, `DELETE /product-sets/{id}` | Create, replace, delete |
| `POST /product-sets/parse-csv` | Validates an uploaded CSV and returns the list (does not save it) |
| `POST /product-sets/generate` | The products the model would generate with a seed (does not save them) |
| Page, **Order entry** tab | Editor, "Upload CSV", "Download CSV", "Generate from seed", "Save", "Open", "Delete" |

## Fields

| Field | Meaning | Values |
|---|---|---|
| `id` | Identifier | 32 hexadecimal characters |
| `name` | Name | 1–200 characters |
| `products` | The list, in entry order; each one with `type` and `priority` | 1 to 30 products; `type` A, I, P, B, E, L, T; `priority` 60–100 (80 if not given). No rule and not the agent use the priority; the page does not show it and sends only the type |
| `total` | Number of products | count |
| `counts` | Number per type | `{"A": …, "I": …, "P": …, "B": …, "E": …, "L": …, "T": …}` |
| `hash` | Fingerprint (SHA-256) of the list. Equal to the `products_hash` of the sessions and runs that used it | 64 hexadecimal characters |
| `created_at`, `updated_at` | Creation and last change | Unix time (s) |

`POST /product-sets/generate` also answers `seed` and `seed_source` (`user` or `random`). `parse-csv` with errors answers 422 with `errors: [{"line": n, "error": "…"}]`.

## Real example

```json
{"id": "251c64c8e403434daedf9577668305f5", "name": "Ejemplo docs", "total": 5,
 "counts": {"A": 1, "I": 1, "P": 0, "B": 1, "E": 1, "L": 1, "T": 0},
 "hash": "56fbcd4c1edbcab65c0acc688e0495594f6d831ed2a2964f2e7ad2598ab7a604",
 "created_at": 1794220312.305876, "updated_at": 1794220312.305876,
 "products": [{"type": "A", "priority": 70}, {"type": "E", "priority": 90}, {"type": "I", "priority": 80},
              {"type": "B", "priority": 60}, {"type": "L", "priority": 100}]}
```

**Reading:** the set "Ejemplo docs" has 5 products, one of each type A, I, B, E and L (no P or T). They enter in the order of the list: first an A. The example fast run used it: its `products_hash` is this `hash`. (This set was created through the API with priorities; the page would have saved them all with 80.)

## CSV of a set

The page's "Download CSV" writes only the `type` column, one row per product, in entry order:

```
type
A
E
```

`GET /product-sets/{id}/csv` writes `type,priority`. When uploading a CSV, `,` or `;` are accepted as separators, UTF-8 with or without BOM, and the type in upper or lower case. `priority` is optional (80 by default) and the page ignores it. At most 30 products.

## Useful calculations and pitfalls

- **Same set** = same `hash`, even with another name or `id`.
- **The list of `GET /product-sets` does not carry the products**; each set has to be requested.
- **A run without a set** ("Random" on the page) has neither `product_set_id` nor `products_hash`: its products came from the seed.
- **An inline set** (`products` when creating the session, or "Current list" on the page) has no `product_set_id`, but it does have `products_hash`.
