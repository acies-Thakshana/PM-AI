"""
Deterministic pipeline coordinator. This is plain glue code, not an agent:
load data -> compute stats -> retrieve knowledge -> run Agent 1 -> run
Agent 2 -> save file. Runs each report job in a background thread and keeps
status in memory so the frontend can poll progress.
"""
import threading
import uuid
from datetime import datetime

from app.agents.insight_agent import generate_insights
from app.agents.ppt_agent import compose_report

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _update(job_id: str, **fields):
    with _lock:
        _jobs[job_id].update(fields)


def _run_job(job_id: str):
    try:
        _update(job_id, status="running", stage="analyzing",
                 stage_label="Agent 1 (Insight Analyst) is correlating cold chain data with post-harvest domain knowledge...")
        insights = generate_insights()

        _update(job_id, stage="composing",
                 stage_label="Agent 2 (Report Composer) is assembling the formatted PPTX deck...")
        output_path, calls = compose_report(insights)

        _update(job_id, status="done", stage="complete", stage_label="Report ready.",
                file_path=str(output_path), file_name=output_path.name, tool_calls=len(calls))
    except Exception as exc:  # noqa: BLE001
        _update(job_id, status="error", stage="failed", stage_label="Report generation failed.", error=str(exc))


def start_report_job() -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = dict(
            job_id=job_id, status="queued", stage="queued", stage_label="Queued...",
            created_at=datetime.now().isoformat(), file_path=None, file_name=None, error=None,
        )
    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None
