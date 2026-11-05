"""FastAPI application entrypoint.

Serves the REST + WebSocket API under /api and statically serves the built
React frontend bundle from frontend/dist when present.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import auth as auth_router
from app.api.v1 import collateral as collateral_router
from app.api.v1 import desks as desks_router
from app.api.v1 import oauth as oauth_router
from app.api.v1 import passkey as passkey_router
from app.api.v4 import admin as admin_router
from app.api.v4 import orders as orders_router
from app.api.v4 import positions as positions_router
from app.api.v4 import public as public_router
from app.api.v4 import resolution as resolution_router
from app.api.v4 import ws as ws_router
from app.api.v4.dexbuilder import proxy as dexbuilder_proxy_router
from app.api.v4.prediction import extended as prediction_extended_router
from app.core.ratelimit import (
    AUTH_CAPACITY,
    AUTH_RATE,
    ORDER_CAPACITY,
    ORDER_RATE,
    PUBLIC_CAPACITY,
    PUBLIC_RATE,
    rate_limiter,
)
from app.db.session import AsyncSessionLocal, init_db

ORDER_MUTATION_PREFIX = "/api/v4/prediction/orders"
PUBLIC_READ_PREFIX = "/api/v4/prediction/"
AUTH_ATTACK_PATHS = (
    "/api/v1/auth/login",
    "/api/v1/auth/oauth/exchange",
    "/api/v1/auth/passkey/login/verify",
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket limits for order mutations and public reads."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        policy = None
        key = ""
        if (
            request.method in ("POST", "DELETE")
            and path.startswith(ORDER_MUTATION_PREFIX)
        ):
            credential = (
                request.headers.get("X-API-KEY")
                or request.headers.get("Authorization")
                or (request.client.host if request.client else "anonymous")
            )
            key = f"orders:{credential}"
            policy = ("50 order requests/second", ORDER_RATE, ORDER_CAPACITY)
        elif request.method == "GET" and path.startswith(PUBLIC_READ_PREFIX):
            ip = request.client.host if request.client else "anonymous"
            key = f"public:{ip}"
            policy = ("100 public requests/minute", PUBLIC_RATE, PUBLIC_CAPACITY)
        elif request.method == "POST" and path in AUTH_ATTACK_PATHS:
            ip = request.client.host if request.client else "anonymous"
            key = f"auth:{ip}"
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
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.db.seed import seed

    async with AsyncSessionLocal() as session:
        await seed(session)
    yield


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

app.include_router(auth_router.router)
app.include_router(collateral_router.router)
app.include_router(desks_router.router)
app.include_router(oauth_router.router)
app.include_router(passkey_router.router)
app.include_router(public_router.router)
app.include_router(orders_router.router)
app.include_router(positions_router.router)
app.include_router(resolution_router.router)
app.include_router(admin_router.router)
app.include_router(ws_router.router)
app.include_router(prediction_extended_router.router)
app.include_router(dexbuilder_proxy_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "dolymarket"}


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
