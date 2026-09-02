"""Shared helpers for routers -- currently just the one every router that
touches an audit session needs: look it up or 404."""
from fastapi import HTTPException

from app.services.audit_store import AuditSession, store


def get_session_or_404(session_id: str) -> AuditSession:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    return session
