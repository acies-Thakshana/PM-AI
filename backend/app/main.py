import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import dashboard, ingestion, report, trips
from app.services.live_feed import run_live_feed_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_live_feed_loop())
    yield
    task.cancel()


app = FastAPI(title="Cold Chain Post-Harvest Assessment API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # local-dev PoC: allow any localhost port so this doesn't break if Vite
    # picks a different port (e.g. 5173 already in use -> 5174, etc.)
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(report.router)
app.include_router(ingestion.router)
app.include_router(trips.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
