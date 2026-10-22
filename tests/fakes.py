"""Dobles de prueba: reemplazan a Gemini y a los agentes para probar el grafo sin red ni costo."""
import asyncio

from langchain_core.messages import AIMessage


class _Router:
    """Imita a `llm.with_structured_output(RouterDecision)`: devuelve decisiones en orden."""

    def __init__(self, decisions):
        self._decisions = iter(decisions)

    async def ainvoke(self, messages, config=None):
        return next(self._decisions)


class FakeLLM:
    def __init__(self, decisions, answer="Chile: 19,7 M; Argentina: 46,6 M (respuesta simulada)."):
        self._router = _Router(decisions)
        self._answer = answer

    def with_structured_output(self, schema):
        return self._router

    async def ainvoke(self, messages, config=None):
        return AIMessage(content=self._answer)


class FakeAgent:
    """Imita a un agente ReAct: devuelve una salida fija, falla, o tarda (para probar timeouts)."""

    def __init__(self, output=None, error=None, delay=0.0):
        self._output, self._error, self._delay = output, error, delay

    async def ainvoke(self, payload, config=None):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return {"structured_response": self._output}
