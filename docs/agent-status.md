# Estado de la Línea A (agente)

Rama `agent/line-a` (desde main `f829fbd`, que incluye `5c2c39c`). Se actualiza al cerrar cada fase.

## Fase 0 — Pestaña "Set de productos"

| Requerimiento | Estado |
|---|---|
| Pestaña aparte con la lista: agregar, editar tipo, eliminar, reordenar arrastrando | Estaba (Línea B, `live.html`) |
| CSV → misma lista editable | Estaba |
| Errores por fila visibles sin descartar el resto | **Agregado**: ante un 422, el frontend reenvía el CSV sin las líneas con error (la API vuelve a validar) y carga el resto; las filas vacías, que la API omite sin avisar, se informan como "fila vacía" |
| La lista enviada al crear la sesión es la que se ve, en ese orden | **Agregado**: opción "Lista actual" en Set de la sesión (se elige sola al editar la lista); envía `products` en línea en ese orden. Antes solo se podía elegir un set guardado |

Prueba: `tests/test_ui_product_set.py` (Playwright, mini-API con el parser real). **Pendiente:** Playwright
no está instalado en el venv y su instalación requiere internet: propuesta `pip install playwright` y usar
el Edge instalado (`channel="msedge"`, sin descargar navegadores). Sin Playwright el test se salta. El JS
de la página pasa `node --check`.

## Fase 1 — candidates (`aclopi/sim/candidates.py`, `aclopi/contracts/candidates.py`)

`compute_candidates` (pura), `read_model_static` y `candidates_for_session` con las firmas acordadas.
`estimate_start`, `machine_loads` y `travel_time` del stub siguen igual (los usan `aclopi/sim/whatif.py`
y el worker). Nota para la Línea B: `travel_time` del stub calcula `distances / 0,3 × 0,31`, un 3,3 %
más que el viaje real medido (`distances` ya está en u.t.); conviene que `estimate_start` use
`aclopi.sim.candidates.travel`.

Viaje medido (`data/a0/travel_times.csv`): en las 16 rutas con 2 o más viajes, el mínimo = `distances`
(±0,1 %). Las 3 rutas vistas una sola vez (M3→M7, M6→M5, M6→M4) incluyeron esperas (+7 % a +78 %);
`distances` es su cota inferior.

**Campos de `CandidatesResult` (para la Línea B).** Los del stub se mantienen con el mismo nombre y tipo.

| Campo | Tipo | Significado |
|---|---|---|
| `product`, `seq`, `operation`, `tick`, `time`, `valid`, `reason` | – | igual que el stub (`reason`: `unknown-or-finished-product`, `invalid-seq`, `seq-mismatch`, `not-in-machine`) |
| `candidates` | lista | ordenada por `finish` (empate: menor número de máquina) |
| `current_machine` | str | máquina donde se procesa el producto |
| `own_remaining` | u.t. | lo que le falta de su operación actual |
| `next_operation` | str \| null | operación `seq+1` |
| `best_by_finish`, `best_by_finish_plus_next` | str | mejores por cada criterio |
| `gap_finish`, `gap_finish_plus_next` | u.t. \| null | segunda − mejor (null con una candidata) |
| `travel_source` | str | `"distances"` |

Por candidata:

| Campo | Tipo | Significado |
|---|---|---|
| `machine` | str | |
| `own_remaining`, `travel`, `current_remaining`, `queue_time`, `en_route_time` | u.t. (duración) | `travel` = `distances[actual][m]`, 0 si es la máquina actual |
| `available_in` | u.t. | `current_remaining + queue_time + en_route_time` (= `own_remaining` si es la máquina actual) |
| `arrival`, `start`, `finish`, `finish_plus_next` | u.t. **absolutos** (como en el stub) | `arrival = now + own + travel`, `start = now + max(own + travel, available_in)`, `finish = start + proc_time` |
| `proc_time` | u.t. | `Machine.Operations.Time` + 10 (Stochastic, no en M1) |
| `delta_finish`, `delta_finish_plus_next` | u.t. | contra la mejor de cada criterio |
| `next_machine`, `travel_next` | str \| null, u.t. | máquina de `seq+1` más cercana (viaje 0 si es la misma) |
| `available` | bool | gancho `machine-available?` (hoy siempre true). Se mantiene bool porque así lo tipa `CandidateInfo` de la API; el tiempo disponible está en `available_in` |
| `is_current_machine` | bool | se reprocesa en el sitio: sin viaje, sin cola |
| `queue`, `en_route` | listas de who | productos contados en cada término |

Diferencias con el diseño: `arrival/start/finish` son absolutos (compatibilidad con el stub) y el tiempo
disponible se llama `available_in` (en la API `available` es bool). En camino = vivos que no están en la
cola ni en proceso en la candidata y van hacia ella: viajando o esperando salir de su estación con
`Heading.Workstation` = candidata, o en proceso (también en la propia candidata, reproceso en el sitio)
con `AI.Next.Machine` = candidata para su operación siguiente.

## Pendiente / bloqueado

- Playwright (ver arriba).
