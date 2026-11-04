# Despliegue local con Docker Compose (L5.7)

`docker-compose.yml`, en la raíz del repo, levanta tres servicios en una red interna:

| Servicio | Imagen | Qué es | Puerto publicado |
|---|---|---|---|
| `platform` | `aclopi-sim` (`docker/Dockerfile`, `CMD` = la API) | API, workers de NetLogo y `/ui` | **8000** |
| `agent-mock` | `aclopi-sim`, con `python -m aclopi.agent_mock` | Agente simulado (`docs/agent-api.md`) | ninguno |
| `dynamodb-local` | `amazon/dynamodb-local:2.5.2` | Resultados y sets de productos, en memoria | ninguno |

## Preparar

```powershell
Copy-Item .env.example .env      # si no existe; luego define ACLOPI_AGENT_TOKEN con un valor propio
```

- `.env` no se sube a git.
- Compose lee de ahí `ACLOPI_AGENT_TOKEN` y se lo pasa a la plataforma y al agente.
- Las rutas de NetLogo de `.env` solo se usan en Windows; dentro del contenedor no cuentan.

## Levantar, ver, parar

```powershell
docker compose build
docker compose up -d
docker compose ps                    # platform pasa a "healthy" cuando /health/ready responde 200 (~1,5 min)
docker compose logs -f platform      # logs JSON; también agent-mock y dynamodb-local
docker compose down                  # para y borra los contenedores (DynamoDB Local es en memoria: se pierde)
```

Página de prueba: `http://localhost:8000/ui`. API: `http://localhost:8000/docs`.

## Variables de la plataforma en Compose

| Variable | Valor | Para qué |
|---|---|---|
| `ACLOPI_AGENT_URL` | `http://agent-mock:8100` | Dónde está el agente |
| `ACLOPI_AGENT_TOKEN` | `.env` | Token compartido con el agente (`Authorization: Bearer`) |
| `ACLOPI_DYNAMODB_ENDPOINT` | `http://dynamodb-local:8000` | Activa el almacén DynamoDB (`aclopi/api/results.py`) |
| `ACLOPI_CREATE_TABLES` | `1` | Crea las tablas al arrancar (solo local; en la nube las crea la infraestructura) |
| `ACLOPI_AWS_REGION` | `eu-north-1` | Región de DynamoDB (Estocolmo). DynamoDB Local la ignora |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | `local` | DynamoDB Local acepta cualquier valor |

**Límites de la plataforma:** son los de L4 (`cpus: 4`, `cpuset: 0-3`, `mem_limit: 6g`).

**Healthchecks:**
- `platform` usa `/health/ready`. El `HEALTHCHECK` propio de la imagen usa `/health/live`, y Compose lo reemplaza.
- `agent-mock` usa `/health`.

**Reinicio:** `restart: unless-stopped`. Si DynamoDB Local todavía no acepta conexiones cuando arranca la plataforma, el arranque falla y Docker la reinicia.

## Tablas (prefijo `aclopi_`)

| Tabla | Clave | Contenido |
|---|---|---|
| `aclopi_runs` | `run_id` | Una por corrida: estado (`finished`, `failed` o `stopped`), motivo, regla, estrategia, semilla y su origen, horizonte, modo, set (id, hash y copia de la lista), KPIs, resumen de decisiones y resumen de what-if |
| `aclopi_decisions` | `run_id` + `seq` | Las decisiones de la corrida, escritas en lote al terminar. La seq de la operación va en `seq_op` |
| `aclopi_product_sets` | `id` | Sets de productos |

- **Cuándo se guarda una corrida:** al terminar, al fallar o al detenerse. Detenerse es `DELETE`, `reset`, inactividad o pérdida del worker.
- **Si DynamoDB falla:** el error se registra en el log y la corrida no se ve afectada.

Consultas: `GET /runs` (filtros `seed`, `strategy`, `rule`, `product_set_id`; paginado con `cursor`), `GET /runs/{id}` y `GET /runs/{id}/decisions`. La pestaña "Corridas" de `/ui` las muestra, con Repetir, Comparar y exportar a CSV.

## Probar

```powershell
python scripts\l5\smoke_compose.py        # con el stack levantado; usa ACLOPI_AGENT_TOKEN del entorno o de .env
```

El script:
1. sube un CSV de 8 productos, lo guarda como set y corre la regla 4 con `b1` en rápido, sin semilla. Comprueba `all_products_done`, el makespan, las decisiones, que la semilla aleatoria quedó guardada y que la corrida está en DynamoDB Local (`/runs`);
2. corre la regla 4 con `agent` en vivo durante 30 s. Comprueba las decisiones por WebSocket y el ritmo de ~32 ticks/s;
3. comprueba que `/health` muestra el agente.
