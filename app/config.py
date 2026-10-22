"""Configuración central: todo lo que cambia entre tu PC y producción vive en variables de entorno."""
import os

from dotenv import load_dotenv

load_dotenv()  # lee el archivo .env (si existe) y lo vuelca a las variables de entorno

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Los jobs expiran solos de Redis a las 24 h, para que la base no crezca sin límite.
JOB_TTL_SECONDS = 60 * 60 * 24

# Tiempo máximo que puede tardar una ejecución del grafo antes de marcarla como FAILED.
JOB_TIMEOUT_SECONDS = float(os.getenv("JOB_TIMEOUT_SECONDS", "300"))

# Tope de pasos que LangGraph permite en una ejecución (seguro anti-bucle).
RECURSION_LIMIT = 30
