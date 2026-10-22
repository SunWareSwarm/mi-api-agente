# API del orquestador multi-agente (FastAPI + Redis + LangSmith)

Pre-entrega 7 — Curso AI Engineering (CoderHouse): **API de producción y monitoreo activo**.

Expone el orquestador multi-agente del Módulo 6 (supervisor + investigador + analista + synthesizer)
como una API REST asíncrona:

| Requisito | Dónde está |
|---|---|
| Endpoints asíncronos (encolar y devolver `job_id`) | `app/main.py`, `app/worker.py` |
| Estado de jobs y checkpoints de LangGraph en Redis | `app/jobs.py`, `app/graph.py`, `app/main.py` |
| Observabilidad (trazas, costo, latencia) con LangSmith | `app/observability.py` |
| Human-in-the-loop (pausa + `POST /tasks/{id}/approve`) | `app/hitl.py` |
| Prueba de carga con 5 peticiones concurrentes | `scripts/load_test.py` |

## Arquitectura

```
Cliente ──POST /tasks──▶ API (FastAPI) ──crea job PENDING──▶ Redis
   ▲                         │ responde 202 + job_id al instante
   │                         ▼
   │                    Worker (tarea en segundo plano, async)
   │                         │ marca RUNNING y ejecuta el grafo (thread_id = job_id)
   │                         ├──checkpoints──▶ Redis
   │                         ├──trazas───────▶ LangSmith
   │                         └─ ¿tarea crítica? ─▶ interrupt ─▶ WAITING_APPROVAL
   ├──POST /tasks/{id}/approve ─────────────────────────────────┘ (reanuda)
   └──GET /tasks/{id} ◀── lee estado ── Redis ◀── DONE | FAILED (+ error)
```

El grafo (diagrama completo en `docs/graph.mmd`):
`supervisor ⇄ researcher / analyst → synthesizer → (si hay destinatario) approval → send_report`.

- Nada bloquea el event loop: el grafo corre con `astream` async nativo y Redis usa el cliente async.
- Cualquier excepción en segundo plano deja el job en `FAILED` con el motivo (nunca queda en `RUNNING` para siempre).
  También hay un tiempo máximo por ejecución (`JOB_TIMEOUT_SECONDS`).
- Estados: `PENDING → RUNNING → DONE`, con `WAITING_APPROVAL` en medio para tareas críticas, o `FAILED`.

## Requisitos

- Python 3.12+
- Docker Desktop (para Redis Stack; en Windows Redis no corre de forma nativa)
- Claves: Google AI Studio (`GOOGLE_API_KEY`), Tavily (`TAVILY_API_KEY`) y LangSmith (`LANGSMITH_API_KEY`)

## Cómo levantarlo

```bash
python -m venv .venv
source .venv/bin/activate            # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt  # solo la API: requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env   -> completa tus claves
docker compose up -d redis           # Redis Stack (RedisJSON + RediSearch)
uvicorn app.main:app --reload
```

Documentación interactiva: http://localhost:8000/docs

Alternativa, todo en Docker (API + Redis): `docker compose up --build`.

Al arrancar, el log debe decir `LangSmith: trazas ACTIVAS -> proyecto 'mi-api-agente'`.

## Probar el patrón ticket y consulta

```bash
curl -X POST localhost:8000/tasks -H "Content-Type: application/json" \
  -d '{"query":"¿Cuál es la población de Chile y de Argentina, y la diferencia porcentual?"}'
# -> 202 {"job_id":"<id>","status":"PENDING"}

curl localhost:8000/tasks/<id>       # repetir hasta status = DONE (o FAILED, con el motivo en "error")
```

Mientras corre, `current_node` indica el último nodo del grafo que terminó.
(En Windows PowerShell usa `curl.exe`, o prueba todo desde http://localhost:8000/docs.)

## Human-in-the-loop (aprobación humana)

Una tarea es **crítica** cuando pide enviar el informe a alguien (`send_report_to`). Esa acción
(`enviar_informe`, simulada) tiene efecto secundario y no se puede deshacer, así que el grafo se
detiene antes de ejecutarla.

```bash
# 1. Crear la tarea crítica
curl -X POST localhost:8000/tasks -H "Content-Type: application/json" \
  -d '{"query":"Compara la población de Chile y Argentina","send_report_to":"jefa@ejemplo.com"}'

# 2. Esperar a que quede en WAITING_APPROVAL; "approval_request" muestra el borrador a aprobar
curl localhost:8000/tasks/<id>

# 3. Decidir (approved=false rechaza: el job termina en DONE sin enviar nada)
curl -X POST localhost:8000/tasks/<id>/approve -H "Content-Type: application/json" \
  -d '{"approved":true,"comment":"ok"}'

# 4. El job vuelve a RUNNING y termina en DONE; "delivery" dice "enviado a ..." o "rechazado: ..."
curl localhost:8000/tasks/<id>
```

Si el job no está esperando aprobación responde `409`; si dos personas aprueban a la vez, solo la primera
reanuda el grafo. El estado pausado vive en los checkpoints de Redis, así que la aprobación puede llegar
mucho después de la pausa.

## Observabilidad (LangSmith)

Con `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` y `LANGSMITH_PROJECT` en el `.env`, cada ejecución del
grafo queda registrada como una traza (nodos, llamadas al LLM, tools, tokens, latencia y costo).

Cada traza raíz se llama `orquestador`, lleva la etiqueta `pre-entrega-7` y el metadato `job_id`
(el mismo que devuelve `POST /tasks`), así puedes saltar de un job a su traza. Las reanudaciones tras
una aprobación aparecen aparte como `orquestador-reanudacion`.

Si la columna de costo sale vacía, LangSmith no tiene el precio de tu modelo: agrégalo en su tabla de precios
(Settings → Model pricing) **antes** de la prueba de carga; los cambios de precio no se aplican a trazas ya registradas.

## Prueba de carga (5 peticiones concurrentes)

Con Redis y la API levantados (y el log mostrando las trazas activas), en otra terminal:

```bash
python -m scripts.load_test            # 5 peticiones simultáneas, espera a que terminen
```

Usa consultas **no críticas** (sin `send_report_to`), para que ningún job quede esperando aprobación.
Al terminar imprime la duración de cada job y la ventana de tiempo de la corrida. Luego:

1. En LangSmith, abre el proyecto y filtra esa ventana: captura la tabla de trazas, el **costo por ejecución**
   y la **latencia p95** (columna/estadística de latencia del proyecto).
2. Respaldo / contraste con lo que muestra el dashboard:

```bash
python -m scripts.latency_report --minutes 30
```

Guarda las capturas en `screenshots/` (trazas anidadas por nodo, costo, p95).

## Tests (sin red, sin claves, sin costo)

```bash
pytest
```

Los tests reemplazan a Gemini y a los agentes por dobles de prueba y a Redis por `fakeredis`.
Cubren el patrón ticket y consulta, `FAILED` ante errores y timeouts, el HITL (pausa, aprobación, rechazo,
doble aprobación) y la prueba de carga.

## Estructura

```
app/
  main.py            API: POST /tasks, GET /tasks/{id}, GET /health
  hitl.py            nodos approval y send_report + POST /tasks/{id}/approve
  worker.py          ejecuta/reanuda el grafo y actualiza el estado en Redis
  graph.py           orquestador del Módulo 6 + checkpointer de Redis
  jobs.py            estado de los jobs en Redis (única parte que sabe cómo se guardan)
  observability.py   configuración y metadatos de trazas de LangSmith
  agents/ tools/     supervisor, investigador, analista y herramientas
scripts/             load_test.py, latency_report.py, make_diagram.py
tests/               pruebas offline
docs/graph.mmd       diagrama del grafo (Mermaid)
screenshots/         capturas del dashboard (trazas, costo, p95)
```

## Problemas frecuentes

- `unknown command 'FT.INFO'` al arrancar: estás usando un Redis sin módulos. El checkpointer de LangGraph
  necesita RedisJSON y RediSearch; usa la imagen `redis/redis-stack-server` del `docker-compose.yml`.
- `Connection refused` al arrancar: Redis no está levantado (`docker compose up -d redis`).
- Errores 429 de Gemini o Tavily durante la prueba de carga: son límites de cuota; el job queda en `FAILED`
  con el motivo. Repite la prueba o baja la concurrencia con `--n`.
- No aparecen trazas: revisa que el log de arranque diga "trazas ACTIVAS" y que la API key de LangSmith sea válida.
