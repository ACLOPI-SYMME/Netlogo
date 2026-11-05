# Línea base sin LLM (15 corridas)

Corridas: `results\a4\baseline_5seeds.csv`.

## Por estrategia

| Estrategia | n | makespan medio (ticks) | desv. | mean_flow_time | work_completed | todas terminadas |
|---|---|---|---|---|---|---|
| rule3 | 5 | 38300 | 1065 | 2070.2 | 39800.0 | 5/5 |
| b1 | 5 | 37952 | 1772 | 1981.6 | 39800.0 | 5/5 |
| b1b | 5 | 37819 | 1599 | 1989.0 | 39800.0 | 5/5 |

## Por semilla (makespan en ticks; diferencia contra rule3)

| Semilla | rule3 | b1 | b1 − rule3 | b1b | b1b − rule3 |
|---|---|---|---|---|---|
| 1 | 38547 | 35774 | -2773 (-7.2 %) | 35774 | -2773 (-7.2 %) |
| 2 | 37034 | 37139 | +105 (+0.3 %) | 37139 | +105 (+0.3 %) |
| 3 | 37900 | 37311 | -589 (-1.6 %) | 37570 | -330 (-0.9 %) |
| 4 | 39934 | 40045 | +111 (+0.3 %) | 40045 | +111 (+0.3 %) |
| 5 | 38084 | 39491 | +1407 (+3.7 %) | 38567 | +483 (+1.3 %) |

## Decisiones de b1 (845 con candidatas; 0 con una sola candidata, sin gap)

Percentiles de los gaps (u.t., segunda − mejor, sobre todas las candidatas):

| | p10 | p20 | p30 | p40 | p50 | p60 | p70 | p80 | p90 |
|---|---|---|---|---|---|---|---|---|---|
| gap_finish | 76.3 | 92.7 | 115.6 | 124.6 | 141.2 | 164.3 | 187.6 | 202.2 | 233.4 |
| gap_finish_plus_next | 33.8 | 77.8 | 86.6 | 115.6 | 139.5 | 164.3 | 191.9 | 202.2 | 262.5 |

Nivel con el filtro del agente (`aclopi.agent.triage.classify`), % de decisiones de b1 (obvia / dudosa / muy reñida):

| U_amplio \ U_estrecho | 30 | 50 | 80 |
|---|---|---|---|
| 100 | 60 / 31 / 9 | 60 / 26 / 13 | 60 / 15 / 25 |
| 150 | 39 / 53 / 9 | 39 / 48 / 13 | 39 / 37 / 25 |
| 200 | 17 / 74 / 9 | 17 / 69 / 13 | 17 / 58 / 25 |
