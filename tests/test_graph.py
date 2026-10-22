from langgraph.checkpoint.redis.jsonplus_redis import JsonPlusRedisSerializer

INITIAL = {
    "messages": [("user", "¿Población de Chile y Argentina?")],
    "step_count": 0,
    "task_completed": False,
    "contributions": [],
    "research_output": None,
    "analysis_output": None,
}
CONFIG = {"configurable": {"thread_id": "t-1"}, "recursion_limit": 30}


async def test_flujo_completo_supervisor_especialistas_synthesizer(graph):
    final = await graph.ainvoke(INITIAL, CONFIG)
    agentes = [c["agent"] for c in final["contributions"]]
    assert agentes == ["supervisor", "researcher", "supervisor", "analyst", "supervisor", "synthesizer"]
    assert final["task_completed"] is True
    assert "respuesta simulada" in final["messages"][-1].content


async def test_el_estado_queda_guardado_por_thread_id(graph):
    await graph.ainvoke(INITIAL, CONFIG)
    snapshot = await graph.aget_state(CONFIG)  # lee el último checkpoint de ese thread_id
    assert snapshot.values["research_output"]["sufficient"] is True
    assert snapshot.values["analysis_output"]["data_quality_ok"] is True


async def test_las_salidas_sobreviven_al_serializador_json_de_redis(graph):
    """El checkpointer de Redis guarda JSON: lo que se escribe debe ser lo que se lee."""
    final = await graph.ainvoke(INITIAL, CONFIG)
    datos = {k: final[k] for k in ("research_output", "analysis_output", "contributions")}
    serde = JsonPlusRedisSerializer()
    assert serde.loads_typed(serde.dumps_typed(datos)) == datos
