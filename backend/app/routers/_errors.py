"""Errors from a service the app depends on (the model, SWP, AWS): the details go to the server log, the caller
gets a short message. Raw exception text can carry host names, response snippets and AWS details."""
import logging

from fastapi import HTTPException

log = logging.getLogger("app.errors")


def upstream_error(status_code: int, message: str, exc: BaseException) -> HTTPException:
    """The HTTPException to raise (`raise upstream_error(...) from exc`); `exc` is logged in full here."""
    log.error("%s: %s", message, exc, exc_info=exc)
    return HTTPException(status_code=status_code, detail=message)
