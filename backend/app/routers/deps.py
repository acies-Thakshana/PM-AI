"""FastAPI dependencies: who is calling, what they may do, and which domain they may use."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header
from fastapi.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.errors import AuthenticationError, ForbiddenError
from app.services.common import request_context
from app.services.common.entra import TokenValidator
from app.services.common.naming import validate_domain
from app.services.context import AppContext, get_context

ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class User:
    id: str
    name: str = ""
    roles: frozenset[str] = field(default_factory=frozenset)
    groups: frozenset[str] = field(default_factory=frozenset)


@lru_cache(maxsize=1)
def _validator() -> TokenValidator:
    settings = get_settings()
    return TokenValidator(settings.entra_tenant_id, settings.entra_client_id, settings.entra_required_scope)


def settings_dep() -> Settings:
    return get_settings()


def context_dep() -> AppContext:
    return get_context()


SettingsDep = Annotated[Settings, Depends(settings_dep)]
ContextDep = Annotated[AppContext, Depends(context_dep)]


async def get_user(settings: SettingsDep, authorization: Annotated[str | None, Header()] = None) -> User:
    """Authenticate the caller.

    Without Entra configured (local development) everyone is one anonymous user holding every
    role. ``Settings.validate`` refuses to start in that mode with AWS storage unless ALLOW_ANON
    is set, so a misconfigured deployment fails closed rather than open.

    This is ``async`` on purpose: it binds the user to the request's context so every log line
    and audit event below it is attributed correctly, which a threadpool dependency cannot do.
    """
    if not settings.auth_enabled:
        user = User(ANONYMOUS, roles=frozenset({settings.role_user, settings.role_steward}))
    else:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("Send the sign-in token as 'Authorization: Bearer <token>'.")
        identity = await run_in_threadpool(_validator().validate, token.strip())
        user = User(identity.user_id, identity.name, identity.roles, identity.groups)
    request_context.current_user_id.set(user.id)
    return user


UserDep = Annotated[User, Depends(get_user)]


def require_user(user: UserDep, settings: SettingsDep) -> User:
    if not user.roles & {settings.role_user, settings.role_steward}:
        raise ForbiddenError(f"This action needs the {settings.role_user} role.")
    return user


def require_steward(user: UserDep, settings: SettingsDep) -> User:
    if settings.role_steward not in user.roles:
        raise ForbiddenError(f"This action needs the {settings.role_steward} role.")
    return user


CurrentUser = Annotated[User, Depends(require_user)]
Steward = Annotated[User, Depends(require_steward)]


def may_access(user: User, domain: str, settings: Settings) -> bool:
    """Whether ``DOMAIN_GROUPS`` lets the user into the domain (domains not listed are open)."""
    allowed = settings.domain_groups.get(domain)
    return not allowed or bool(user.groups & set(allowed))


def authorize_domain(user: User, domain: str, settings: Settings) -> str:
    """Check the domain id is well formed and the user may use it. Returns the domain id.

    When ``DOMAIN_GROUPS`` lists groups for the domain, the user must belong to one of them.
    Domains that are not listed are open to every signed-in user. Call this from ``async``
    code (the domain dependencies below are) so the domain is bound to the request's context.
    """
    validate_domain(domain)
    if not may_access(user, domain, settings):
        raise ForbiddenError(f"You do not have access to domain {domain!r}.")
    request_context.current_domain.set(domain)
    return domain


async def user_domain(domain: str, user: CurrentUser, settings: SettingsDep) -> str:
    """Path dependency for routes any signed-in user may call."""
    return authorize_domain(user, domain, settings)


async def steward_domain(domain: str, user: Steward, settings: SettingsDep) -> str:
    """Path dependency for routes only a steward may call."""
    return authorize_domain(user, domain, settings)


UserDomain = Annotated[str, Depends(user_domain)]
StewardDomain = Annotated[str, Depends(steward_domain)]
