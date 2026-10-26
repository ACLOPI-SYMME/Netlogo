# Regla 4 – AI Agent: gancho de decisión

Interfaz para que Python decida a qué máquina va cada producto. Todo lo que aquí se describe
existe en `model/Paper.nlogo` (sección "Rule 4 - AI Agent" y "Rule 4 decision hook") y en
`aclopi/sim/decisions.py`. No hace falta leer el código del modelo para usarlo.

## Mecanismo

1. Con `Reactivity.rule = "Rule 4 - AI Agent"`, cuando un producto **entra** a una máquina para
   la operación de índice `k` (índice en `ProductOperations`), el modelo agrega una **petición**
   a la cola global `decision-queue` para la operación `k+1`.
2. Python lee la petición y responde con `platform-set-next-machine` mientras el producto está
   en proceso (~645 ticks en M2–M7, ~323 en M1).
3. Cuando la operación **termina** (`Cheking.Machine.Completion`), el modelo asigna
   `Heading.Workstation`:
   - la máquina elegida por Python, si hay una respuesta para esa operación y la máquina sigue
     siendo viable → `Decision.Source = "agent"`;
   - si no, la regla 3 (Potential Fields) con el mismo código y el mismo consumo de azar →
     `Decision.Source = "rule3-fallback"`.
   En ambos casos se limpia la respuesta guardada y se agrega una línea a `decision-log`.
   El producto nunca se queda sin destino.

"Viable" hoy significa "capaz de la operación". El reporter `machine-available? [nombre]`
devuelve siempre `true`; es el punto donde se conectarán los escenarios de falla.

### Cuándo se crea una petición y cuándo no

Se crea una petición al entrar a máquina si y solo si:
- la regla activa es la 4;
- existe la operación `k+1` (el producto no está en su última operación);
- la operación `k+1` puede hacerla **más de una** máquina.

Tabla de máquinas capaces (`Set.operations`):

| Operación | Máquinas | ¿Petición? |
|---|---|---|
| O1 | M2 M3 M5 M7 | sí |
| O2 | M2 M3 M6 M7 | sí |
| O3 | M4 M5 M6 M7 | sí |
| O4 | M2 M4 M6 M7 | sí |
| O5 | M3 M4 M5 M7 | sí |
| O6 | M5 | no |
| O7 | M6 | no |
| O8 | M1 | no |
| O9 | M1 | no |

Consecuencias:
- La primera operación (O8 en M1) no se decide: el producto nace con destino M1.
- El paso a O9 (M1, última operación) no genera petición; la regla 3 elige M1 y queda en el
  registro como `rule3-fallback`. Por eso, aun con un decisor que responde todo, el registro
  tiene un `rule3-fallback` por producto (el de O9). Las asignaciones a operaciones con varias
  máquinas deberían ser todas `agent`.
- Con las reglas 1–3 no se crea ninguna petición ni se escribe en el registro.

## Variables de producto

| Variable | Valor por defecto | Significado |
|---|---|---|
| `AI.Next.Machine` | `""` | máquina elegida por Python para la próxima operación |
| `AI.Decision.Seq` | `-1` | índice en `ProductOperations` de la operación para la que se eligió |
| `Decision.Source` | `""` | quién hizo la última asignación: `"agent"` o `"rule3-fallback"` |

Aparecen en `platform-state` (cada producto vivo) como `ai_next_machine`, `ai_decision_seq` y
`decision_source`.

## Reporters y comandos de NetLogo

Todos los que devuelven estructuras devuelven **texto JSON**. Ninguno consume el generador
aleatorio del modelo.

### `platform-run-until-decision [max-ticks]` (reporter)

Avanza con `go` hasta que ocurra lo primero de:
- hay al menos una petición en la cola;
- se avanzaron `max-ticks` ticks;
- terminó la corrida (al llegar a `horizon-ticks` hace la llamada extra a `go` que ejecuta
  `ExportData`, igual que `platform-step`).

Devuelve una lista NetLogo de 4 números: `[ticks avanzados terminó n_peticiones]`, con
`terminó` = 1 o 0.

**Importante:** si al llamarlo ya hay peticiones en la cola, no avanza (devuelve
`avanzados = 0`). Después de leer las peticiones hay que llamar a `platform-clear-decisions`.

Las peticiones se crean durante un `go`; cuando la llamada vuelve con `n_peticiones > 0`, el
producto acaba de entrar a la máquina, así que hay todo el tiempo de proceso para responder.

### `platform-pending-decisions` (reporter, JSON)

No vacía la cola.

```json
{
  "fields": ["who", "seq", "operation", "origin", "tick", "candidates"],
  "requests": [
    [200, 1, "O1", "M1", 366, ["M2", "M3", "M5", "M7"]]
  ]
}
```

- `who`: id del producto.
- `seq`: índice en `ProductOperations` de la operación a decidir (`k+1`).
- `operation`: nombre de esa operación (`"O1"`..`"O9"`).
- `origin`: máquina en la que está el producto (la que hace la operación `k`).
- `tick`: tick en que entró a la máquina.
- `candidates`: máquinas capaces de la operación (calculado al leer, a partir de la tabla de
  operaciones; en la cola interna se guardan solo los 5 primeros campos).

### `platform-clear-decisions` (comando)

Vacía la cola de peticiones.

### `platform-set-next-machine [who machine seq]` (reporter)

Guarda la elección de Python. Argumentos: `who` (número), `machine` (texto, p. ej. `"M3"`),
`seq` (número). Devuelve `"ok"` o el motivo del rechazo. Si rechaza, no cambia nada.

Validaciones, en este orden (se devuelve el primer motivo que aplica):

| Motivo | Cuándo |
|---|---|
| `rule4-not-active` | la regla activa no es la 4 |
| `invalid-arguments` | `who` o `seq` no son números, o `machine` no es texto |
| `unknown-product` | no existe un producto con ese `who` (incluye ids de nodos, máquinas, etc.) |
| `product-finished` | el producto ya terminó (estado `"death"`) |
| `invalid-seq` | `seq` < 0, `seq` ≥ número de operaciones del producto, o no entero |
| `stale-seq` | `seq` ≤ `CurrentSequenceOrder`: la operación ya empezó o ya tiene máquina (respuesta vieja) |
| `not-in-machine` | el producto no está en proceso en una máquina (va en camino) |
| `seq-mismatch` | `seq` ≠ `CurrentSequenceOrder + 1` (no es la operación pendiente) |
| `unknown-machine` | `machine` no es M1..M7 |
| `machine-not-capable` | la máquina no puede hacer la operación `seq` |

"En máquina" = la última operación empezada aún no terminó
(`length ProductRealStart > length ProductRealCompletion`). No se usa `Product.State`, porque
el modelo lo cambia entre "Waiting" y "Movement" mientras el producto está en proceso.

Una respuesta que llega después de que la operación terminó se rechaza como `stale-seq` (el
producto ya avanzó `CurrentSequenceOrder` a `seq`), o `product-finished` si ya terminó.

Se puede llamar varias veces para la misma operación mientras el producto está en proceso;
vale la última respuesta aceptada.

### `platform-decision-log` (reporter, JSON)

Todas las asignaciones hechas por la regla 4 desde el último vaciado (con y sin petición).

```json
{
  "fields": ["tick", "who", "seq", "operation", "origin", "chosen", "source"],
  "decisions": [
    [690, 200, 1, "O1", "M1", "M7", "agent"]
  ]
}
```

- `tick`: tick en que terminó la operación anterior y se asignó la máquina.
- `seq`, `operation`: operación asignada.
- `origin`: máquina que terminó la operación anterior.
- `chosen`: máquina asignada (`Heading.Workstation`).
- `source`: `"agent"` o `"rule3-fallback"`.

### `platform-clear-decision-log` (comando)

Vacía el registro.

## Python: `aclopi/sim/decisions.py`

Todas las funciones reciben una `SimulationSession` (con `setup(..., rule=4)`) y usan su lock.

| Función | Devuelve |
|---|---|
| `run_until_decision(session, max_ticks)` | `DecisionStepResult(ticks, advanced, finished, pending)` |
| `pending_decisions(session)` | `list[DecisionRequest(who, seq, operation, origin, tick, candidates)]` |
| `clear_decisions(session)` | `None` |
| `set_next_machine(session, who, machine, seq)` | `"ok"` o el motivo |
| `decision_log(session, clear=False)` | `list[DecisionRecord(tick, who, seq, operation, origin, chosen, source)]` |
| `clear_decision_log(session)` | `None` |

`SimulationSession.setup` acepta `rule=4`. Bucle típico ("modo rápido": se responde en el
mismo tick en que se crea la petición):

```python
session.setup(seed=42, rule=4, horizon_ticks=100000)
while True:
    result = run_until_decision(session, max_ticks=100000)
    for request in pending_decisions(session):
        set_next_machine(session, request.who, elegir(request), request.seq)
    clear_decisions(session)
    if result.finished:
        break
```

## Garantías

- Con regla 4 y **sin respuestas** de Python, la simulación es idéntica a la regla 3 con la
  misma semilla (KPIs, CSV de eventos y CSV de datos salvo la columna 2, que es el nombre de la
  regla). Lo verifican `tests/test_decisions.py` (10.000 ticks; 100.000 con `-m slow`) y
  `scripts/rule4_checks.py`.
- Leer peticiones o el registro, vaciarlos y llamar a `platform-set-next-machine` no consume el
  generador aleatorio del modelo.
- Con regla 4, `ExportData` escribe `Data_100_Sto_R 4_0.csv` y `Event_100_Sto_R 4_0.csv`.
- La misma semilla **no** garantiza las mismas condiciones para todas las estrategias una vez
  que el agente elige algo distinto de la regla 3: ver la medición en el informe de la tarea A1.
