# Eventos del modelo

[← Índice y glosario](README.md)

## Qué es

El "diario" de los movimientos de los productos: cada vez que un producto **entra** a una máquina, **sale** de una o **pasa** por ciertos nodos del riel, el modelo anota una línea. Sirve para reconstruir el recorrido de un producto y para animar la planta en la página.

## Cómo se genera y cuándo está disponible

- Lo escribe el **modelo NetLogo**, en el mismo momento en que pasa cada cosa, en una lista interna (el *event-buffer*).
- Durante una corrida, la plataforma vacía esa lista al final de **cada bloque** y manda los eventos por el WebSocket (`events` de `tick` y `progress`). También guarda los últimos 500 de la sesión para el `snapshot`.
- Fuera de una corrida (sesión detenida o pausada, o después de un `step` manual): `GET /sessions/{id}/events` devuelve los eventos que quedaron en la lista **desde la última lectura** y la vacía.
- Los eventos no se guardan con la corrida ni en DynamoDB.

## Cómo verlo

| Dónde | Qué trae |
|---|---|
| WebSocket, mensajes `tick` / `progress` | Los eventos nuevos de cada bloque |
| WebSocket, `snapshot` → `recent_events` | Los últimos 500 de la sesión (desde el último reinicio) |
| `GET /sessions/{id}/events` | Los que quedaron sin leer. **Responde 409 mientras la sesión corre** |
| Página, cuadro **Eventos** | Los últimos 200 |

## Campos (los 9 del event-buffer)

| Campo | Qué significa | Unidad | Valores |
|---|---|---|---|
| `tick` | Tick del evento | ticks | — |
| `event` | Qué pasó | — | `ProductEntersMachine` (entra a una máquina), `ProductExitsMachine` (sale de una máquina), `PassingBy` (pasa por un nodo de control) |
| `who` | Producto | — | 200… |
| `product_type` | Tipo de producto | — | A, I, P, B, E, L, T |
| `location` | Dónde pasó | — | `M1`…`M7` en entradas y salidas; `Node <número>` en `PassingBy` |
| `operation` | En una entrada o un paso: la operación que va a hacer. En una salida: la operación **que acaba de terminar** | — | O1…O9 |
| `next_operation` | La siguiente operación pendiente del producto, según el modelo en ese instante | — | O1…O9 |
| `destination` | Máquina hacia la que se dirige | — | M1…M7 |
| `time` | Tiempo simulado del evento | u.t. | — |

## Ejemplo real

Los cuatro primeros eventos de la corrida rápida (vinieron en los `progress` del WebSocket):

```json
[{"tick": 366, "event": "ProductEntersMachine", "who": 200, "product_type": "A", "location": "M1",
  "operation": "O8", "next_operation": "O8", "destination": "M1", "time": 113.77},
 {"tick": 690, "event": "ProductExitsMachine", "who": 200, "product_type": "A", "location": "M1",
  "operation": "O8", "next_operation": "O1", "destination": "M2", "time": 213.9},
 {"tick": 1007, "event": "PassingBy", "who": 200, "product_type": "A", "location": "Node 12",
  "operation": "O1", "next_operation": "O1", "destination": "M2", "time": 312.48},
 {"tick": 1011, "event": "ProductEntersMachine", "who": 201, "product_type": "E", "location": "M1",
  "operation": "O8", "next_operation": "O8", "destination": "M1", "time": 313.72}]
```

**Lectura línea por línea del segundo evento:**
- `tick: 690`, `time: 213.9`: ocurrió en el tick 690, a las 213,9 u.t.
- `event: ProductExitsMachine`, `location: M1`: el producto salió de M1.
- `who: 200`, `product_type: A`: es el producto 200, de tipo A.
- `operation: O8`: acaba de terminar O8 (la operación de entrada, en M1). Entró en el tick 366: estuvo 324 ticks, unas 100 u.t., lo que dura O8.
- `next_operation: O1`, `destination: M2`: ahora va a hacer O1 en M2 (con la regla 4, la máquina la había elegido el agente en el tick 367).

## Cuentas útiles

- **Tiempo de una operación** = `time` de la salida − `time` de la entrada del mismo producto en la misma máquina (en u.t.).
- **Tiempo de viaje entre máquinas** = `time` de la entrada a la siguiente máquina − `time` de la salida de la anterior.
- **Recorrido de un producto:** filtrar por `who` y ordenar por `tick`.
- **Cantidad de eventos:** en la corrida rápida del ejemplo hubo 104 (41 entradas, 41 salidas, 22 pasos) para 5 productos.

## Trampas

- **`GET /sessions/{id}/events` no es repetible:** cada llamada vacía la lista. Y como durante una corrida la plataforma ya la vació para el WebSocket, **después de una corrida suele venir vacía** (en el ejemplo, `[]`). Para tener todos los eventos de una corrida, hay que escuchar el WebSocket desde el principio.
- **`operation` cambia de sentido en las salidas:** es la que terminó, no la que sigue.
- **No confundir con el CSV de eventos del modelo** (`Results/Events`), que tiene otras columnas y escribe `"XXX"`/`"YYY"` en las salidas ([csv-del-modelo.md](csv-del-modelo.md)).
- **Una sesión reiniciada** vuelve a empezar su lista de eventos recientes.
