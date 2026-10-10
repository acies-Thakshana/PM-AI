from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import DATA_DIR
from app.routers import analysis, analysis_paths, audit, brief, features, planner, report
from app.services.audit.audit_store import SessionConflict
from app.services.common import doc_store, session_repo, token_usage

app = FastAPI(title="Cold Chain Data Audit API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # Vite's dev server auto-increments past a taken port (5173 -> 5174 ->
    # ...) every time an old instance is still holding one, which drifts
    # past CORS_ORIGINS' fixed list after a few restarts. Matching any
    # localhost/127.0.0.1 port covers that without having to keep guessing
    # -- this app has no cookie-based auth for the regex's broader match to
    # put at risk, and it's dev-only in intent (the deployed frontend origin
    # should still be added to CORS_ORIGINS explicitly for production).
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(SessionConflict)
async def _session_conflict_handler(request: Request, exc: SessionConflict):
    return JSONResponse(
        status_code=409,
        content={"detail": "This session was changed by another request. Reload and try again."},
    )


@app.exception_handler(session_repo.FramesUnavailable)
async def _frames_unavailable_handler(request: Request, exc: session_repo.FramesUnavailable):
    # The session's data lived in memory and is gone (restart, or another task served it).
    return JSONResponse(status_code=410, content={"detail": str(exc)})


@app.exception_handler(doc_store.VersionConflict)
async def _doc_conflict_handler(request: Request, exc: doc_store.VersionConflict):
    return JSONResponse(
        status_code=409,
        content={"detail": "This data was changed by another request. Reload and try again."},
    )


app.include_router(brief.router)
app.include_router(audit.router)
app.include_router(planner.router)
app.include_router(features.router)
app.include_router(analysis.router)
app.include_router(analysis_paths.router)
app.include_router(report.router)

# Bundled example files for the Upload page's "Add all samples" button (see
# UploadPage.tsx) -- fetched as plain static bytes and turned into File
# objects client-side, so trying the app end to end never requires hunting
# down real source files first. Not meant for anything past that: nothing
# server-side reads from this mount.
app.mount("/samples", StaticFiles(directory=DATA_DIR / "samples"), name="samples")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/token-usage")
def token_usage_report():
    """Per-call token usage (input/output/total) recorded since this
    process started, aggregated by which of the 8 LLM calls made them."""
    return {
        "summary_by_call": token_usage.summary_by_call(),
        "records": [vars(r) for r in token_usage.get_records()],
    }
