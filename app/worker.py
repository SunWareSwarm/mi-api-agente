"""Worker: ejecuta el grafo en segundo plano y deja el estado del job en Redis."""
import asyncio
import json

from langgraph.types import Command
from redis.asyncio import Redis

from app.config import JOB_TIMEOUT_SECONDS, RECURSION_LIMIT
from app.jobs import JobStatus, get_job, update_job
from app.llm import as_text
from app.observability import trace_config


async def _drive(redis: Redis, graph, job_id: str, graph_input, config: dict) -> None:
    """Avanza el grafo hasta que termine o se pause, y refleja cada avance en Redis.

    Sirve tanto para la primera ejecución (graph_input = estado inicial) como para reanudar tras
    una aprobación (graph_input = Command(resume=...)).
    """
    interrupt_value = None
    async with asyncio.timeout(JOB_TIMEOUT_SECONDS):  # si se pasa, lanza TimeoutError
        # stream_mode="updates": emite lo que devuelve cada nodo, apenas termina.
        async for update in graph.astream(graph_input, config=config, stream_mode="updates"):
            for node_name, node_output in update.items():
                if node_name == "__interrupt__":  # el grafo se pausó en un interrupt()
                    interrupt_value = node_output[0].value
                    continue
                if not isinstance(node_output, dict):
                    continue
                await update_job(redis, job_id, current_node=node_name)

    snapshot = await graph.aget_state(config)  # estado final (o de la pausa) desde el checkpointer
    values = snapshot.values
    draft = as_text(values["messages"][-1].content) if values.get("task_completed") else None

    if interrupt_value is not None:
        # Pausa HITL: no es un error ni un fin. Se guarda qué hay que aprobar y se libera al worker.
        await update_job(
            redis, job_id, JobStatus.WAITING_APPROVAL,
            approval_request=json.dumps(interrupt_value, ensure_ascii=False),
        )
        return

    if draft is None:
        raise RuntimeError("El grafo terminó sin generar una respuesta final")

    extra = {}
    if values.get("send_report_to"):  # tarea crítica: informar cómo terminó la acción
        approval = values.get("approval") or {}
        if approval.get("approved") and values.get("delivery"):
            extra["delivery"] = f"enviado a {values['delivery']['destinatario']}"
        else:
            motivo = approval.get("comment") or "sin comentario"
            extra["delivery"] = f"rechazado: {motivo}"
    await update_job(redis, job_id, JobStatus.DONE, result=draft, **extra)


def _fail_detail(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc) or '(sin detalle)'}"


async def run_job(redis: Redis, graph, job_id: str) -> None:
    try:
        await update_job(redis, job_id, JobStatus.RUNNING)

        # Por la cola solo viaja el job_id; los datos se leen desde Redis.
        job = await get_job(redis, job_id)

        initial_state = {
            "messages": [("user", job["query"])],
            "step_count": 0,
            "task_completed": False,
            "contributions": [],
            "research_output": None,
            "analysis_output": None,
            "send_report_to": job.get("send_report_to"),  # si viene, la tarea es crítica (HITL)
            "approval": None,
            "delivery": None,
        }
        # thread_id = job_id: cada job es una "conversación" independiente del grafo,
        # y el checkpointer guarda su estado bajo ese identificador.
        config = {
            "configurable": {"thread_id": job_id},
            "recursion_limit": RECURSION_LIMIT,
            **trace_config(job_id),  # run_name, tags y metadata para encontrar la traza en LangSmith
        }
        await _drive(redis, graph, job_id, initial_state, config)
    except Exception as exc:
        # Sin esto, el cliente vería RUNNING para siempre.
        await update_job(redis, job_id, JobStatus.FAILED, error=_fail_detail(exc))


async def resume_job(redis: Redis, graph, job_id: str, approved: bool, comment: str = "") -> None:
    """Reanuda un job pausado con la decisión humana. Mismo thread_id = continúa donde quedó."""
    try:
        config = {
            "configurable": {"thread_id": job_id},
            "recursion_limit": RECURSION_LIMIT,
            **trace_config(job_id, resumed=True),
        }
        resume = Command(resume={"approved": approved, "comment": comment})
        await _drive(redis, graph, job_id, resume, config)
    except Exception as exc:
        await update_job(redis, job_id, JobStatus.FAILED, error=_fail_detail(exc))
