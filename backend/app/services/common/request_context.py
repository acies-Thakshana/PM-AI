"""Who is making the current request, available anywhere below the router without passing it
through every function (LLM calls, token accounting, audit logging).

`audit_store.get_or_404` sets the session (and its owner) for a request. Threads started by
a ThreadPoolExecutor do NOT inherit these automatically; wrap the submitted function with
`wrap()` so LLM calls made on worker threads are still attributed to the right user.
"""
from __future__ import annotations

import contextvars
from typing import Callable, TypeVar

T = TypeVar("T")

current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_id", default=None)
current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_session_id", default=None)


# The feature / analysis entry being computed right now, so an LLM call can be tied to the stored
# document its output ends up in (see token_usage.output_ref).
current_entry_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_entry_id", default=None)


# Every request is this one user until sign-in is added (the profiles table is keyed by user id).
LOCAL_USER_ID = "local"


def user_id() -> str:
    """The user making the current request (the single local user when none is set)."""
    return current_user_id.get() or LOCAL_USER_ID


def wrap(fn: Callable[..., T]) -> Callable[..., T]:
    """Bind `fn` to a copy of the caller's context: `executor.submit(wrap(fn), *args)`."""
    ctx = contextvars.copy_context()

    def runner(*args, **kwargs) -> T:
        return ctx.run(fn, *args, **kwargs)

    return runner
