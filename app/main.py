"""FastAPI application entrypoint.

Serves the REST + WebSocket API under /api and statically serves the built
React frontend bundle from frontend/dist when present.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import auth as auth_router
from app.api.v1 import collateral as collateral_router
from app.api.v4 import admin as admin_router
from app.api.v4 import orders as orders_router
from app.api.v4 import positions as positions_router
from app.api.v4 import public as public_router
from app.api.v4 import resolution as resolution_router
from app.api.v4 import ws as ws_router
from app.db.session import AsyncSessionLocal, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.db.seed import seed

    async with AsyncSessionLocal() as session:
        await seed(session)
    yield


app = FastAPI(
    title="Prediction Market Platform API",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(collateral_router.router)
app.include_router(public_router.router)
app.include_router(orders_router.router)
app.include_router(positions_router.router)
app.include_router(resolution_router.router)
app.include_router(admin_router.router)
app.include_router(ws_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "prediction-market-platform"}


# Static frontend bundle (built via `npm run build` in frontend/).
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
