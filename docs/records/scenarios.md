# Scenario fields

[← Index and glossary](README.md)

**Scenarios are not available on the platform** (decision of 9 November 2026). The platform simulates the original plant, only in Stochastic mode, with no changed times, no degradation and no failures. The scenario code is kept only for Línea A's experiments (`docs/scenarios.md`).

For compatibility, some records keep scenario fields. Today they always carry the "no scenario" value:

| Where | Field | Current value |
|---|---|---|
| Runs (`GET /runs`, table `aclopi_runs`) | `scenario_id` | `"S0"` |
| | `scenario` | `{"id": "S0", "params": {}}` |
| | `scenario_events` | `[]` |
| | `scenario_summary` | `{"applied": 0, "skipped": 0}` |
| Session card (`GET /sessions/{id}`) | `scenario`, `scenario_summary` | as above |
| WebSocket, `snapshot` | `scenario`, `scenario_events` | `{"id": "S0", "params": {}}`, `[]` |
| CSV of a run | `scenario_id` | `S0` |

**If another value appears** (S1, S2 or S3, with parameters and events), it is an **old run**, saved before scenarios were taken out. On the page it shows with the mark `[S2]` (for example) next to the rule, and "Repeat" repeats it without the scenario. Its `scenario_events` have the format described in `docs/scenarios.md`.

Creating a session with a scenario other than S0 answers `422` with the code `scenarios_unavailable` ("scenarios are not available").
