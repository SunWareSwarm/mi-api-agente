from langchain_core.tools import tool


@tool
def calcular_diferencia_porcentual(valor_a: float, valor_b: float) -> dict:
    """Calcula la diferencia porcentual de valor_a respecto a valor_b.
    Usar cuando se necesite comparar dos cifras."""
    if valor_b == 0:
        return {"error": "valor_b no puede ser cero"}
    return {
        "diferencia_absoluta": valor_a - valor_b,
        "diferencia_porcentual": round((valor_a - valor_b) / valor_b * 100, 2),
    }


@tool
def calcular_estadisticas(valores: list[float]) -> dict:
    """Calcula promedio, mínimo y máximo de una lista de números.
    Usar cuando haya tres o más cifras que resumir."""
    if not valores:
        return {"error": "lista vacía"}
    return {
        "promedio": round(sum(valores) / len(valores), 2),
        "minimo": min(valores),
        "maximo": max(valores),
    }
