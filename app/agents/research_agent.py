from functools import cache

from langchain_core.runnables import RunnableConfig
from langchain_tavily import TavilySearch
from langgraph.prebuilt import create_react_agent

from app.llm import get_llm
from app.schemas import ResearchOutput
from app.state import OrchestratorState

RESEARCH_PROMPT = """Eres un agente investigador. Tu única tarea es buscar información \
en la web sobre la instrucción que recibes y devolver hallazgos verificables.

Reglas:
- Usa la herramienta de búsqueda. No respondas desde tu conocimiento previo.
- Cada hallazgo debe ser un dato concreto (cifras, hechos), no una opinión.
- En `sources` incluye las URLs de donde obtuviste los datos.
- Marca `sufficient=True` solo si los hallazgos permiten un análisis cuantitativo; \
si no, `sufficient=False`.
- No analices ni calcules nada: eso lo hace otro agente."""


@cache  # se construye la primera vez que se pide y se reutiliza (no al importar el módulo)
def get_research_agent():
    return create_react_agent(
        model=get_llm(),
        tools=[TavilySearch(max_results=3)],
        prompt=RESEARCH_PROMPT,
        response_format=ResearchOutput,
        name="researcher",
        checkpointer=False,  # este sub-agente NO guarda checkpoints propios en Redis
    )


async def research_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    # Aislamiento de contexto: el agente solo recibe la instrucción del supervisor.
    # `config` se propaga para que las trazas (Fase 3) queden anidadas bajo este nodo.
    result = await get_research_agent().ainvoke(
        {"messages": [("user", state["instruction"])]}, config
    )
    output: ResearchOutput = result["structured_response"]

    return {
        "research_output": output.model_dump(),
        "contributions": [
            {
                "agent": "researcher",
                "step": state.get("step_count", 0),
                "summary": f"{len(output.findings)} hallazgos, {len(output.sources)} fuentes",
            }
        ],
    }
