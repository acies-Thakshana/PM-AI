"""Kicks off and tracks the 2-agent report generation pipeline (see
app/orchestrator.py) and serves the finished .pptx for download."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import orchestrator

router = APIRouter(prefix="/api/report", tags=["report"])


@router.post("/generate")
def generate_report():
    job_id = orchestrator.start_report_job()
    return {"job_id": job_id}


@router.get("/status/{job_id}")
def report_status(job_id: str):
    job = orchestrator.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/download/{job_id}")
def download_report(job_id: str):
    job = orchestrator.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "done" or not job["file_path"]:
        raise HTTPException(status_code=409, detail=f"report not ready (status={job['status']})")
    return FileResponse(
        job["file_path"],
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=job["file_name"],
    )
