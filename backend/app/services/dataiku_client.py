"""Dataiku DSS client using the official dataikuapi SDK."""
import io
import json
import threading

import dataikuapi

from app import config

_lock = threading.Lock()
_project: dataikuapi.DSSProject | None = None


def _get_project() -> dataikuapi.DSSProject:
    global _project
    with _lock:
        if _project is None:
            client = dataikuapi.DSSClient(config.DATAIKU_DSS_URL, config.DATAIKU_API_KEY)
            _project = client.get_project(config.DATAIKU_PROJECT_KEY)
        return _project


def upload_to_folder(path: str, file_bytes: bytes) -> None:
    """Upload file_bytes to the uploads managed folder at the given path."""
    folder = _get_project().get_managed_folder(config.DATAIKU_UPLOADS_FOLDER_ID)
    folder.put_file(path, io.BytesIO(file_bytes))


def set_audit_variables(session_id: str, source: str, filename: str) -> None:
    """Write audit job parameters into project-level local variables."""
    project = _get_project()
    variables = project.get_variables()
    variables.setdefault("local", {}).update({
        "audit_session_id": session_id,
        "audit_source": source,
        "audit_filename": filename,
    })
    project.set_variables(variables)


def trigger_and_wait(scenario_id: str) -> str:
    """Trigger the scenario and block until it finishes. Returns the outcome string."""
    project = _get_project()
    scenario = project.get_scenario(scenario_id)
    run = scenario.run()
    run.wait_for_completion(no_fail=True)
    # The outcome is on the run object; try the property first, fall back to the raw dict.
    try:
        return run.outcome  # type: ignore[attr-defined]
    except AttributeError:
        return run.run.get("result", {}).get("outcome", "UNKNOWN")


def download_from_folder(path: str) -> bytes:
    """Download a file from the uploads managed folder."""
    folder = _get_project().get_managed_folder(config.DATAIKU_UPLOADS_FOLDER_ID)
    resp = folder.get_file(path)
    return resp.content


def fetch_audit_result(session_id: str) -> dict:
    """Download and parse the audit_result.json written by the Dataiku scenario."""
    raw = download_from_folder(f"{session_id}/audit_result.json")
    return json.loads(raw)
