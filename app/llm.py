from langchain_google_genai import ChatGoogleGenerativeAI

MODEL_NAME = "gemini-3.8-flash"


def get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)


def as_text(content) -> str:
    """Normaliza el contenido de un mensaje a str (puede venir como lista de bloques)."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)
