import httpx

import app.agents.supervisor as supervisor_mod
from app.schemas import RouterDecision
from scripts.load_test import QUERIES, run_load_test
from tests.fakes import FakeLLM


class _StatelessRouter:
    """Decide mirando el informe que recibe (no un iterador compartido): sirve con jobs concurrentes."""

    async def ainvoke(self, messages, config=None):
        report = messages[-1].content
        if "AÚN NO HAY INVESTIGACIÓN" in report:
            return RouterDecision(next="researcher", instruction="busca", reasoning="falta investigar")
        if "AÚN NO HAY ANÁLISIS" in report:
            return RouterDecision(next="analyst", instruction="calcula", reasoning="ya hay datos")
        return RouterDecision(next="synthesizer", instruction="redacta", reasoning="todo listo")


async def test_el_script_de_carga_completa_las_peticiones_concurrentes(client_app, monkeypatch):
    llm = FakeLLM([])
    llm.with_structured_output = lambda schema: _StatelessRouter()
    monkeypatch.setattr(supervisor_mod, "get_llm", lambda: llm)

    transport = httpx.ASGITransport(app=client_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        results = await run_load_test(c, QUERIES, poll=0.01, timeout=10)

    assert len(results) == 5
    assert all(r["status"] == "DONE" for r in results), [r["error"] for r in results]
    assert len({r["job_id"] for r in results}) == 5  # cada petición tuvo su propio job
