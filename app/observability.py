"""Observabilidad con LangSmith.

LangGraph y LangChain ya traen el instrumento de trazas incorporado: si las variables de entorno
LANGSMITH_* están definidas, CADA llamada a un LLM, tool o nodo se registra sola (sin decoradores).
Este módulo agrega lo que falta para que las trazas sean útiles:
  - verificar al arrancar que la configuración es coherente (y avisar si no lo es),
  - ponerle nombre, etiquetas y metadatos a cada ejecución para encontrarla después,
  - asegurar que las trazas pendientes se envíen al apagar el servidor.
"""
import logging
import os

DEFAULT_PROJECT = "mi-api-agente"
RUN_NAME = "orquestador"  # nombre que verás en la tabla de trazas de LangSmith
RESUME_RUN_NAME = "orquestador-reanudacion"  # trazas de las reanudaciones tras una aprobación

log = logging.getLogger("uvicorn.error")  # el logger de uvicorn sí muestra mensajes INFO


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes"}


def init_observability() -> dict:
    """Revisa la configuración de LangSmith y la informa en el log de arranque."""
    # Si no definiste proyecto, usamos uno propio en vez del genérico "default".
    os.environ.setdefault("LANGSMITH_PROJECT", DEFAULT_PROJECT)

    enabled = _truthy(os.getenv("LANGSMITH_TRACING"))
    has_key = bool(os.getenv("LANGSMITH_API_KEY"))
    project = os.environ["LANGSMITH_PROJECT"]

    if enabled and has_key:
        log.info("LangSmith: trazas ACTIVAS -> proyecto '%s'", project)
    elif enabled:
        log.warning("LANGSMITH_TRACING=true pero falta LANGSMITH_API_KEY: NO se enviarán trazas")
    else:
        log.info("LangSmith: trazas DESACTIVADAS (define LANGSMITH_TRACING=true para activarlas)")

    return {"enabled": enabled and has_key, "project": project}


def trace_config(job_id: str, resumed: bool = False) -> dict:
    """Campos de `config` que identifican una ejecución en LangSmith.

    - run_name: el título de la traza raíz.
    - tags: etiquetas para filtrar.
    - metadata: datos libres; aquí el job_id, para saltar de un job de la API a su traza.
    (El thread_id ya se registra solo, porque va en config["configurable"].)

    Una reanudación tras aprobar es una traza raíz APARTE (con otro nombre), para que no se mezcle
    con las ejecuciones normales al calcular costo y latencia p95.
    """
    return {
        "run_name": RESUME_RUN_NAME if resumed else RUN_NAME,
        "tags": ["api", "pre-entrega-7"] + (["resume"] if resumed else []),
        "metadata": {"job_id": job_id},
    }


def flush_traces() -> None:
    """Espera a que las trazas pendientes se envíen. LangSmith las manda desde un hilo en segundo
    plano: si apagas el servidor justo después de una ejecución, podrías perder las últimas."""
    try:
        from langchain_core.tracers.langchain import wait_for_all_tracers

        wait_for_all_tracers()
    except Exception:  # apagar nunca debe fallar por culpa de la observabilidad
        log.warning("No se pudieron enviar todas las trazas pendientes", exc_info=True)
