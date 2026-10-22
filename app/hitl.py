"""Human-in-the-loop (HITL): pausa obligatoria para aprobación humana antes de una acción crítica.

Flujo:
  1. `synthesizer` termina el informe. Si el job pidió enviarlo (`send_report_to`), el grafo pasa
     al nodo `approval`.
  2. `approval` llama a `interrupt(...)`: LangGraph guarda el estado en el checkpointer (Redis)
     y DETIENE la ejecución. El worker marca el job como WAITING_APPROVAL.
  3. El cliente llama a `POST /tasks/{id}/approve`. La API reanuda el grafo con
     `Command(resume=...)` y el MISMO thread_id (= job_id).
  4. Si se aprobó, corre `send_report` (el único nodo con efecto secundario); si no, el grafo termina.

REGLA DE ORO: al reanudar, el nodo con el `interrupt` se vuelve a ejecutar DESDE SU PRIMERA LÍNEA.
Por eso `approval` no hace nada con efectos antes del interrupt, y el envío vive en OTRO nodo.
"""
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from langgraph.types import interrupt
from pydantic import BaseModel, Field
from app import jobs
from app.api_models import TaskAccepted
from app.deps import GraphDep, RedisDep
from app.jobs import JobStatus
from app.llm import as_text
from app.state import OrchestratorState
from app.tools.report_tools import enviar_informe
from app.worker import resume_job

# --------------------------------------------------------------------------- nodos del grafo


async def approval_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    """Pausa el grafo hasta recibir una decisión humana. Sin efectos secundarios aquí."""
    draft = as_text(state["messages"][-1].content)
    decision = interrupt(
        {
            "action": "enviar_informe",
            "destinatario": state["send_report_to"],
            "draft": draft,
            "question": "¿Apruebas enviar este informe? (POST /tasks/{id}/approve)",
        }
    )
    # --- desde aquí, `decision` es lo que mandó el humano al reanudar ---
    approved = bool(decision.get("approved", False))
    return {
        "approval": {"approved": approved, "comment": decision.get("comment", "")},
        "contributions": [
            {
                "agent": "human",
                "step": state.get("step_count", 0),
                "summary": "aprobó el envío" if approved else "rechazó el envío",
            }
        ],
    }


async def send_report_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    """La acción crítica. Solo se alcanza si un humano aprobó."""
    report = as_text(state["messages"][-1].content)
    delivery = enviar_informe(state["send_report_to"], report)
    return {
        "delivery": delivery,
        "contributions": [
            {"agent": "sender", "step": state.get("step_count", 0), "summary": f"informe enviado a {state['send_report_to']}"}
        ],
    }


# --------------------------------------------------------------------------- rutas del grafo


def route_after_synthesizer(state: OrchestratorState) -> Literal["approval", "__end__"]:
    """Tarea crítica = pidió enviar el informe a alguien. Las demás terminan sin pausa."""
    return "approval" if state.get("send_report_to") else END


def route_after_approval(state: OrchestratorState) -> Literal["send_report", "__end__"]:
    return "send_report" if (state.get("approval") or {}).get("approved") else END


# --------------------------------------------------------------------------- endpoint /approve

router = APIRouter()


class ApprovalDecision(BaseModel):
    approved: bool = Field(description="True para aprobar el envío, False para rechazarlo")
    comment: str = Field(default="", max_length=500, description="Comentario opcional del revisor")


@router.post("/tasks/{job_id}/approve", status_code=202, response_model=TaskAccepted)
async def approve_task(
    job_id: str,
    decision: ApprovalDecision,
    background: BackgroundTasks,
    redis: RedisDep,
    graph: GraphDep,
):
    job = await jobs.get_job(redis, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado (o expirado)")
    if job["status"] != JobStatus.WAITING_APPROVAL:
        raise HTTPException(status_code=409, detail=f"El job está en {job['status']}, no espera aprobación")

    # Candado atómico: si dos clientes aprueban a la vez, solo uno reanuda el grafo.
    if not await jobs.claim_approval(redis, job_id):
        raise HTTPException(status_code=409, detail="Este job ya recibió una decisión")

    await jobs.update_job(redis, job_id, JobStatus.RUNNING)  # el polling ya ve que avanzó
    background.add_task(resume_job, redis, graph, job_id, decision.approved, decision.comment)
    return TaskAccepted(job_id=job_id, status=JobStatus.RUNNING)
