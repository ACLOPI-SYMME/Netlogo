# Agente con LLM real frente a rule3 / b1 / b1b (S0, semillas 1 2 3 4 5, 30 productos)

| Estrategia | n | makespan medio | desv. | mean_flow_time |
|---|---|---|---|---|
| rule3 | 5 | 38300 | 1065 | 2070.2 |
| b1 | 5 | 37952 | 1772 | 1981.6 |
| b1b | 5 | 37819 | 1599 | 1989.0 |
| agent | 5 | 37819 | 1599 | 1989.0 |

Prueba pareada por semilla (makespan, ticks):

| Comparación | n | diferencia media | IC 95 % | % |
|---|---|---|---|---|
| agent − rule3 | 5 | -481 | [-2111, +1150] | -1.3 % |
| agent − b1 | 5 | -133 | [-699, +433] | -0.4 % |

Decisiones del agente: 845 en 5 corridas.

| Nivel | % |
|---|---|
| code-obvious | 60.1 |
| llm | 39.9 |
| llm-what-if | 0.0 |
| code-fallback | 0.0 |

- Llamadas al LLM: 337; fallidas 0 (0.0 %); JSON inválido 0 (0.0 %).
- Latencia del LLM: p50 2562 ms, p95 3086 ms.
- What-if pedidos: 0 (ofrecidos 118).
- Rechazos 409/422: 0 .
- Eligió distinto de B1: 2 de 845 (0.2 %).
