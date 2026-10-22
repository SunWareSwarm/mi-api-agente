"""Estado de los trabajos (jobs) en Redis.

Cada job es un "hash" de Redis (un mini-diccionario) guardado bajo la clave `job:<job_id>`.
Este módulo es la ÚNICA parte del código que sabe cómo se guarda un job: la API y el
worker solo llaman a estas funciones.
"""
import uuid
from datetime import datetime, timezone
from enum import StrEnum

from redis.asyncio import Redis

from app.config import JOB_TTL_SECONDS


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"  # el grafo está pausado esperando a un humano (HITL)
    DONE = "DONE"
    FAILED = "FAILED"


def _key(job_id: str) -> str:
    return f"job:{job_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_job(redis: Redis, query: str, send_report_to: str | None = None) -> str:
    job_id = uuid.uuid4().hex
    now = _now()
    fields = {
        "query": query,
        "status": JobStatus.PENDING.value,
        "created_at": now,
        "updated_at": now,
    }
    if send_report_to:  # Redis no acepta None como valor: si no hay dato, no se guarda el campo
        fields["send_report_to"] = send_report_to

    # Pipeline: manda los dos comandos juntos y de forma atómica (todo o nada).
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(_key(job_id), mapping=fields)
        pipe.expire(_key(job_id), JOB_TTL_SECONDS)
        await pipe.execute()
    return job_id


async def update_job(redis: Redis, job_id: str, status: JobStatus | None = None, **fields: str) -> None:
    if status is not None:
        fields["status"] = status.value
    fields["updated_at"] = _now()
    await redis.hset(_key(job_id), mapping=fields)


async def get_job(redis: Redis, job_id: str) -> dict[str, str] | None:
    data = await redis.hgetall(_key(job_id))
    return data or None  # hgetall devuelve {} si la clave no existe


async def claim_approval(redis: Redis, job_id: str) -> bool:
    """Candado atómico para que UNA sola decisión reanude el job (SET NX: solo gana el primero)."""
    return bool(await redis.set(f"approval-lock:{job_id}", "1", nx=True, ex=JOB_TTL_SECONDS))
