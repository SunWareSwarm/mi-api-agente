"""Contratos de la API: qué JSON acepta y qué JSON devuelve (validados con Pydantic)."""
from pydantic import BaseModel, Field

from app.jobs import JobStatus


class TaskCreate(BaseModel):
    """Cuerpo del POST /tasks."""

    query: str = Field(min_length=3, max_length=2000, description="Consulta para el orquestador")
    # Si viene, la tarea es "crítica" (envía el informe) y quedará en WAITING_APPROVAL hasta que
    # un humano la apruebe con POST /tasks/{id}/approve.
    send_report_to: str | None = Field(default=None, description="Destinatario del informe")


class TaskAccepted(BaseModel):
    """Respuesta inmediata del POST /tasks: el 'ticket'."""

    job_id: str
    status: JobStatus


class TaskStatus(BaseModel):
    """Respuesta del GET /tasks/{job_id}."""

    job_id: str
    status: JobStatus
    query: str
    current_node: str | None = None  # último nodo del grafo que terminó (progreso)
    result: str | None = None
    error: str | None = None
    send_report_to: str | None = None
    approval_request: dict | None = None  # qué se pide aprobar (solo en WAITING_APPROVAL)
    delivery: str | None = None  # resultado del envío: "enviado a ..." o "rechazado: ..."
    created_at: str
    updated_at: str
