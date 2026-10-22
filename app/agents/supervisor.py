from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.llm import as_text, get_llm
from app.schemas import RouterDecision
from app.state import OrchestratorState, get_analysis, get_research

MAX_STEPS = 6  # tope duro contra el "supervisor infinito"

SUPERVISOR_PROMPT = """Eres el supervisor de un sistema multi-agente. Decides quién interviene \
ahora. Equipo disponible:

- researcher: busca datos en la web. No calcula.
- analyst: procesa datos con herramientas de cálculo. No busca información.
- synthesizer: redacta la respuesta final para el usuario.

Rúbrica de decisión (aplícala en orden):
1. Si no hay investigación, o está marcada como insuficiente → researcher.
2. Si hay investigación suficiente y no hay análisis → analyst.
3. Si el análisis indica data_quality_ok=False → researcher, con una instrucción \
más precisa sobre qué dato falta o es inconsistente.
4. Si hay investigación suficiente y análisis con data_quality_ok=True, y ambos \
responden la solicitud original → synthesizer.

En `instruction` escribe una orden específica y autocontenida para el agente elegido \
(no le pases la conversación completa). Para synthesizer puede ser breve."""


def _original_request(state: OrchestratorState) -> str:
    return as_text(state["messages"][0].content)


def _format_metrics(metrics) -> str:
    return ", ".join(f"{m.name}={m.value}" for m in metrics) or "(ninguna)"


def _status_report(state: OrchestratorState, step: int) -> str:
    research = get_research(state)
    analysis = get_analysis(state)

    research_txt = "AÚN NO HAY INVESTIGACIÓN."
    if research:
        research_txt = f"suficiente={research.sufficient}\n" + "\n".join(
            f"- {f}" for f in research.findings
        )

    analysis_txt = "AÚN NO HAY ANÁLISIS."
    if analysis:
        analysis_txt = (
            f"data_quality_ok={analysis.data_quality_ok}\n"
            f"métricas: {_format_metrics(analysis.metrics)}\n"
            + "\n".join(f"- {c}" for c in analysis.conclusions)
        )

    return (
        f"Solicitud original: {_original_request(state)}\n\n"
        f"Paso actual: {step} de {MAX_STEPS}\n\n"
        f"== INVESTIGACIÓN ==\n{research_txt}\n\n"
        f"== ANÁLISIS ==\n{analysis_txt}"
    )


async def supervisor_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    step = state.get("step_count", 0) + 1

    # Condición de parada 1: tope de pasos -> cerrar con lo que haya.
    if step > MAX_STEPS:
        return {
            "next_agent": "synthesizer",
            "instruction": "Responde con la información disponible e indica sus límites.",
            "step_count": step,
            "contributions": [
                {"agent": "supervisor", "step": step, "summary": "tope de pasos alcanzado"}
            ],
        }

    router = get_llm().with_structured_output(RouterDecision)
    decision: RouterDecision = await router.ainvoke(
        [
            SystemMessage(content=SUPERVISOR_PROMPT),
            HumanMessage(content=_status_report(state, step)),
        ],
        config,
    )

    # Condición de parada 2: guardas deterministas sobre la decisión del LLM.
    research = get_research(state)
    analysis = get_analysis(state)
    next_agent = decision.next

    if next_agent == "analyst" and research is None:
        next_agent = "researcher"
    if next_agent == "synthesizer" and (research is None or analysis is None):
        next_agent = "researcher" if research is None else "analyst"

    return {
        "next_agent": next_agent,
        "instruction": decision.instruction,
        "step_count": step,
        "contributions": [
            {
                "agent": "supervisor",
                "step": step,
                "summary": f"-> {next_agent}: {decision.reasoning}",
            }
        ],
    }


def route_from_supervisor(
    state: OrchestratorState,
) -> Literal["researcher", "analyst", "synthesizer"]:
    return state["next_agent"]


async def synthesizer_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    research = get_research(state)
    analysis = get_analysis(state)

    parts = [f"Solicitud original: {_original_request(state)}"]
    if research:
        parts.append("Hallazgos:\n" + "\n".join(f"- {f}" for f in research.findings))
        parts.append("Fuentes:\n" + "\n".join(f"- {s}" for s in research.sources))
    if analysis:
        parts.append(f"Métricas: {_format_metrics(analysis.metrics)}")
        parts.append("Conclusiones:\n" + "\n".join(f"- {c}" for c in analysis.conclusions))
        if not analysis.data_quality_ok:
            parts.append("ADVERTENCIA: el análisis marcó calidad de datos insuficiente.")

    system = (
        "Redacta la respuesta final al usuario en español, clara y concisa. "
        "Usa solo la información entregada, cita las fuentes y, si hay "
        "advertencias de calidad de datos, menciónalas."
    )
    answer = await get_llm().ainvoke(
        [SystemMessage(content=system), HumanMessage(content="\n\n".join(parts))], config
    )

    return {
        "messages": [AIMessage(content=as_text(answer.content))],
        "task_completed": True,
        "contributions": [
            {
                "agent": "synthesizer",
                "step": state.get("step_count", 0),
                "summary": "respuesta final",
            }
        ],
    }
