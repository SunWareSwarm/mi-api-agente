"""Herramienta con EFECTO SECUNDARIO (simulada): enviar el informe a un destinatario.

Es la acción "crítica" del sistema: una vez enviada no se puede deshacer, por eso el grafo exige
aprobación humana (app/hitl.py) antes de llamarla. Aquí solo se registra en el log; en un
producto real iría un correo, un webhook, un mensaje de Slack, etc.
"""
import logging
from datetime import datetime, timezone

log = logging.getLogger("uvicorn.error")


def enviar_informe(destinatario: str, contenido: str) -> dict:
    log.info("ENVIANDO INFORME (simulado) a %s (%d caracteres)", destinatario, len(contenido))
    return {
        "status": "enviado",
        "destinatario": destinatario,
        "enviado_en": datetime.now(timezone.utc).isoformat(),
    }
