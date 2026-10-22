import httpx

from app import hitl
from app.jobs import JobStatus, create_job, get_job
from app.worker import resume_job, run_job
from tests.test_api import make_client

DEST = "jefa@ejemplo.com"


async def _enviados(monkeypatch):
    """Reemplaza el efecto secundario por un espía: así sabemos si se llamó (y cuántas veces)."""
    llamadas = []

    def espia(destinatario, contenido):
        llamadas.append(destinatario)
        return {"status": "enviado", "destinatario": destinatario, "enviado_en": "ahora"}

    monkeypatch.setattr(hitl, "enviar_informe", espia)
    return llamadas


async def test_tarea_critica_se_pausa_y_NO_envia_nada(redis, graph, monkeypatch):
    enviados = await _enviados(monkeypatch)
    job_id = await create_job(redis, "consulta", send_report_to=DEST)
    await run_job(redis, graph, job_id)

    job = await get_job(redis, job_id)
    assert job["status"] == JobStatus.WAITING_APPROVAL
    assert DEST in job["approval_request"]
    assert "respuesta simulada" in job["approval_request"]  # el humano ve el borrador
    assert enviados == []  # la pausa ocurre ANTES del efecto secundario


async def test_aprobar_envia_una_vez_y_termina_en_done(redis, graph, monkeypatch):
    enviados = await _enviados(monkeypatch)
    job_id = await create_job(redis, "consulta", send_report_to=DEST)
    await run_job(redis, graph, job_id)
    await resume_job(redis, graph, job_id, approved=True, comment="ok")

    job = await get_job(redis, job_id)
    assert job["status"] == JobStatus.DONE
    assert job["delivery"] == f"enviado a {DEST}"
    assert "respuesta simulada" in job["result"]
    assert enviados == [DEST]  # exactamente una vez (el nodo con interrupt se reejecuta, el envío no)


async def test_rechazar_termina_en_done_sin_enviar(redis, graph, monkeypatch):
    enviados = await _enviados(monkeypatch)
    job_id = await create_job(redis, "consulta", send_report_to=DEST)
    await run_job(redis, graph, job_id)
    await resume_job(redis, graph, job_id, approved=False, comment="falta una fuente")

    job = await get_job(redis, job_id)
    assert job["status"] == JobStatus.DONE
    assert job["delivery"] == "rechazado: falta una fuente"
    assert enviados == []


async def test_tarea_no_critica_no_se_pausa(redis, graph, monkeypatch):
    enviados = await _enviados(monkeypatch)
    job_id = await create_job(redis, "consulta normal")
    await run_job(redis, graph, job_id)

    job = await get_job(redis, job_id)
    assert job["status"] == JobStatus.DONE
    assert "delivery" not in job and enviados == []


async def test_error_al_reanudar_deja_el_job_en_failed(redis, graph, monkeypatch):
    def explota(destinatario, contenido):
        raise ConnectionError("SMTP caído")

    monkeypatch.setattr(hitl, "enviar_informe", explota)
    job_id = await create_job(redis, "consulta", send_report_to=DEST)
    await run_job(redis, graph, job_id)
    await resume_job(redis, graph, job_id, approved=True)

    job = await get_job(redis, job_id)
    assert job["status"] == JobStatus.FAILED
    assert "SMTP caído" in job["error"]


# ------------------------------------------------------------------ por la API (flujo completo)


async def test_api_flujo_completo_espera_aprobacion_y_reanuda(client_app, monkeypatch):
    enviados = await _enviados(monkeypatch)
    async with make_client(client_app) as c:
        r = await c.post("/tasks", json={"query": "informe de poblaciones", "send_report_to": DEST})
        job_id = r.json()["job_id"]

        estado = (await c.get(f"/tasks/{job_id}")).json()
        assert estado["status"] == "WAITING_APPROVAL"
        assert estado["approval_request"]["destinatario"] == DEST
        assert enviados == []

        r = await c.post(f"/tasks/{job_id}/approve", json={"approved": True, "comment": "ok"})
        assert r.status_code == 202 and r.json()["status"] == "RUNNING"

        estado = (await c.get(f"/tasks/{job_id}")).json()
        assert estado["status"] == "DONE"
        assert estado["delivery"] == f"enviado a {DEST}"
        assert estado["approval_request"] is None
        assert enviados == [DEST]


async def test_api_approve_de_job_inexistente_da_404(client_app):
    async with make_client(client_app) as c:
        r = await c.post("/tasks/no-existe/approve", json={"approved": True})
        assert r.status_code == 404


async def test_api_approve_de_job_que_no_espera_da_409(client_app):
    async with make_client(client_app) as c:
        job_id = (await c.post("/tasks", json={"query": "consulta normal"})).json()["job_id"]
        r = await c.post(f"/tasks/{job_id}/approve", json={"approved": True})
        assert r.status_code == 409


async def test_api_segunda_aprobacion_da_409_y_no_reenvia(client_app, monkeypatch):
    enviados = await _enviados(monkeypatch)
    async with make_client(client_app) as c:
        job_id = (await c.post("/tasks", json={"query": "informe", "send_report_to": DEST})).json()["job_id"]
        assert (await c.post(f"/tasks/{job_id}/approve", json={"approved": True})).status_code == 202
        assert (await c.post(f"/tasks/{job_id}/approve", json={"approved": True})).status_code == 409
    assert enviados == [DEST]


async def test_api_approve_con_body_invalido_da_422(client_app):
    async with make_client(client_app) as c:
        assert (await c.post("/tasks/x/approve", json={})).status_code == 422
