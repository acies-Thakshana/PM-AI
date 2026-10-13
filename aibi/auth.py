"""Local authentication stub (no IdP / no cloud)."""

from __future__ import annotations

from aibi.settings import LocalAuthUser, get_settings, load_yaml


def list_users() -> list[LocalAuthUser]:
    raw = load_yaml(get_settings().users_path)
    return [LocalAuthUser.model_validate(item) for item in (raw.get("users") or [])]


def authenticate(user_id: str | None = None) -> LocalAuthUser:
    settings = get_settings()
    uid = (user_id or settings.default_user_id).strip()
    for user in list_users():
        if user.user_id == uid:
            return user
    return LocalAuthUser(
        user_id=uid or "anonymous",
        display_name="Unknown local user",
        roles=[],
        authorized_bu_codes=[],
        can_query_cross_bu=False,
    )
