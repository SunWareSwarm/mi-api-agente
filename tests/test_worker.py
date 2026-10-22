from app import worker
from app.jobs import JobStatus, create_job, get_job
from app.schemas import ResearchOutput
from app.worker import run_job

import app.agents.research_agent as research_mod
from tests.fakes import FakeAgent


async def test_job_termina_en_done_con_el_resultado_del_grafo(redis, graph):
    job_id = await create_job(redis, "¿Población de Chile y Argentina?")
    await run_job(redis, graph, job_id)
    job = await get_job(redis, job_id)
    assert job["status"] == JobStatus.DONE
    assert "respuesta simulada" in job["result"]
    assert job["current_node"] == "synthesizer"


async def test_el_job_id_es_el_thread_id_del_checkpoint(redis, graph):
    job_id = await create_job(redis, "consulta")
    await run_job(redis, graph, job_id)
    snapshot = await graph.aget_state({"configurable": {"thread_id": job_id}})
    assert snapshot.values["task_completed"] is True


async def test_error_en_un_agente_deja_el_job_en_failed(redis, graph, monkeypatch):
    monkeypatch.setattr(
        research_mod, "get_research_agent", lambda: FakeAgent(error=RuntimeError("Gemini 429: cuota agotada"))
    )
    job_id = await create_job(redis, "consulta")
    await run_job(redis, graph, job_id)  # no debe propagar la excepción
    job = await get_job(redis, job_id)
    assert job["status"] == JobStatus.FAILED
    assert "Gemini 429" in job["error"]


async def test_timeout_deja_el_job_en_failed(redis, graph, monkeypatch):
    monkeypatch.setattr(worker, "JOB_TIMEOUT_SECONDS", 0.05)
    slow = FakeAgent(output=ResearchOutput(findings=[], sources=[], sufficient=True), delay=1)
    monkeypatch.setattr(research_mod, "get_research_agent", lambda: slow)
    job_id = await create_job(redis, "consulta lenta")
    await run_job(redis, graph, job_id)
    job = await get_job(redis, job_id)
    assert job["status"] == JobStatus.FAILED
    assert "TimeoutError" in job["error"]
