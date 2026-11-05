# Decisiones de la sesión `7836cb2f99d74d5cafc45e2eccc837d6`

Estrategia: agent. Registro: `results\a4_1105\pilot_decisions.jsonl`. Sin eventos: no hay fin real.

| Métrica | Valor |
|---|---|
| decisions | 60 |
| n_code-obvious | 32 |
| pct_code-obvious | 53.3 |
| n_llm | 23 |
| pct_llm | 38.3 |
| n_llm-what-if | 3 |
| pct_llm-what-if | 5.0 |
| n_code-fallback | 2 |
| pct_code-fallback | 3.3 |
| n_heuristic | 0 |
| pct_heuristic | 0.0 |
| n_no_decision | 0 |
| what_if_requested | 3 |
| what_if_done | 3 |
| what_if_skipped | 0 |
| latency_mean_ms_code-obvious | 29.3 |
| latency_p95_ms_code-obvious | 47.0 |
| latency_mean_ms_llm | 536.0 |
| latency_p95_ms_llm | 562.0 |
| latency_mean_ms_llm-what-if | 3745.0 |
| latency_p95_ms_llm-what-if | 3922.0 |
| latency_mean_ms_code-fallback | 547.0 |
| latency_p95_ms_code-fallback | 547.0 |
| compared_with_b1 | 60 |
| differs_from_b1 | 0 |
| pct_differs_from_b1 | 0.0 |
| decisions_with_real_end | 0 |

| tick | product | seq | operation | current_machine | candidates | gap_finish | gap_finish_plus_next | triage | level | machine | b1_machine | differs_from_b1 | reason | total_ms | llm_ms | what_if_ms | what_if | estimated_finish | real_end | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 366 | 200 | 1 |  |  | M2 f=535.1 fpn=535.1; M5 f=549.3 fpn=549.3; M3 f=625.6 fpn=625.6; M7 f=722.2 fpn=722.2 | 14.2 | 14.2 | very_close | llm-what-if | M2 | M2 | False | fake decision | 3563.0 | 503.9 508.0 | 2531.0 | ok | 535.1 |  |  |
| 1011 | 201 | 1 |  |  | M5 f=749.2 fpn=749.2; M3 f=825.5 fpn=825.5; M7 f=922.1 fpn=922.1; M2 f=1363.7 fpn=1363.7 | 76.3 | 76.3 | uncertain | llm | M5 | M5 | False | fake decision | 531.0 | 511.7 |  |  | 749.2 |  |  |
| 1049 | 200 | 2 |  |  | M2 f=742.1 fpn=742.1; M3 f=866.7 fpn=866.7; M5 f=929.3 fpn=929.3; M7 f=1102.9 fpn=1102.9 | 124.6 | 124.6 | uncertain | llm | M2 | M2 | False | fake decision | 531.0 | 508.9 |  |  | 742.1 |  |  |
| 1656 | 202 | 1 |  |  | M3 f=1025.5 fpn=1025.5; M7 f=1122.1 fpn=1122.1; M5 f=1563.7 fpn=1563.7; M2 f=1582.1 fpn=1582.1 | 96.6 | 96.6 | uncertain | llm | M3 | M3 | False | fake decision | 531.0 | 491.1 |  |  | 1025.5 |  |  |
| 1717 | 200 | 3 |  |  | M2 f=953.0 fpn=953.0; M3 f=1077.5 fpn=1077.5; M7 f=1313.8 fpn=1313.8; M5 f=1582.6 fpn=1698.2 | 124.6 | 124.6 | uncertain | llm | M2 | M2 | False | fake decision | 563.0 | 520.2 |  |  | 953.0 |  |  |
| 1740 | 201 | 2 |  |  | M5 f=950.5 fpn=950.5; M7 f=1152.7 fpn=1152.7; M3 f=1252.7 fpn=1252.7; M2 f=1793.0 fpn=1793.0 |  |  | obvious | code-obvious | M5 | M5 | False | obvious: single candidate | 32.0 |  |  |  | 950.5 |  |  |
| 2389 | 201 | 3 |  |  | M5 f=1159.1 fpn=1159.1; M7 f=1361.3 fpn=1361.3; M3 f=1461.3 fpn=1530.5; M2 f=1793.0 fpn=1902.3 |  |  | obvious | code-obvious | M5 | M5 | False | obvious: single candidate | 31.0 |  |  |  | 1159.1 |  |  |
| 2397 | 200 | 4 |  |  | M2 f=1174.7 fpn=1174.7; M3 f=1299.3 fpn=1299.3; M6 f=1448.4 fpn=1448.4; M7 f=1535.5 fpn=1535.5 | 124.6 | 124.6 | uncertain | llm | M2 | M2 | False | fake decision | 547.0 | 516.2 |  |  | 1174.7 |  |  |
| 2624 | 203 | 1 |  |  | M3 f=1325.5 fpn=1325.5; M7 f=1422.2 fpn=1422.2; M2 f=1804.7 fpn=1804.7; M5 f=1999.1 fpn=1999.1 | 96.6 | 96.6 | uncertain | llm | M3 | M3 | False | fake decision | 547.0 | 514.4 |  |  | 1325.5 |  |  |
| 2631 | 202 | 2 |  |  | M3 f=1235.6 fpn=1235.6; M7 f=1555.8 fpn=1555.8; M2 f=1804.7 fpn=1804.7; M5 f=1999.1 fpn=1999.1 |  |  | obvious | code-obvious | M3 | M3 | False | obvious: single candidate | 31.0 |  |  |  | 1235.6 |  |  |
| 3062 | 201 | 4 |  |  | M5 f=1403.1 fpn=1403.1; M6 f=1518.7 fpn=1518.7; M4 f=1590.7 fpn=1590.7; M7 f=1605.3 fpn=1605.3 | 115.6 | 115.6 | uncertain | llm | M5 | M5 | False | fake decision | 532.0 | 507.9 |  |  | 1403.1 |  |  |
| 3112 | 200 | 5 |  |  | M2 f=1388.2 fpn=1388.2; M6 f=1661.9 fpn=1661.9; M7 f=1749.0 fpn=1749.0; M3 f=2075.6 fpn=2144.7 |  |  | obvious | code-obvious | M2 | M2 | False | obvious: single candidate | 32.0 |  |  |  | 1388.2 |  |  |
| 3269 | 204 | 1 |  |  | M7 f=1622.1 fpn=1622.1; M2 f=1808.2 fpn=1808.2; M3 f=2075.6 fpn=2075.6; M5 f=2243.1 fpn=2243.1 |  |  | obvious | code-obvious | M7 | M7 | False | obvious: single candidate | 16.0 |  |  |  | 1622.1 |  |  |
| 3309 | 202 | 3 |  |  | M3 f=1454.5 fpn=1454.5; M7 f=1774.7 fpn=1774.7; M2 f=1808.2 fpn=1808.2; M5 f=2243.1 fpn=2358.7 |  |  | obvious | code-obvious | M3 | M3 | False | obvious: single candidate | 32.0 |  |  |  | 1454.5 |  |  |
| 3801 | 200 | 6 |  |  | M2 f=1604.5 fpn=1892.4; M4 f=1713.9 fpn=1926.2; M6 f=1878.2 fpn=2086.3; M7 f=1965.3 fpn=2086.2 | 109.4 | 33.8 | very_close | llm-what-if | M2 | M2 | False | fake decision | 3922.0 | 491.4 516.7 | 2875.0 | ok | 1604.5 |  |  |
| 3849 | 201 | 5 |  |  | M5 f=1610.1 fpn=1610.1; M6 f=1725.7 fpn=1846.9; M4 f=1797.7 fpn=1797.7; M7 f=1812.3 fpn=1812.3 | 115.6 | 236.8 | uncertain | llm | M5 | M5 | False | fake decision | 547.0 | 502.8 |  |  | 1610.1 |  |  |
| 3914 | 205 | 1 |  |  | M2 f=1814.5 fpn=1814.5; M7 f=1822.0 fpn=1822.0; M5 f=2240.1 fpn=2240.1; M3 f=2504.5 fpn=2504.5 | 7.6 | 7.6 | very_close | llm | M2 | M2 | False | fake decision | 531.0 | 490.7 |  |  | 1814.5 |  |  |
| 4015 | 202 | 4 |  |  | M3 f=1666.2 fpn=1735.3; M6 f=1899.6 fpn=1899.6; M7 f=1986.4 fpn=1986.4; M2 f=2024.5 fpn=2024.5 |  |  | obvious | code-obvious | M3 | M3 | False | obvious: single candidate | 31.0 |  |  |  | 1666.2 |  |  |
| 4517 | 201 | 6 |  |  | M5 f=1826.1 fpn=1826.1; M4 f=2013.7 fpn=2013.7; M7 f=2450.6 fpn=2450.6; M3 f=2506.2 fpn=2506.2 |  |  | obvious | code-obvious | M5 | M5 | False | obvious: single candidate | 15.0 |  |  |  | 1826.1 |  |  |
| 4557 | 204 | 2 |  |  | M7 f=1826.5 fpn=1826.5; M5 f=2246.1 fpn=2361.7; M3 f=2506.2 fpn=2506.2; M2 f=2645.3 fpn=2645.3 |  |  | obvious | code-obvious | M7 | M7 | False | obvious: single candidate | 32.0 |  |  |  | 1826.5 |  |  |
| 4698 | 202 | 5 |  |  | M4 f=1936.7 fpn=1936.7; M6 f=2101.0 fpn=2101.0; M7 f=2456.5 fpn=2456.5; M2 f=2645.3 fpn=2754.7 |  |  | obvious | code-obvious | M4 | M4 | False | obvious: single candidate | 31.0 |  |  |  | 1936.7 |  |  |
| 4882 | 206 | 1 |  |  | M5 f=2246.1 fpn=2246.1; M7 f=2456.5 fpn=2456.5; M3 f=2497.6 fpn=2497.6; M2 f=2645.3 fpn=2645.3 |  |  | obvious | code-obvious | M5 | M5 | False | obvious: single candidate | 31.0 |  |  |  | 2246.1 |  |  |
| 5184 | 205 | 2 |  |  | M2 f=2028.2 fpn=2028.2; M5 f=2456.1 fpn=2571.7; M7 f=2456.5 fpn=2456.5; M3 f=2497.6 fpn=2497.6 |  |  | obvious | code-obvious | M2 | M2 | False | obvious: single candidate | 31.0 |  |  |  | 2028.2 |  |  |
| 5214 | 201 | 7 |  |  | M5 f=2036.0 fpn=2165.6; M4 f=2223.6 fpn=2435.9; M7 f=2456.7 fpn=2577.6; M3 f=2497.6 fpn=2745.0 |  |  | obvious | code-obvious | M5 | M5 | False | obvious: single candidate | 47.0 |  |  |  | 2036.0 |  |  |
| 5215 | 204 | 3 |  |  | M7 f=2040.5 fpn=2040.5; M6 f=2180.0 fpn=2180.0; M3 f=2497.6 fpn=2566.7; M2 f=2658.2 fpn=2658.2 | 139.5 | 139.5 | uncertain | llm | M7 | M7 | False | fake decision | 562.0 | 518.0 |  |  | 2040.5 |  |  |
| 5454 | 203 | 2 |  |  | M3 f=2132.7 fpn=2132.7; M5 f=2456.0 fpn=2456.0; M7 f=2460.5 fpn=2460.5; M2 f=2658.2 fpn=2658.2 |  |  | obvious | code-obvious | M3 | M3 | False | obvious: single candidate | 31.0 |  |  |  | 2132.7 |  |  |
| 5527 | 207 | 1 |  |  | M7 f=2460.5 fpn=2460.5; M3 f=2552.7 fpn=2552.7; M2 f=2658.2 fpn=2658.2; M5 f=2876.0 fpn=2876.0 | 92.2 | 92.2 | uncertain | code-fallback | M7 | M7 | False | fallback (llm-invalid-json) | 547.0 | 509.1 |  |  | 2460.5 |  | llm-invalid-json |
| 5644 | 202 | 6 |  |  | M4 f=2181.2 fpn=2181.2; M6 f=2379.6 fpn=2500.8; M7 f=2670.5 fpn=2670.5; M5 f=2876.0 fpn=2876.0 |  |  | obvious | code-obvious | M4 | M4 | False | obvious: single candidate | 15.0 |  |  |  | 2181.2 |  |  |
| 5866 | 205 | 3 |  |  | M2 f=2241.8 fpn=2241.8; M6 f=2515.5 fpn=2515.5; M3 f=2552.7 fpn=2621.8; M7 f=2670.5 fpn=2670.5 |  |  | obvious | code-obvious | M2 | M2 | False | obvious: single candidate | 31.0 |  |  |  | 2241.8 |  |  |
| 5905 | 204 | 4 |  |  | M7 f=2248.8 fpn=2369.7; M6 f=2388.3 fpn=2596.4; M4 f=2601.2 fpn=2813.5; M2 f=2661.8 fpn=2949.7 | 139.5 | 226.7 | uncertain | llm | M7 | M7 | False | fake decision | 547.0 | 511.4 |  |  | 2248.8 |  |  |
| 6203 | 203 | 3 |  |  | M3 f=2337.5 fpn=2406.6; M2 f=2661.8 fpn=2771.2; M7 f=2668.8 fpn=2668.8; M5 f=2880.9 fpn=2880.9 |  |  | obvious | code-obvious | M3 | M3 | False | obvious: single candidate | 32.0 |  |  |  | 2337.5 |  |  |
| 6359 | 202 | 7 |  |  | M4 f=2384.7 fpn=2597.0; M3 f=2602.0 fpn=2849.4; M7 f=2669.9 fpn=2790.8; M5 f=2880.9 fpn=3010.5 |  |  | obvious | code-obvious | M4 | M4 | False | obvious: single candidate | 32.0 |  |  |  | 2384.7 |  |  |
| 6495 | 208 | 1 |  |  | M3 f=2547.5 fpn=2547.5; M2 f=2661.8 fpn=2661.8; M7 f=2668.8 fpn=2668.8; M5 f=2880.9 fpn=2880.9 | 114.3 | 114.3 | uncertain | llm | M3 | M3 | False | fake decision | 531.0 | 506.9 |  |  | 2547.5 |  |  |
| 6555 | 205 | 4 |  |  | M2 f=2445.7 fpn=2733.6; M4 f=2594.7 fpn=2807.0; M6 f=2719.4 fpn=2927.5; M7 f=2806.5 fpn=2927.4 | 149.0 | 73.4 | uncertain | llm | M2 | M2 | False | fake decision | 531.0 | 507.7 |  |  | 2445.7 |  |  |
| 6623 | 206 | 2 |  |  | M5 f=2491.1 fpn=2491.1; M7 f=2693.3 fpn=2693.3; M2 f=2702.8 fpn=2702.8; M3 f=2793.3 fpn=2793.3 |  |  | obvious | code-obvious | M5 | M5 | False | obvious: single candidate | 16.0 |  |  |  | 2491.1 |  |  |
| 6863 | 203 | 4 |  |  | M4 f=2609.3 fpn=2609.3; M6 f=2773.6 fpn=2773.6; M5 f=2911.1 fpn=2911.1; M7 f=3293.9 fpn=3293.9 |  |  | obvious | code-obvious | M4 | M4 | False | obvious: single candidate | 31.0 |  |  |  | 2609.3 |  |  |
| 7273 | 207 | 2 |  |  | M7 f=2677.3 fpn=2677.3; M2 f=2880.4 fpn=2880.4; M5 f=2911.1 fpn=2911.1; M3 f=2970.8 fpn=2970.8 |  |  | obvious | code-obvious | M7 | M7 | False | obvious: single candidate | 31.0 |  |  |  | 2677.3 |  |  |
| 7359 | 206 | 3 |  |  | M5 f=2693.7 fpn=2809.3; M2 f=2905.4 fpn=2905.4; M3 f=2995.9 fpn=2995.9; M7 f=3517.3 fpn=3517.3 | 211.7 | 96.1 | uncertain | llm | M5 | M5 | False | fake decision | 532.0 | 502.1 |  |  | 2693.7 |  |  |
| 7463 | 209 | 1 |  |  | M2 f=2735.1 fpn=2735.1; M5 f=2903.7 fpn=2903.7; M3 f=3380.2 fpn=3380.2; M7 f=3517.3 fpn=3517.3 |  |  | obvious | code-obvious | M2 | M2 | False | obvious: single candidate | 31.0 |  |  |  | 2735.1 |  |  |
| 7550 | 208 | 2 |  |  | M3 f=2753.8 fpn=2753.8; M5 f=2903.7 fpn=2903.7; M2 f=2915.6 fpn=2915.6; M7 f=3517.3 fpn=3517.3 | 149.9 | 149.9 | uncertain | llm | M3 | M3 | False | fake decision | 532.0 | 502.3 |  |  | 2753.8 |  |  |
| 7740 | 203 | 5 |  |  | M4 f=2832.9 fpn=2832.9; M5 f=2944.8 fpn=2944.8; M6 f=3031.3 fpn=3152.5; M7 f=3517.3 fpn=3517.3 | 111.9 | 111.9 | uncertain | llm | M4 | M4 | False | fake decision | 531.0 | 508.8 |  |  | 2832.9 |  |  |
| 7959 | 207 | 3 |  |  | M7 f=2883.7 fpn=2883.7; M2 f=3086.8 fpn=3086.8; M5 f=3101.0 fpn=3216.6; M3 f=3593.8 fpn=3593.8 |  |  | obvious | code-obvious | M7 | M7 | False | obvious: single candidate | 32.0 |  |  |  | 2883.7 |  |  |
| 8012 | 206 | 4 |  |  | M6 f=3060.7 fpn=3060.7; M2 f=3156.8 fpn=3156.8; M3 f=3593.8 fpn=3593.8; M7 f=3723.7 fpn=3723.7 | 96.1 | 96.1 | uncertain | llm | M6 | M6 | False | fake decision | 546.0 | 517.5 |  |  | 3060.7 |  |  |
| 8146 | 209 | 2 |  |  | M2 f=2939.9 fpn=2939.9; M5 f=3127.1 fpn=3242.7; M3 f=3593.8 fpn=3593.8; M7 f=3723.7 fpn=3723.7 |  |  | obvious | code-obvious | M2 | M2 | False | obvious: single candidate | 47.0 |  |  |  | 2939.9 |  |  |
| 8206 | 208 | 3 |  |  | M3 f=2955.9 fpn=2955.9; M5 f=3102.8 fpn=3218.4; M2 f=3569.9 fpn=3569.9; M7 f=3723.7 fpn=3723.7 | 146.9 | 262.5 | uncertain | code-fallback | M3 | M3 | False | fallback (llm-invalid-json) | 547.0 | 510.0 |  |  | 2955.9 |  | llm-invalid-json |
| 8461 | 203 | 6 |  |  | M4 f=3044.7 fpn=3044.7; M5 f=3156.6 fpn=3156.6; M3 f=3585.9 fpn=3585.9; M7 f=3723.7 fpn=3723.7 | 111.9 | 111.9 | uncertain | llm | M4 | M4 | False | fake decision | 531.0 | 510.1 |  |  | 3044.7 |  |  |
| 8625 | 207 | 4 |  |  | M7 f=3094.3 fpn=3094.3; M6 f=3233.8 fpn=3233.8; M2 f=3569.9 fpn=3569.9; M3 f=3585.9 fpn=3655.0 | 139.5 | 139.5 | uncertain | llm | M7 | M7 | False | fake decision | 516.0 | 502.3 |  |  | 3094.3 |  |  |
| 8807 | 209 | 3 |  |  | M2 f=3141.0 fpn=3141.0; M6 f=3414.7 fpn=3414.7; M3 f=3585.9 fpn=3655.0; M7 f=3934.3 fpn=3934.3 |  |  | obvious | code-obvious | M2 | M2 | False | obvious: single candidate | 31.0 |  |  |  | 3141.0 |  |  |
| 8858 | 208 | 4 |  |  | M3 f=3172.7 fpn=3172.7; M6 f=3406.1 fpn=3406.1; M2 f=3561.0 fpn=3561.0; M7 f=3934.3 fpn=3934.3 |  |  | obvious | code-obvious | M3 | M3 | False | obvious: single candidate | 31.0 |  |  |  | 3172.7 |  |  |
| 9145 | 203 | 7 |  |  | M4 f=3281.8 fpn=3494.1; M5 f=3393.7 fpn=3523.3; M3 f=3592.7 fpn=3840.1; M7 f=3934.3 fpn=4055.2 | 111.9 | 29.2 | very_close | llm | M4 | M4 | False | fake decision | 516.0 | 492.2 |  |  | 3281.8 |  |  |
| 9196 | 206 | 5 |  |  | M6 f=3284.0 fpn=3284.0; M2 f=3574.1 fpn=3683.5; M3 f=3664.7 fpn=3733.8; M7 f=3934.3 fpn=3934.3 |  |  | obvious | code-obvious | M6 | M6 | False | obvious: single candidate | 31.0 |  |  |  | 3284.0 |  |  |
| 9305 | 207 | 5 |  |  | M7 f=3296.7 fpn=3296.7; M2 f=3561.0 fpn=3670.4; M4 f=3575.1 fpn=3575.1; M6 f=3704.0 fpn=3704.0 |  |  | obvious | code-obvious | M7 | M7 | False | obvious: single candidate | 15.0 |  |  |  | 3296.7 |  |  |
| 9455 | 209 | 4 |  |  | M2 f=3345.2 fpn=3633.1; M4 f=3491.8 fpn=3704.1; M6 f=3704.0 fpn=3912.1; M7 f=3926.7 fpn=4047.6 | 146.6 | 71.0 | uncertain | llm | M2 | M2 | False | fake decision | 547.0 | 503.2 |  |  | 3345.2 |  |  |
| 9558 | 208 | 5 |  |  | M3 f=3384.1 fpn=3453.3; M2 f=3555.2 fpn=3664.6; M6 f=3704.0 fpn=3704.0; M7 f=3926.7 fpn=3926.7 |  |  | obvious | code-obvious | M3 | M3 | False | obvious: single candidate | 32.0 |  |  |  | 3384.1 |  |  |
| 9917 | 206 | 6 |  |  | M6 f=3496.3 fpn=3617.5; M5 f=3800.7 fpn=3800.7; M4 f=3861.8 fpn=3861.8; M7 f=3926.7 fpn=3926.7 |  |  | obvious | code-obvious | M6 | M6 | False | obvious: single candidate | 15.0 |  |  |  | 3496.3 |  |  |
| 9957 | 207 | 6 |  |  | M7 f=3503.7 fpn=3503.7; M6 f=3706.3 fpn=3827.5; M5 f=3720.9 fpn=3720.9; M4 f=3782.1 fpn=3782.1 |  |  | obvious | code-obvious | M7 | M7 | False | obvious: single candidate | 16.0 |  |  |  | 3503.7 |  |  |
| 10240 | 208 | 6 |  |  | M4 f=3658.6 fpn=3658.6; M5 f=3736.4 fpn=3736.4; M6 f=3822.9 fpn=3944.1; M7 f=3923.7 fpn=3923.7 | 77.8 | 77.8 | uncertain | llm | M4 | M4 | False | fake decision | 531.0 | 495.0 |  |  | 3658.6 |  |  |
| 10601 | 206 | 7 |  |  | M7 f=3923.7 fpn=4044.6; M5 f=4034.1 fpn=4163.7; M4 f=4095.2 fpn=4307.5; M3 f=4110.4 fpn=4357.8 | 110.5 | 119.2 | uncertain | llm | M7 | M7 | False | fake decision | 515.0 | 491.5 |  |  | 3923.7 |  |  |
| 10625 | 207 | 7 |  |  | M7 f=3713.7 fpn=3834.6; M5 f=3931.0 fpn=4060.6; M4 f=3992.1 fpn=4204.4; M3 f=4007.2 fpn=4254.6 |  |  | obvious | code-obvious | M7 | M7 | False | obvious: single candidate | 47.0 |  |  |  | 3713.7 |  |  |
| 11125 | 208 | 7 |  |  | M4 f=3859.1 fpn=4071.4; M5 f=3971.0 fpn=4100.6; M3 f=4076.4 fpn=4323.8; M7 f=4144.3 fpn=4265.2 | 111.9 | 29.2 | very_close | llm-what-if | M4 | M4 | False | fake decision | 3750.0 | 511.6 516.2 | 2688.0 | ok | 3859.1 |  |  |
