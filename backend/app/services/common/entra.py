"""Validation of Microsoft Entra ID access tokens. Pure logic: no FastAPI imports.

A token is accepted when its signature verifies against the tenant's published keys, it has not
expired, it was issued by the configured tenant for this application, and (for tokens issued on
behalf of a user) it carries the required scope. Roles and groups are only read, never trusted
beyond what the signed token says.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import jwt
from jwt import PyJWKClient

from app.errors import AuthenticationError

LOGGER = logging.getLogger(__name__)

_LOGIN = "https://login.microsoftonline.com"
_ALGORITHMS = ["RS256"]


@dataclass(frozen=True)
class Identity:
    user_id: str
    name: str = ""
    roles: frozenset[str] = field(default_factory=frozenset)
    groups: frozenset[str] = field(default_factory=frozenset)


class TokenValidator:
    def __init__(self, tenant_id: str, client_id: str, required_scope: str) -> None:
        self._client_id = client_id
        self._required_scope = required_scope
        # Entra issues v1 tokens (sts.windows.net) or v2 tokens (login.microsoftonline.com)
        # depending on the app registration; both are legitimate for the same tenant.
        self._issuers = [f"{_LOGIN}/{tenant_id}/v2.0", f"https://sts.windows.net/{tenant_id}/"]
        self._audiences = [client_id, f"api://{client_id}"]
        self._jwks = PyJWKClient(f"{_LOGIN}/{tenant_id}/discovery/v2.0/keys", cache_keys=True, lifespan=3600)

    def validate(self, token: str) -> Identity:
        """Return the caller's identity, or raise ``AuthenticationError``. May block on a key fetch."""
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=_ALGORITHMS,
                audience=self._audiences,
                issuer=self._issuers,
                options={"require": ["exp", "iss", "aud"]},
                leeway=30,
            )
        except jwt.PyJWTError as exc:
            LOGGER.info("Rejected token: %s", exc)
            raise AuthenticationError("The sign-in token is missing, expired or not valid.") from exc
        return self._identity(claims)

    def _identity(self, claims: dict[str, Any]) -> Identity:
        scopes = str(claims.get("scp") or "").split()
        if scopes and self._required_scope not in scopes:
            raise AuthenticationError(f"The token does not grant the {self._required_scope!r} scope.")
        user_id = str(claims.get("oid") or claims.get("sub") or "")
        if not user_id:
            raise AuthenticationError("The token does not identify a user.")
        return Identity(
            user_id=user_id,
            name=str(claims.get("name") or claims.get("preferred_username") or ""),
            roles=frozenset(str(role) for role in claims.get("roles") or []),
            groups=frozenset(str(group) for group in claims.get("groups") or []),
        )
