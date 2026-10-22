import os

# Los tests NUNCA deben enviar trazas a LangSmith (ensuciarían tu proyecto), aunque tu .env las active.
# Debe ir antes de importar la app, porque LangSmith lee esta variable al primer uso.
os.environ["LANGSMITH_TRACING"] = "false"

import fakeredis
import pytest
from langgraph.checkpoint.memory import InMemorySaver

import app.agents.analyst_agent as analyst_mod
import app.agents.research_agent as research_mod
import app.agents.supervisor as supervisor_mod
from app.graph import build_graph
from app.main import app, get_graph, get_redis
from app.schemas import AnalysisOutput, Metric, ResearchOutput, RouterDecision
from tests.fakes import FakeAgent, FakeLLM


@pytest.fixture
async def redis():
    client = fakeredis.FakeAsyncRedis(decode_responses=True)  # Redis simulado en memoria
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    """Reemplaza Gemini y los agentes por dobles: ningún test llama a servicios externos."""
    decisions = [
        RouterDecision(next="researcher", instruction="busca poblaciones", reasoning="falta investigar"),
        RouterDecision(next="analyst", instruction="calcula la diferencia", reasoning="ya hay datos"),
        RouterDecision(next="synthesizer", instruction="redacta", reasoning="todo listo"),
    ]
    llm = FakeLLM(decisions)  # una sola instancia: el iterador de decisiones debe avanzar
    monkeypatch.setattr(supervisor_mod, "get_llm", lambda: llm)

    research = ResearchOutput(
        findings=["Población de Chile: 19.7 millones", "Población de Argentina: 46.6 millones"],
        sources=["https://ejemplo.com"],
        sufficient=True,
    )
    analysis = AnalysisOutput(
        metrics=[Metric(name="diferencia_porcentual", value=136.55)],
        conclusions=["Argentina tiene más del doble de población."],
        data_quality_ok=True,
    )
    monkeypatch.setattr(research_mod, "get_research_agent", lambda: FakeAgent(output=research))
    monkeypatch.setattr(analyst_mod, "get_analyst_agent", lambda: FakeAgent(output=analysis))


@pytest.fixture
def graph():
    return build_graph(InMemorySaver())  # checkpointer en memoria (en producción: Redis)


@pytest.fixture
def client_app(redis, graph):
    app.dependency_overrides[get_redis] = lambda: redis  # la API usa el Redis simulado
    app.dependency_overrides[get_graph] = lambda: graph
    yield app
    app.dependency_overrides.clear()
