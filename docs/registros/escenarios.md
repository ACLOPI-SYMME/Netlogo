# Campos de escenario

[← Índice y glosario](README.md)

**Los escenarios no están disponibles en la plataforma** (decisión del 9 de noviembre de 2026). La plataforma simula la planta original, solo en modo Stochastic, sin tiempos cambiados, sin degradación y sin fallas. El código de escenarios queda solo para los experimentos de la Línea A (`docs/scenarios.md`).

Por compatibilidad, algunos registros conservan campos de escenario. Hoy siempre traen el valor "sin escenario":

| Dónde | Campo | Valor actual |
|---|---|---|
| Corridas (`GET /runs`, tabla `aclopi_runs`) | `scenario_id` | `"S0"` |
| | `scenario` | `{"id": "S0", "params": {}}` |
| | `scenario_events` | `[]` |
| | `scenario_summary` | `{"applied": 0, "skipped": 0}` |
| Ficha de la sesión (`GET /sessions/{id}`) | `scenario`, `scenario_summary` | igual que arriba |
| WebSocket, `snapshot` | `scenario`, `scenario_events` | `{"id": "S0", "params": {}}`, `[]` |
| CSV de una corrida | `scenario_id` | `S0` |

**Si aparece otro valor** (S1, S2 o S3, con parámetros y eventos), es una **corrida antigua**, guardada antes de quitar los escenarios. En la página se ve con la marca `[S2]` (por ejemplo) junto a la regla, y "Repetir" la repite sin escenario. Sus `scenario_events` tienen el formato descrito en `docs/scenarios.md`.

Crear una sesión con un escenario distinto de S0 responde `422` con el código `scenarios_unavailable` ("los escenarios no están disponibles").
