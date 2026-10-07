from __future__ import annotations

from fastapi import Request

from app.container import Container
from app.errors import AppError


def get_container(request: Request) -> Container:
    c = getattr(request.app.state, "container", None)
    if c is None:
        raise AppError("service is starting up")
    return c
