"""FastAPI application entrypoint.

Serves the REST + WebSocket API under /api and statically serves the built
React frontend bundle from frontend/dist when present.
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env before any settings are read so JWT_SECRET and other env vars
# defined in the project's .env file are available to os.environ.get calls.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import auth as auth_router
from app.api.v1 import agx as agx_router
from app.api.v1 import collateral as collateral_router
from app.api.v1 import desks as desks_router
from app.api.v1 import feargreed as feargreed_router
from app.api.v1 import oauth as oauth_router
from app.api.v1 import passkey as passkey_router
from app.api.v4 import admin as admin_router
from app.api.v4 import amm as amm_router
from app.api.v4 import community as community_router
from app.api.v4 import orders as orders_router
from app.api.v4 import positions as positions_router
from app.api.v4 import public as public_router
from app.api.v4 import resolution as resolution_router
from app.api.v4 import ws as ws_router
from app.api.v4 import ws_live as ws_live_router
from app.api.v4.dexbuilder import proxy as dexbuilder_proxy_router
from app.api.v4.prediction import extended as prediction_extended_router
from app.api.v4.prediction import live as prediction_live_router
from app.core.ratelimit import (
    AUTH_CAPACITY,
    AUTH_RATE,
    MONEY_CAPACITY,
    MONEY_RATE,
    ORDER_CAPACITY,
    ORDER_RATE,
    PUBLIC_CAPACITY,
    PUBLIC_RATE,
    rate_limiter,
)
from app.db.session import AsyncSessionLocal, init_db
from app.services.agx import AgxError

ORDER_MUTATION_PREFIX = "/api/v4/prediction/orders"
PUBLIC_READ_PREFIX = "/api/v4/prediction/"
AUTH_ATTACK_PATHS = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/oauth/exchange",
    "/api/v1/auth/wallet/challenge",
    "/api/v1/auth/wallet/verify",
    "/api/v1/auth/passkey/login/verify",
    "/api/v1/auth/passkey/register/options",
    "/api/v1/auth/passkey/register/verify",
)
MONEY_MUTATION_PATHS = (
    "/api/v1/collateral/deposit",
    "/api/v1/collateral/withdraw",
)


def _client_ip(request: Request) -> str:
    """Client IP for rate-limit bucketing.

    ``X-Forwarded-For`` is only honoured behind a trusted proxy (opt-in via
    ``TRUST_PROXY_HEADERS=1``); trusting it blindly lets any caller spoof a
    fresh bucket per request.
    """
    if os.environ.get("TRUST_PROXY_HEADERS", "").strip() == "1":
        forwarded = request.headers.get("X-Forwarded-For", "")
        first = forwarded.split(",")[0].strip() if forwarded else ""
        if first:
            return first
    return request.client.host if request.client else "anonymous"


def _credential(request: Request) -> str:
    return (
        request.headers.get("X-API-KEY")
        or request.headers.get("Authorization")
        or _client_ip(request)
    )


_REQUEST_COUNT = 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket limits + X-Request-ID correlation for all requests."""

    async def dispatch(self, request: Request, call_next):
        import uuid

        global _REQUEST_COUNT
        _REQUEST_COUNT += 1
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        path = request.url.path
        policy = None
        key = ""
        if (
            request.method in ("POST", "DELETE")
            and path.startswith(ORDER_MUTATION_PREFIX)
        ):
            key = f"orders:{_credential(request)}"
            policy = ("50 order requests/second", ORDER_RATE, ORDER_CAPACITY)
        elif request.method == "POST" and path in MONEY_MUTATION_PATHS:
            key = f"money:{_credential(request)}"
            policy = (
                "30 collateral mutations/minute",
                MONEY_RATE,
                MONEY_CAPACITY,
            )
        elif request.method == "GET" and path.startswith(PUBLIC_READ_PREFIX):
            key = f"public:{_client_ip(request)}"
            policy = ("100 public requests/minute", PUBLIC_RATE, PUBLIC_CAPACITY)
        elif request.method == "POST" and path in AUTH_ATTACK_PATHS:
            key = f"auth:{_client_ip(request)}"
            policy = ("30 sign-in attempts/minute", AUTH_RATE, AUTH_CAPACITY)

        if policy is not None:
            label, rate, capacity = policy
            allowed, retry_after = rate_limiter.allow(key, rate, capacity)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Rate limit exceeded: {label}"},
                    headers={
                        "Retry-After": f"{max(1, int(retry_after))}",
                        "X-RateLimit-Limit": label,
                    },
                )
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    import contextlib

    is_prod = os.environ.get("APP_ENV", "").strip().lower() == "production"
    if is_prod:
        from app.db.session import DATABASE_URL

        if DATABASE_URL.startswith("sqlite") and os.environ.get("ALLOW_SQLITE_PROD", "").strip() != "1":
            raise RuntimeError("Production requires explicit non-SQLite DATABASE_URL")
        if os.environ.get("CORS_ALLOW_ORIGINS", "*").strip() in ("", "*"):
            raise RuntimeError("Production requires explicit CORS_ALLOW_ORIGINS (wildcard '*' not allowed)")
    else:
        await init_db()
    from app.db.seed import seed
    from app.services import agx as agx_service
    from app.services.market_maker import mm_manager

    async with AsyncSessionLocal() as session:
        await seed(session)
        await session.commit()
    await mm_manager.resume_enabled()

    async def _epoch_rollover_loop():
        while True:
            await asyncio.sleep(900)
            try:
                async with AsyncSessionLocal() as s:
                    distributed = await agx_service.distribute_matured_epochs(s)
                    if distributed:
                        await s.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                import logging

                logging.getLogger("app.main").exception("agx epoch rollover failed")

    rollover_task = asyncio.create_task(_epoch_rollover_loop())
    try:
        yield
    finally:
        rollover_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await rollover_task
        await mm_manager.stop_all()


app = FastAPI(
    title="Dolymarket API",
    description="Dolymarket prediction markets: in-memory CLOB, CTF settlement, real-time streaming.",
    version="4.1.0",
    lifespan=lifespan,
    # Swagger/ReDoc move under /api so /docs can serve the markdown site.
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/openapi.json",
)

# Wildcard CORS keeps local dev frictionless; production deployments set
# CORS_ALLOW_ORIGINS (comma separated) to the exact frontend origins.
_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)


@app.exception_handler(AgxError)
async def _agx_error_handler(request: Request, exc: AgxError) -> JSONResponse:
    """Map AGX domain failures onto their stable HTTP status and error code."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.code})


def _json_safe(value):
    """Make a validation error JSON-encodable for Starlette's
    allow_nan=False encoder: non-finite floats and Decimals become strings
    instead of 500ing while rendering the 422 itself."""
    import math
    from decimal import Decimal

    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"detail": _json_safe(exc.errors())}
    )


app.include_router(auth_router.router)
app.include_router(agx_router.router)
app.include_router(collateral_router.router)
app.include_router(desks_router.router)
app.include_router(feargreed_router.router)
app.include_router(oauth_router.router)
app.include_router(passkey_router.router)
app.include_router(public_router.router)
app.include_router(orders_router.router)
app.include_router(positions_router.router)
app.include_router(resolution_router.router)
app.include_router(admin_router.router)
app.include_router(amm_router.router)
app.include_router(community_router.router)
app.include_router(ws_router.router)
app.include_router(ws_live_router.router)
app.include_router(prediction_extended_router.router)
app.include_router(prediction_live_router.router)
app.include_router(dexbuilder_proxy_router.router)


@app.get("/health")
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "dolymarket"}


@app.get("/metrics")
async def metrics():
    """Prometheus-compatible operational metrics."""
    from fastapi.responses import PlainTextResponse
    from app.ws.manager import manager
    from app.services.market_maker import mm_manager

    active_bots = sum(1 for st in mm_manager._desks.values() if st.running)
    lines = [
        f"dolymarket_requests_total {_REQUEST_COUNT}",
        f"dolymarket_ws_public_connections {len(manager.public)}",
        f"dolymarket_ws_private_connections {len(manager.private)}",
        f"dolymarket_mm_active_bots {active_bots}",
        f"dolymarket_mm_kill_switch {1 if mm_manager.global_kill_switch else 0}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


# Documentation site (built via `mkdocs build` in the repo root). Mounted
# BEFORE the frontend bundle so the more specific /docs prefix wins over the
# SPA catch-all at /.
_docs = Path(__file__).resolve().parent.parent / "site"
if _docs.is_dir():
    @app.get("/docs", include_in_schema=False)
    async def _docs_redirect():
        return RedirectResponse(url="/docs/", status_code=307)
    app.mount("/docs", StaticFiles(directory=str(_docs), html=True), name="docs")

# Static frontend bundle (built via `npm run build` in frontend/).
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
