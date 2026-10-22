from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest
from langchain_core.tracers.run_collector import RunCollectorCallbackHandler

from app.observability import RUN_NAME, init_observability, trace_config
from scripts.latency_report import percentile, summarize


def test_trace_config_identifica_la_ejecucion():
    cfg = trace_config("abc123")
    assert cfg["run_name"] == RUN_NAME
    assert cfg["metadata"] == {"job_id": "abc123"}
    assert "api" in cfg["tags"]


async def test_la_traza_raiz_lleva_nombre_etiquetas_y_metadatos(graph):
    """Comprueba (con un recolector local, sin LangSmith) que el config produce la traza esperada."""
    collector = RunCollectorCallbackHandler()
    config = {
        "configurable": {"thread_id": "job-9"},
        "recursion_limit": 30,
        "callbacks": [collector],
        **trace_config("job-9"),
    }
    initial = {
        "messages": [("user", "consulta")], "step_count": 0, "task_completed": False,
        "contributions": [], "research_output": None, "analysis_output": None,
    }
    await graph.ainvoke(initial, config)

    root = collector.traced_runs[0]  # solo se recolectan trazas raíz
    assert root.name == RUN_NAME
    assert root.metadata["job_id"] == "job-9"
    assert root.metadata["thread_id"] == "job-9"  # LangChain copia el thread_id a los metadatos
    assert "pre-entrega-7" in root.tags


def test_init_observability_activo(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-clave")
    monkeypatch.setenv("LANGSMITH_PROJECT", "mi-proyecto")
    assert init_observability() == {"enabled": True, "project": "mi-proyecto"}


def test_init_observability_sin_api_key_no_queda_activo(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert init_observability()["enabled"] is False


def test_init_observability_desactivado_usa_proyecto_por_defecto(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    assert init_observability() == {"enabled": False, "project": "mi-api-agente"}


def test_percentil_rango_mas_cercano():
    assert percentile([1, 2, 3, 4, 5], 0.95) == 5  # con 5 datos, p95 = el máximo
    assert percentile([5, 1, 4, 2, 3], 0.50) == 3
    assert percentile(list(range(10, 101, 10)), 0.95) == 100
    assert percentile(list(range(10, 101, 10)), 0.50) == 50
    with pytest.raises(ValueError):
        percentile([], 0.95)


def _run(seconds, cost, tokens=1000):
    t0 = datetime(2026, 10, 21, tzinfo=timezone.utc)
    return SimpleNamespace(
        id="abcdef123456", status="success", start_time=t0,
        end_time=t0 + timedelta(seconds=seconds), total_cost=cost, total_tokens=tokens,
    )


def test_summarize_calcula_latencia_y_costo():
    runs = [_run(10, 0.002), _run(12, 0.004), _run(11, 0.003), _run(30, 0.005), _run(13, 0.001)]
    out = summarize(runs)
    assert out["n"] == 5
    assert out["p50_s"] == 12 and out["p95_s"] == 30
    assert out["avg_cost"] == pytest.approx(0.003)
    assert out["runs_without_cost"] == 0


def test_summarize_avisa_cuando_falta_el_costo_y_omite_trazas_en_curso():
    en_curso = _run(5, None)
    en_curso.end_time = None
    out = summarize([_run(10, None), _run(12, 0.004), en_curso])
    assert out["n"] == 2
    assert out["runs_without_cost"] == 1
