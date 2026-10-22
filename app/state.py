"""Estado compartido del grafo.

IMPORTANTE (cambio respecto al Módulo 6): las salidas de los especialistas se guardan como
`dict` (con .model_dump()) y NO como objetos Pydantic. El checkpointer de Redis guarda el
estado en JSON, y al leerlo de vuelta (por ejemplo, tras una pausa de aprobación humana) los
objetos Pydantic regresan como diccionarios simples. Guardando dicts, lo que se escribe es
exactamente lo que se lee. Pydantic se usa en los bordes: al producir y al consumir.
"""
import operator
from typing import Annotated

from langgraph.graph import MessagesState

from app.schemas import AnalysisOutput, ResearchOutput


class OrchestratorState(MessagesState):
    # Control de flujo (se sobrescriben en cada turno)
    next_agent: str
    instruction: str
    step_count: int
    task_completed: bool

    # Salidas de los especialistas, como dict (se sobrescriben al refinar)
    research_output: dict | None
    analysis_output: dict | None

    # Human-in-the-loop (Fase 4): acción crítica opcional, decisión humana y resultado del envío
    send_report_to: str | None
    approval: dict | None
    delivery: dict | None

    # Registro de quién aportó qué (se acumula con operator.add)
    contributions: Annotated[list[dict], operator.add]


def get_research(state: OrchestratorState) -> ResearchOutput | None:
    """dict del estado -> objeto Pydantic validado (o None si aún no hay investigación)."""
    data = state.get("research_output")
    return ResearchOutput.model_validate(data) if data else None


def get_analysis(state: OrchestratorState) -> AnalysisOutput | None:
    data = state.get("analysis_output")
    return AnalysisOutput.model_validate(data) if data else None
