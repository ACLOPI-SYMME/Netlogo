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

## Fases 2–5 — filtro, LLM, flujo y servicio

- `aclopi/agent/triage.py`, `strategies.py` (b1, b1b, nivel de código del agente), `local.py` (b1/b1b como
  decisores de la regla 4 sobre `SimulationSession`, modo rápido, hilo principal).
- `aclopi/agent/llm/` (fake, ollama, anthropic, bedrock) y `aclopi/agent/prompts/` (prompt mayor ≈ 800 tokens estimados).
- `aclopi/agent/core.py`: flujo con plazos de vivo y rápido, what-if, respaldo y registro por decisión.
- `aclopi/agent/service.py` (`python -m aclopi.agent`, puerto 8100), `docker/agent.Dockerfile`,
  `requirements-agent.txt`, servicio `agent` en `docker-compose.yml` con `profiles: [agent]`,
  `.env.agent.example`.

## Comentarios de la Línea A sobre la propuesta (`docs/agent-api.md`, `aclopi/contracts/agent.py`)

1. **De acuerdo** con `/decide` → 202, `next-machine`, niveles, token, 409/422 sin reintento y el registro.
2. **`latencies`:** el agente puede mandar también `what_if_ms`; `Latencies` ya admite extras, pero convendría documentarlo.
3. **`/decide` podría traer `own_remaining`, el tipo del producto y sus operaciones pendientes.** Hoy el agente
   necesita `GET /state` además de `candidates` para el contexto del prompt (2 llamadas por decisión).
4. **`CandidateInfo` tipa `available` como bool.** El agente lo mantiene (gancho `machine-available?`) y publica el tiempo
   en `available_in`. Convendría declarar en el modelo de la API los campos nuevos (`available_in`, `proc_time`,
   `travel_next`, `is_current_machine`, `queue`, `en_route` y, en el resultado, `best_by_*`, `gap_*`,
   `current_machine`, `own_remaining`, `next_operation`, `travel_source`) para que aparezcan en el OpenAPI;
   hoy pasan como extras.
5. **`estimate_start` del what-if** calcula el viaje con `distances / 0,3 × 0,31`; el medido es `distances` (−3,3 %).
6. **Plazo en rápido:** el agente usa 60 s de seguridad + what-if ≤ 15 s, por debajo de
   `ACLOPI_FAST_DECISION_TIMEOUT_S` (90 s). Conviene mantener ese orden si se cambia alguno.
7. **`/health` del agente** responde 200 con `{"llm": "ok"|"down"|"unknown"}`. Con el LLM caído b1/b1b siguen
   y `agent` decide por `code-fallback`; la plataforma podría mostrar ese estado.
8. **La API acepta solo las reglas 1–3 al crear sesiones** (si no cambió): para el agente hace falta la regla 4 con
   `strategy` (ya está en la UI).
9. **KPIs `created` y `work_completed`:** siguen sin estar en el modelo `Kpis` de la API (2 tests aceptados como fallo).

## Pendiente / bloqueado

- **Playwright** (ver Fase 0).
- **LangGraph no está instalado** (requiere internet). `core.py` usa `StateGraph` si está disponible y, si no,
  un ejecutor mínimo con los mismos nodos y aristas; los tests corren con este último. Propuesta:
  `pip install langgraph` (ya está en `requirements-agent.txt`).
- **respx no está instalado;** los tests usan `httpx.MockTransport` (equivalente, sin dependencia nueva).
