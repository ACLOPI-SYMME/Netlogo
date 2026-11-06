# Escenarios: lado plataforma

Un escenario cambia la planta durante la corrida, desde Python y sin tocar el modelo. Son lo más importante de la demo: ver al agente reaccionar a una falla.

**Reparto del trabajo.**
- La **Línea A** escribe la lógica en `aclopi/sim/scenarios.py`: qué escenarios hay, sus parámetros, el calendario de eventos y cómo se aplica cada evento al modelo.
- La **plataforma** decide cuándo se aplica cada evento, lo registra, lo transmite, lo guarda y lo muestra.
- Mientras la Línea A no entregue su versión, el módulo es un stub con las mismas firmas. El stub **no cambia el modelo**: todos los eventos salen aplicados, con `before`/`after` en `null`.

## Interfaz que usa la plataforma (`aclopi/sim/scenarios.py`)

| Función | Qué hace |
|---|---|
| `list_scenarios()` | Lista de `ScenarioSpec(id, name, description, params)`. `params` es una lista de `ParamSpec(name, type, default, min, max, description)` |
| `validate_params(id, params)` | Devuelve los parámetros con los valores por defecto ya puestos. Si algo es inválido, lanza `ValueError` con el motivo |
| `scenario_events(id, params, seed, start, end)` | Eventos `ScenarioEvent(tick, kind, machine, value, label)` del rango `[start, end)`, ordenados por tick. Es pura y determinista: S3 sortea con `random.Random(seed)` de Python, no con el azar del modelo, así que el calendario es el mismo para cualquier estrategia |
| `apply_events(session, events)` | Aplica los eventos con el modelo en su tick. Devuelve un `AppliedEvent(event, applied, skip_reason, before, after)` por evento |

`kind` puede ser:
- `set_times` (S1);
- `scale_times` (S2);
- `repair` (S3).

El único motivo de salto es `skip_reason = "machine-idle"`: una falla en una máquina libre. Esa condición se evalúa dentro de `apply_events`, en el mismo momento en que se aplica.

Variable solo para tests: con `ACLOPI_SCENARIO_STUB_SKIP=1`, el stub devuelve los `repair` como saltados.

### Escenarios del stub

| Id | Nombre | Parámetros (valor por defecto, rango) | Eventos |
|---|---|---|---|
| S0 | Base | — | ninguno |
| S1 | Máquinas heterogéneas | `times`: M2 160, M3 180, M4 200, M5 220, M6 240, M7 260 (cada uno 50–1000 u.t.) | Un `set_times` en el tick 0 por cada máquina indicada |
| S2 | Degradación | `machine` M7 (M2–M7); `factor` 1,75 (1,0–5,0); `start_tick` 10.000 (0–1.000.000) | Un `scale_times` en `start_tick` |
| S3 | Fallas | `interval_ticks` 5000 (500–1.000.000); `repair_ut` 300 (10–2000); `machines` M2–M7 (al menos una) | Una falla en cada múltiplo de `interval_ticks` (la primera en `interval_ticks`), en una máquina sorteada de la lista. Label: "Falla en Mx: +N u.t." |

Detalles de S1:
- Se pueden dar tiempos solo para algunas máquinas: las demás conservan el tiempo que tenga el modelo.
- `times: {}` es válido y equivale a S0.
- En la página, un campo vacío significa "sin cambio".

**Qué afecta cada evento en el modelo:**
- `scale_times` (S2) y `set_times` (S1) solo cambian las operaciones que **empiecen después** del evento. Una operación en curso termina con su tiempo de antes.
- El único evento que alarga una operación en curso es **`repair` (S3)**.

## API

- **`GET /scenarios`:** devuelve `list_scenarios()`. La página arma el formulario con esa lista.
- **`POST /sessions`:**
  - acepta `scenario: {id, params}`. Es opcional; por defecto, S0;
  - valida con `validate_params`. Si recibe un `ValueError`, responde `422` con `code: "invalid_scenario"` y el mensaje en `detail`, por ejemplo `"factor: must be between 1 and 5 (got 9)"`;
  - la validación ocurre antes de pedir un worker.
- **`SessionInfo`:** incluye `scenario: {id, params}`, con los parámetros ya completados, y `scenario_summary: {applied, skipped}` de la corrida actual.
- **`GET /runs?scenario=S3`:** filtra las corridas por escenario.

## Regla del tick

**Un evento del tick T se aplica cuando el modelo está en el tick T, antes de avanzar.** Esto vale en todos los casos:

| Caso | Cuándo se aplica |
|---|---|
| Setup | Los eventos del tick 0 se aplican después del `setup` del modelo, antes del primer avance |
| Reset | Los eventos se recalculan con la misma semilla y salen idénticos. Los del tick 0 se aplican otra vez |
| En vivo | Al final del bloque que llega a T |
| Rápido | Igual que en vivo |
| Rápido con decisiones (`run-until-decision`) | Igual que en vivo |
| Step manual | Durante el step: se parte en tramos que paran en cada evento, se aplica y se sigue hasta completar los n ticks |

**Cortes de bloque.** Ningún avance pasa por encima del tick de un evento: el tamaño del bloque se recorta para que pare justo en T.
- **En rápido**, el bloque se detiene en lo primero que ocurra: el siguiente evento, la siguiente decisión o el fin del bloque.
- **En vivo**, un bloque recortado es más corto. El siguiente bloque se programa según los ticks que realmente avanzó, así que el ritmo no cambia.

Los eventos se calculan una sola vez, para `[0, horizonte)`, en el setup y en cada reset. El worker guarda cuáles ya aplicó.

## Orden: evento, decisión y foto del what-if

Cuando un bloque termina en un tick T que tiene eventos, el orden es:

1. Se aplican los eventos de T (`apply_events`).
2. Se leen las peticiones de decisión del bloque (`pending_decisions`) y su contexto. En el registro de la API:
   - primero se registra y se publica cada `scenario_event`;
   - después se envía `POST /decide` al agente.

   Si un evento coincide con una decisión pendiente, el agente decide con la planta ya cambiada.
3. Solo después, entre bloques, el worker atiende otros pedidos: candidates, la foto del what-if, el estado.

   Por eso, si llega un pedido de what-if en un tick con eventos, la foto se toma **después** de aplicarlos.

## What-if sin eventos futuros

Las copias del what-if **no aplican eventos de escenario**: el worker de what-if borra el calendario al importar la foto. El agente no debe conocer el futuro.

Lo que ya ocurrió (un tiempo cambiado, una degradación, una reparación en curso) forma parte del estado de la planta. La foto lo lleva y la copia lo respeta.

## Lo que se transmite y se guarda

**Registro de eventos.** Cada `AppliedEvent` se añade al registro de eventos de la sesión (`recent_events` del snapshot y lista de la página) como un evento de tipo `scenario`:

```json
{"type": "scenario", "tick": 5000, "kind": "repair", "machine": "M4", "value": 300.0,
 "label": "Falla en M4: +300 u.t.", "applied": true, "skip_reason": null, "before": null, "after": null}
```

**WebSocket.** Se envía un mensaje `scenario_event` por cada evento aplicado o saltado:

```json
{"type": "scenario_event", "seq": 812, "tick": 5000, "event": { ...el registro de arriba... }}
```

Se publica antes que el `tick`/`progress` del bloque que termina en ese tick. Los eventos del tick 0 (setup y reset) no generan mensaje: llegan en el snapshot.

**Snapshot.** Trae `scenario: {id, params}` y `scenario_events`, con todos los eventos ya ocurridos en la corrida. Un cliente que se conecta tarde puede marcar las máquinas afectadas.

**Corrida guardada** (`GET /runs`, `GET /runs/{id}`):
- `scenario_id`;
- `scenario: {id, params}`;
- `scenario_events`: la lista completa;
- `scenario_summary: {applied, skipped}`.

## Página (`/ui`)

**Pestaña Sesión:**
- selector de escenario, con su nombre y su descripción;
- sección plegable "Parámetros del escenario", armada desde `ParamSpec` y con los valores por defecto ya puestos. Los errores aparecen junto a cada campo; el servidor valida igual.

**Vista en vivo:**
- cada evento aparece como aviso durante 5 s y queda en la lista de eventos;
- en una falla, la máquina parpadea 5 s;
- en una degradación o un tiempo cambiado, la máquina queda con un marco y el valor;
- un evento saltado se ve atenuado: "Falla saltada: M4 libre".

**Pestaña Corridas:**
- columnas Escenario y Fallas (aplicadas / saltadas), y filtro por escenario;
- "Repetir" copia el escenario con sus parámetros;
- la comparación agrupa por escenario (con parámetros), semilla y set de productos.
