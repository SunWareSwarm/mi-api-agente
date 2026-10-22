from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.agents.analyst_agent import analyst_node
from app.agents.research_agent import research_node
from app.agents.supervisor import route_from_supervisor, supervisor_node, synthesizer_node
from app.hitl import approval_node, route_after_approval, route_after_synthesizer, send_report_node
from app.state import OrchestratorState


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    """Construye y compila el grafo. El checkpointer (Redis) llega desde afuera."""
    builder = StateGraph(OrchestratorState)

    # Nodos
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("researcher", research_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("synthesizer", synthesizer_node)
    builder.add_node("approval", approval_node)  # HITL: pausa hasta que un humano decida
    builder.add_node("send_report", send_report_node)  # acción crítica (efecto secundario)

    # Aristas
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "researcher": "researcher",
            "analyst": "analyst",
            "synthesizer": "synthesizer",
        },
    )
    builder.add_edge("researcher", "supervisor")  # los especialistas siempre vuelven
    builder.add_edge("analyst", "supervisor")
    # Tarea crítica (send_report_to) -> pide aprobación; si no, termina sin pausa.
    builder.add_conditional_edges(
        "synthesizer", route_after_synthesizer, {"approval": "approval", END: END}
    )
    builder.add_conditional_edges(
        "approval", route_after_approval, {"send_report": "send_report", END: END}
    )
    builder.add_edge("send_report", END)

    return builder.compile(checkpointer=checkpointer)
