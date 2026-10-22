"""Prueba de carga: N peticiones CONCURRENTES contra la API, esperando a que todas terminen.

Uso (con la API y Redis levantados):
    python -m scripts.load_test                       # 5 peticiones contra http://localhost:8000
    python -m scripts.load_test --url http://localhost:8000 --n 5

Las consultas son NO críticas (sin send_report_to): no disparan la pausa de aprobación, que
dejaría el job esperando y distorsionaría la medición de costo y latencia.

Al terminar imprime cuánto tardó cada job y la hora de inicio/fin: úsala para filtrar la ventana
de tiempo en el dashboard de LangSmith y para `python -m scripts.latency_report`.
"""
import argparse
import asyncio
import time
from datetime import datetime

import httpx

QUERIES = [
    "¿Cuál es la población de Chile y de Argentina, y cuál es la diferencia porcentual?",
    "¿Cuál es la población de Perú y de Colombia, y cuál es la diferencia porcentual?",
    "¿Cuál es la población de Uruguay y de Paraguay, y cuál es la diferencia porcentual?",
    "¿Cuál es el PIB per cápita de Brasil y de México, y cuál es la diferencia porcentual?",
    "¿Cuál es la superficie de Bolivia y de Ecuador, y cuál es la diferencia porcentual?",
]
TERMINAL = {"DONE", "FAILED"}


async def run_one(client: httpx.AsyncClient, query: str, poll: float, timeout: float) -> dict:
    """Envía UNA tarea y consulta su estado hasta que termine (patrón ticket y consulta)."""
    t0 = time.perf_counter()
    r = await client.post("/tasks", json={"query": query})
    r.raise_for_status()
    accepted_in = time.perf_counter() - t0  # lo que tardó la API en devolver el job_id
    job_id = r.json()["job_id"]

    while True:
        job = (await client.get(f"/tasks/{job_id}")).json()
        if job["status"] in TERMINAL:
            return {
                "job_id": job_id, "status": job["status"], "query": query,
                "accepted_s": accepted_in, "total_s": time.perf_counter() - t0,
                "error": job.get("error"),
            }
        if time.perf_counter() - t0 > timeout:
            return {"job_id": job_id, "status": "TIMEOUT_CLIENTE", "query": query,
                    "accepted_s": accepted_in, "total_s": time.perf_counter() - t0, "error": None}
        await asyncio.sleep(poll)


async def run_load_test(client: httpx.AsyncClient, queries: list[str], poll: float = 2.0, timeout: float = 600.0):
    # gather lanza todas a la vez: eso es lo que las hace "concurrentes".
    return await asyncio.gather(*(run_one(client, q, poll, timeout) for q in queries))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--n", type=int, default=5, help="cantidad de peticiones concurrentes")
    args = parser.parse_args()
    queries = [QUERIES[i % len(QUERIES)] for i in range(args.n)]

    async with httpx.AsyncClient(base_url=args.url, timeout=30) as client:
        start = datetime.now().astimezone()
        t0 = time.perf_counter()
        print(f"Lanzando {args.n} peticiones concurrentes a {args.url} ({start:%H:%M:%S})...")
        results = await run_load_test(client, queries)
        wall = time.perf_counter() - t0
        end = datetime.now().astimezone()

    print(f"\n{'job_id':<10}{'estado':<16}{'ticket (s)':>11}{'total (s)':>11}  consulta")
    for r in results:
        print(f"{r['job_id'][:8]:<10}{r['status']:<16}{r['accepted_s']:>11.3f}{r['total_s']:>11.1f}  {r['query'][:50]}")
        if r["error"]:
            print(f"{'':<10}ERROR: {r['error']}")

    totals = sorted(r["total_s"] for r in results)
    ok = sum(r["status"] == "DONE" for r in results)
    print(f"\nTerminaron en DONE: {ok}/{len(results)} | tiempo total de la corrida: {wall:.1f} s")
    print(f"Más lento: {totals[-1]:.1f} s | más rápido: {totals[0]:.1f} s")
    print(f"Ventana de la corrida: {start:%H:%M:%S} -> {end:%H:%M:%S} (hora local; filtra el dashboard con ella)")
    if ok < len(results):
        print("AVISO: hubo jobs que no terminaron en DONE; revisa el error antes de capturar el dashboard.")


if __name__ == "__main__":
    asyncio.run(main())
