import httpx


def make_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_post_devuelve_202_y_job_id(client_app):
    async with make_client(client_app) as c:
        r = await c.post("/tasks", json={"query": "hola mundo"})
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "PENDING" and body["job_id"]

        # (en tests el worker ya terminó: ASGITransport espera las tareas de fondo)
        r2 = await c.get(f"/tasks/{body['job_id']}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "DONE"
        assert "respuesta simulada" in r2.json()["result"]


async def test_job_inexistente_da_404(client_app):
    async with make_client(client_app) as c:
        assert (await c.get("/tasks/no-existe")).status_code == 404


async def test_body_invalido_da_422(client_app):
    async with make_client(client_app) as c:
        assert (await c.post("/tasks", json={"query": "x"})).status_code == 422
        assert (await c.post("/tasks", json={})).status_code == 422
