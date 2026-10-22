"""Regenera docs/graph.mmd. Ejecutar desde la raíz del repo: python -m scripts.make_diagram"""
import os

from app.graph import build_graph

mermaid = build_graph().get_graph().draw_mermaid()
print(mermaid)

os.makedirs("docs", exist_ok=True)
with open("docs/graph.mmd", "w", encoding="utf-8") as f:
    f.write(mermaid)
