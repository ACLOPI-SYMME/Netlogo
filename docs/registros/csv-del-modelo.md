# CSV que escribe el propio modelo (`Results/Data` y `Results/Events`)

[← Índice y glosario](README.md)

## Qué es

El modelo NetLogo, por su cuenta, escribe dos archivos CSV al **final** de una corrida: uno de **datos** periódicos de la planta (`Data`) y uno de **eventos** (`Events`). Vienen del modelo original, de antes de la plataforma. **La plataforma no los usa para mostrar nada**: la página, la API y las corridas guardadas se alimentan de los KPIs, los eventos y las decisiones que la plataforma lee directamente del modelo. Se conservan para comparar con el modelo original (la línea base de regresión, `scripts/compare_baseline.py`).

## Cómo se genera y cuándo está disponible

- Los escribe el procedimiento `ExportData` del modelo **solo cuando la corrida llega al horizonte** (`horizon_ticks`). Durante la corrida el modelo acumula las filas en memoria.
- **No se escriben** si la corrida termina antes: un set de productos terminado (`all_products_done`), una corrida detenida, fallida o borrada.
- Están disponibles al terminar esa corrida.

## Cómo verlo

En la carpeta de trabajo del worker que corrió la sesión:

```
<ACLOPI_WORK_DIR>/pool_<id>/sessions/session<N>_g<G>/Results/Data/Data_100_Sto_R 3_0.csv
<ACLOPI_WORK_DIR>/pool_<id>/sessions/session<N>_g<G>/Results/Events/Event_100_Sto_R 3_0.csv
```

`100` es el intervalo de registro (`Interval.Logs`), `Sto` el modo (Stochastic), `R 3` la regla (los caracteres 4–6 del nombre de la regla, con un espacio) y `0` el número de corrida de BehaviorSpace, que con la plataforma es siempre 0. Por defecto, `ACLOPI_WORK_DIR` es `results/workers/` (en Docker Compose, la carpeta `results/` del equipo).

**Ninguno tiene cabecera.**

## `Events` (9 columnas)

| Columna | Qué es | Unidad / valores |
|---|---|---|
| 1 | Tiempo simulado del evento | u.t. |
| 2 | Producto (`who`) | — |
| 3 | Tipo de producto | A, I, P, B, E, L, T |
| 4 | Evento | `ProductEntersMachine`, `ProductExitsMachine`, `PassingBy` |
| 5 | Lugar | `M1`…`M7` o `Node <n>` |
| 6 | Posición de la operación actual en la lista del producto (desde 0) | En salidas: el texto fijo **`XXX`** |
| 7 | Operación actual | O1…O9. En salidas: el texto fijo **`YYY`** |
| 8 | Operación siguiente | O1…O9 |
| 9 | Máquina a la que se dirige | M1…M7 |

Ejemplo real (de una corrida de prueba de la regla 3):

```
113.77,200,A,ProductEntersMachine,M1,0,O8,O8,M1
213.9,200,A,ProductExitsMachine,M1,XXX,YYY,O1,M2
312.48,200,A,PassingBy,Node 12,1,O1,O1,M2
```

Lectura de la segunda fila: a las 213,9 u.t. el producto 200 (tipo A) salió de M1; el CSV no dice qué operación terminó (`XXX`, `YYY`); la siguiente es O1 y va a M2.

**Diferencias con los eventos de la plataforma** ([eventos.md](eventos.md)): la plataforma agrega el tick, usa nombres de campo, y en las salidas sí dice qué operación terminó.

## `Data` (84 columnas)

Una fila cada `Interval.Logs` = 100 u.t. de tiempo simulado. Las columnas, agrupadas (el detalle está en el procedimiento `PrintData` del modelo):

| Columnas | Contenido |
|---|---|
| 1–3 | Tiempo simulado (redondeado), regla, modo |
| 4–7 | Productos vivos, productos vivos / 10, máquinas procesando, productos vivos sin máquina |
| 8–11 | Posición media (x, y) de los productos vivos y su desviación |
| 12–19 | Operaciones totales y completadas de los vivos, productos esperando, operaciones pendientes, trabajo nominal total, tiempo de proceso real, **tiempo esperando (columna 18)**, trabajo nominal pendiente |
| 20–21 | Máquinas procesando y no procesando |
| 22–28 | Productos vivos por tipo (B, E, L, T, A, I, P) |
| 29–33 | Entropía de la mezcla de tipos, fracción de tipos presentes, avance medio de los productos y relacionados |
| 34–54 | Por máquina M1…M7, tres columnas: estado (`Machine.Busy` / `Machine.Idle`), tiempo que le falta (u.t., `NaN` si está libre), productos cercanos que se dirigen a ella (`NaN` si está libre) |
| 55–84 | Productos por zona de la planta (una por máquina), máquinas ocupadas, libres y su fracción, y repeticiones de indicadores anteriores (un bloque de "KPI" del modelo original) |

## Problemas conocidos (no se corrigen, para no cambiar la línea base)

- **Columna 18 de `Data` siempre vale 0**: compara el estado con `"waiting"` en minúscula y el real es `"Waiting"` (punto 1 de `docs/known-issues.md`).
- **`XXX` / `YYY` en las salidas de `Events`**: el CSV no registra la operación que terminó (punto 3). La plataforma sí la registra en sus eventos.
- **Varias columnas de `Data` valen 0 cuando no queda ningún producto vivo** (solo al final de una corrida con set; punto 7).

## Trampas

- **La carpeta es por worker, no por sesión:** la siguiente sesión que llegue al horizonte en el mismo worker **sobrescribe** los archivos. Copiarlos antes si interesan.
- **Sin cabecera:** hay que saber qué es cada columna (esta página o `PrintData`).
- **No coinciden con lo que muestra la página:** la página usa los KPIs de la plataforma ([kpis.md](kpis.md)), que se calculan de otra forma.
