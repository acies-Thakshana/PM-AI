from fastapi import APIRouter, HTTPException, Response

from app.services.common import jobs, request_context

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_LOST = "This request is no longer available (the server restarted or it expired). Please try again."


def _job_or_404(job_id: str) -> jobs.Job:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=_LOST)
    # A finished job belongs to the user whose request it was; others see "not found".
    if job.owner is not None and job.owner != request_context.user_id():
        raise HTTPException(status_code=404, detail=_LOST)
    return job


@router.get("/{job_id}")
def job_status(job_id: str):
    """`running` or `done`. Once done, `GET .../result` returns the endpoint's own response."""
    job = _job_or_404(job_id)
    return {
        "job_id": job.id,
        "status": job.status,
        "http_status": job.result.status_code if job.result else None,
    }


@router.get("/{job_id}/result")
def job_result(job_id: str):
    """The finished endpoint's response, exactly as it would have been sent (status, headers, body)."""
    job = _job_or_404(job_id)
    if job.result is None:
        raise HTTPException(status_code=409, detail="This job is still running.")
    return Response(content=job.result.body, status_code=job.result.status_code, headers=job.result.headers)
