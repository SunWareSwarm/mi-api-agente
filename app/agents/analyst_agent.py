from functools import cache

from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent

from app.llm import get_llm
from app.schemas import AnalysisOutput
from app.state import OrchestratorState, get_research
from app.tools.math_tools import calcular_diferencia_porcentual, calcular_estadisticas

ANALYST_PROMPT = """Eres un agente analista. Recibes hallazgos ya investigados y debes \
procesarlos cuantitativamente.

Reglas:
- Todo cálculo debe hacerse con las herramientas. Nunca calcules de cabeza.
- Usa solo los datos que se te entregan. No inventes cifras ni busques información nueva.
- En `metrics` incluye cada resultado numérico con un nombre descriptivo.
- Si los datos son insuficientes, ambiguos o inconsistentes para calcular lo pedido, \
marca `data_quality_ok=False` y explica el problema en `conclusions`."""


@cache
def get_analyst_agent():
    return create_react_agent(
        model=get_llm(),
        tools=[calcular_diferencia_porcentual, calcular_estadisticas],
        prompt=ANALYST_PROMPT,
        response_format=AnalysisOutput,
        name="analyst",
        checkpointer=False,
    )


async def analyst_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    research = get_research(state)
    if research is None:
        # Salvaguarda: el supervisor no debería enviar aquí sin investigación previa.
        empty = AnalysisOutput(
            metrics=[],
            conclusions=["No hay datos de investigación para analizar."],
            data_quality_ok=False,
        )
        return {
            "analysis_output": empty.model_dump(),
            "contributions": [
                {"agent": "analyst", "step": state.get("step_count", 0), "summary": "sin datos de entrada"}
            ],
        }

    # Contexto acotado: solo la instrucción y los hallazgos, no el historial.
    findings = "\n".join(f"- {f}" for f in research.findings)
    task = f"Tarea: {state['instruction']}\n\nHallazgos disponibles:\n{findings}"

    result = await get_analyst_agent().ainvoke({"messages": [("user", task)]}, config)
    output: AnalysisOutput = result["structured_response"]

    return {
        "analysis_output": output.model_dump(),
        "contributions": [
            {
                "agent": "analyst",
                "step": state.get("step_count", 0),
                "summary": f"{len(output.metrics)} métricas, calidad_ok={output.data_quality_ok}",
            }
        ],
    }
