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

## Pendiente / bloqueado

- Playwright (ver arriba).
