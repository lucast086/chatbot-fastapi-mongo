"""Application entry point.

Wires the FastAPI app: the lifespan (MongoDB client plus idempotent index
creation) and the two health checks.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.adapters.mongo.connection import create_client, ensure_indexes
from app.adapters.openrouter.llm import OpenRouterLLM, OpenRouterTitleGenerator
from app.api.errors import DOCS_BASE_URL, register_exception_handlers
from app.api.routers.conversations import router as conversations_router
from app.api.routers.streaming import router as streaming_router
from app.api.schemas import ConfigResponse
from app.core.config import get_settings
from app.core.dependencies import DbDep, SettingsDep

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    client = create_client(settings.mongo_uri.get_secret_value())
    app.state.mongo_client = client
    app.state.mongo_db = client[settings.mongo_db]

    # Index creation needs a reachable server. A failure here must not stop the
    # application: the readiness probe already reports MongoDB being down, and
    # crashing on boot would turn a recoverable outage into a restart loop.
    try:
        await ensure_indexes(app.state.mongo_db)
    except Exception:
        logger.warning("Could not create indexes at startup; MongoDB is unreachable.")

    # Built once, like the Mongo client and for the same reason: each
    # AsyncOpenAI owns an httpx connection pool, so constructing them per
    # request meant a fresh TLS handshake on every turn — added straight to
    # time-to-first-token on a streaming product — and pools that were never
    # closed, accumulating sockets under load.
    app.state.llm = OpenRouterLLM(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        models=settings.openrouter_models,
        system_prompt=settings.system_prompt,
        timeout_seconds=settings.request_timeout_seconds,
        max_output_tokens=settings.max_output_tokens,
        first_token_timeout_seconds=settings.first_token_timeout_seconds,
    )
    app.state.title_generator = OpenRouterTitleGenerator(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        # The first model only. A title is a nicety; it does not deserve a
        # fallback chain, and failing it costs nothing.
        model=settings.openrouter_models[0],
        timeout_seconds=settings.request_timeout_seconds,
    )

    # Detected here rather than when someone sends their first message, so the
    # UI can show the banner as soon as the page opens.
    if not settings.provider_configured:
        logger.warning(
            "OPENROUTER_API_KEY is not set. The app is running in a degraded state: "
            "conversations and history work, message generation will return an error. "
            "See the README for how to obtain a key."
        )

    try:
        yield
    finally:
        await app.state.llm.aclose()
        await app.state.title_generator.aclose()
        await client.close()


app = FastAPI(
    title="Chatbot",
    version="0.1.0",
    lifespan=lifespan,
)

register_exception_handlers(app)
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(streaming_router, prefix="/api/v1")


@app.get("/api/v1/config", tags=["config"])
async def read_config(settings: SettingsDep) -> ConfigResponse:
    """What the frontend needs on load.

    Separate from the health endpoints on purpose: health is a contract for an
    orchestrator and should be free to change shape, this is a contract for the
    UI. The model name and a documentation link have no business in a health
    probe.
    """
    return ConfigResponse(
        provider_configured=settings.provider_configured,
        models=settings.openrouter_models,
        streaming_enabled=True,
        docs_url=DOCS_BASE_URL,
    )


@app.get("/health/live", tags=["health"])
async def health_live() -> dict[str, str]:
    """Liveness: the process is up and answering.

    Touches no external dependency on purpose. If this failed because MongoDB
    was down, an orchestrator would restart a container that has nothing wrong
    with it.
    """
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
async def health_ready(settings: SettingsDep, db: DbDep) -> JSONResponse:
    """Readiness: can this instance serve requests right now.

    Returns 200 with `status: "degraded"` when only the API key is missing. That
    state is deliberate — everything except generation works — and a 503 would
    mean `depends_on: service_healthy` never passes, breaking `docker compose up`
    for exactly the person who has not configured a key.

    503 is reserved for MongoDB being unreachable, which genuinely makes the
    instance unable to serve.

    This is a status report rather than an error response, so it does not use
    the error envelope the rest of the API returns.
    """
    checks: dict[str, Any] = {}

    try:
        await db.command("ping")
        checks["mongo"] = "ok"
        mongo_ok = True
    except Exception:
        checks["mongo"] = "unreachable"
        mongo_ok = False

    checks["llm_provider"] = "ok" if settings.provider_configured else "not_configured"

    if not mongo_ok:
        status = "unavailable"
    elif not settings.provider_configured:
        status = "degraded"
    else:
        status = "ok"

    return JSONResponse(
        status_code=200 if mongo_ok else 503,
        content={"status": status, "checks": checks},
    )
