"""FastAPI entrypoint. The container (and EMBEDDING_DIM validation) is built at startup: misconfig fails loudly."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.db.client import ping
from app.errors import install_error_handlers
from app.logging_setup import configure_logging, get_logger, log_event, request_id_var

log = get_logger(__name__)
RECONCILE_EVERY_SECONDS = 60


class Health(BaseModel):
    status: str
    dynamodb: bool
    dynamodb_error: str | None = None
    vector_backend: str
    env: str
    
    
async def _reconciler(app:FastAPI):
    while True:
        await asyncio.sleep(RECONCILE_EVERY_SECONDS)
        try:
            res = await run_in_threadpool(app.state.container.memory_service.reconcile_pending)
            if res["pending"]:
                log_event(log, "reconciler.tick", **res)
        except Exception:  # noqa: BLE001
            log.exception("reconciler.tick_failed")
            
def create_app(settings: Settings | None = None, container: Any | None = None,
               build_on_startup: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = None
        if app.state.container is None and build_on_startup:
            from app.container import build_container

            app.state.container = build_container(settings)  # raises ConfigError on dim mismatch
        if app.state.container is not None and settings.app_env != "test":
            task = asyncio.create_task(_reconciler(app))
        log_event(log, "app.startup", env=settings.app_env, vector_backend=settings.vector_backend,
                  chat_model=settings.openai_chat_model, embedding_model=settings.embedding_model)
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        log_event(log, "app.shutdown")
    
    app = FastAPI(title="Heirloom", version="0.5.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.container = container
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["x-request-id"])
    install_error_handlers(app)
    
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        
        try:
            response = await call_next(request)
            response.headers["x-request-id"] = rid
            log_event(log, "http.request", method=request.method, path=request.url.path,
                      status=response.status_code, ms=round((time.perf_counter() - t0) * 1000, 1))
            return response
        
        finally:
            request_id_var.reset(token)
            
        
    
    @app.get("/healthz", response_model=Health, tags=["ops"])
    def healthz() -> Health:
        ok, err = ping(settings)
        if not ok:
            log_event(log, "health.dynamodb_unreachable", logging.WARNING, error=err)
        return Health(status="ok" if ok else "degraded", dynamodb=ok, dynamodb_error=err,
                      vector_backend=settings.vector_backend, env=settings.app_env)
        
    from app.api.routes import router
    
    app.include_router(router)
    return app
        


def __getattr__(name: str) -> Any:  # lazy `app` for uvicorn app.main:app (no side effects on import)
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)