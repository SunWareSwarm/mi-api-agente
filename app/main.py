"""API REST: recibe tareas, las encola y permite consultar su estado. No ejecuta nada pesado."""
import json
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from redis.asyncio import Redis

from app import jobs
from app.api_models import TaskAccepted, TaskCreate, TaskStatus
from app.config import REDIS_URL
from app.deps import GraphDep, RedisDep, get_graph, get_redis  # noqa: F401 (los tests los reemplazan)
from app.graph import build_graph
from app.hitl import router as hitl_router
from app.jobs import JobStatus
from app.observability import flush_traces, init_observability
from app.worker import run_job


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_observability()  # informa en el log si LangSmith quedó activo

    # ARRANQUE 1: conexión a Redis para el estado de los jobs.
    app.state.redis = Redis.from_url(REDIS_URL, decode_responses=True)
    await app.state.redis.ping()  # si Redis no está disponible, falla de inmediato y con claridad

    # ARRANQUE 2: checkpointer de LangGraph sobre Redis + grafo compilado (una sola vez).
    # `async with` mantiene abierta la conexión del checkpointer mientras la API vive.
    # Al entrar, crea los índices que necesita en Redis (requiere redis-stack).
    async with AsyncRedisSaver.from_conn_string(REDIS_URL) as checkpointer:
        app.state.graph = build_graph(checkpointer)
        yield  # <- aquí la API queda funcionando
    # APAGADO: el `async with` ya cerró el checkpointer; falta cerrar nuestra conexión.
    await app.state.redis.aclose()
    flush_traces()  # envía a LangSmith las trazas que aún estén en cola


app = FastAPI(title="API del orquestador multi-agente", lifespan=lifespan)
app.include_router(hitl_router)  # POST /tasks/{id}/approve


@app.post("/tasks", status_code=202, response_model=TaskAccepted)
async def create_task(body: TaskCreate, background: BackgroundTasks, redis: RedisDep, graph: GraphDep):
    job_id = await jobs.create_job(redis, body.query, body.send_report_to)
    background.add_task(run_job, redis, graph, job_id)  # se ejecuta DESPUÉS de enviar la respuesta
    return TaskAccepted(job_id=job_id, status=JobStatus.PENDING)


@app.get("/tasks/{job_id}", response_model=TaskStatus)
async def read_task(job_id: str, redis: RedisDep):
    job = await jobs.get_job(redis, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado (o expirado)")
    if "approval_request" in job:  # en Redis se guarda como texto JSON
        job["approval_request"] = json.loads(job["approval_request"])
    # Solo mientras espera aprobación: ya decidido, ese dato deja de ser relevante.
    if job["status"] != JobStatus.WAITING_APPROVAL:
        job.pop("approval_request", None)
    return TaskStatus(job_id=job_id, **job)


@app.get("/health")
async def health(redis: RedisDep):
    await redis.ping()
    return {"status": "ok"}
