"""Who and what the current request is about, available below the router without passing it down.

``deps.get_user`` sets the user, the request-id middleware sets the id, and the routers set the
domain. Worker threads do not inherit these automatically: submit work with ``wrap`` so LLM calls,
audit events and logs made on a worker stay attributed to the right user and request.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")

current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_request_id", default=None)
current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_id", default=None)
current_domain: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_domain", default=None)


@contextmanager
def request_scope(request_id: str) -> Iterator[None]:
    """Bind a request id for the duration of a ``with`` block."""
    token = current_request_id.set(request_id)
    try:
        yield
    finally:
        current_request_id.reset(token)


def wrap(fn: Callable[P, T]) -> Callable[P, T]:
    """Bind ``fn`` to a copy of the caller's context: ``executor.submit(wrap(fn), *args)``."""
    context = contextvars.copy_context()

    def runner(*args: P.args, **kwargs: P.kwargs) -> T:
        return context.run(fn, *args, **kwargs)

    return runner
