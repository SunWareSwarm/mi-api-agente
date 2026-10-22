"""Dependencias compartidas de FastAPI (las usan main.py y hitl.py; los tests las reemplazan)."""
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_graph(request: Request):
    return request.app.state.graph


RedisDep = Annotated[Redis, Depends(get_redis)]  # "inyección de dependencias"
GraphDep = Annotated[object, Depends(get_graph)]
