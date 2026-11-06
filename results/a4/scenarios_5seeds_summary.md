# Escenarios sin LLM (45 corridas)

Corridas: `results\a4\scenarios_5seeds.csv`. Makespan en ticks.
Sin terminar, fuera del resumen y de su par en la prueba pareada: rule3 S1 s4 (cap 180 s reached).

## S1

| Estrategia | n | makespan medio | desv. | mean_flow_time | eventos aplicados / saltados | todas terminadas |
|---|---|---|---|---|---|---|
| rule3 | 4 | 38138 | 2466 | 2039.6 | 24 / 0 | 4/5 |
| b1 | 5 | 38786 | 2493 | 1939.9 | 30 / 0 | 5/5 |
| b1b | 5 | 39049 | 2455 | 1930.5 | 30 / 0 | 5/5 |

Prueba pareada por semilla (makespan, ticks):

| Comparación | n | diferencia media | IC 95 % | % |
|---|---|---|---|---|
| b1 − rule3 | 4 | +393 | [-1813, +2599] | +1.0 % |
| b1b − rule3 | 4 | +716 | [-957, +2389] | +1.9 % |

## S2

| Estrategia | n | makespan medio | desv. | mean_flow_time | eventos aplicados / saltados | todas terminadas |
|---|---|---|---|---|---|---|
| rule3 | 5 | 39527 | 1213 | 2209.0 | 5 / 0 | 5/5 |
| b1 | 5 | 38173 | 1175 | 2076.6 | 5 / 0 | 5/5 |
| b1b | 5 | 38746 | 996 | 2081.5 | 5 / 0 | 5/5 |

Prueba pareada por semilla (makespan, ticks):

| Comparación | n | diferencia media | IC 95 % | % |
|---|---|---|---|---|
| b1 − rule3 | 5 | -1354 | [-2767, +58] | -3.4 % |
| b1b − rule3 | 5 | -781 | [-2475, +912] | -2.0 % |

## S3

| Estrategia | n | makespan medio | desv. | mean_flow_time | eventos aplicados / saltados | todas terminadas |
|---|---|---|---|---|---|---|
| rule3 | 5 | 39181 | 1508 | 2128.8 | 24 / 12 | 5/5 |
| b1 | 5 | 38351 | 1633 | 2043.1 | 20 / 16 | 5/5 |
| b1b | 5 | 38528 | 1071 | 2007.7 | 21 / 16 | 5/5 |

Prueba pareada por semilla (makespan, ticks):

| Comparación | n | diferencia media | IC 95 % | % |
|---|---|---|---|---|
| b1 − rule3 | 5 | -830 | [-4185, +2525] | -2.1 % |
| b1b − rule3 | 5 | -653 | [-2194, +888] | -1.7 % |
