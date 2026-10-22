"""Contratos de datos (Pydantic) entre los nodos del grafo."""
from typing import Literal

from pydantic import BaseModel, Field


class RouterDecision(BaseModel):
    """Salida del supervisor: decide el próximo nodo."""

    next: Literal["researcher", "analyst", "synthesizer"]
    instruction: str = Field(
        description="Instrucción específica y autocontenida para el agente elegido"
    )
    reasoning: str = Field(description="Por qué se eligió este paso")


class ResearchOutput(BaseModel):
    """Salida del agente investigador."""

    findings: list[str] = Field(description="Hallazgos concretos y verificables")
    sources: list[str] = Field(description="URLs de las fuentes usadas")
    sufficient: bool = Field(
        description="True si hay datos suficientes para realizar el análisis"
    )


class Metric(BaseModel):
    """Una métrica numérica calculada por el analista."""

    name: str = Field(description="Nombre descriptivo de la métrica")
    value: float


class AnalysisOutput(BaseModel):
    """Salida del agente analista."""

    metrics: list[Metric] = Field(description="Resultados numéricos calculados")
    conclusions: list[str]
    data_quality_ok: bool = Field(
        description="False si los datos son insuficientes o inconsistentes"
    )
