"""Project variables to AI4BI settings."""

from __future__ import annotations

import os
from typing import Any

from ai4bi.config.settings import Settings, load_settings
from ai4bi.logging import get_logger

LOGGER = get_logger(__name__)
FORWARDED = (
    "AIBI_DOMAIN",
    "AIBI_LLM_MODE",
    "AIBI_LLM_CONNECTION",
    "AIBI_LOG_LEVEL",
    "AIBI_PROJECT_ROOT",
    "AIBI_SETTINGS_PATH",
    "AIBI_AUTO_ONBOARD",
    "AIBI_INCLUDE_DRAFTS",
    "AIBI_JOIN_MIN_OVERLAP",
    "AIBI_ACTIVATION_CONFIDENCE",
    "AIBI_ONBOARDING_SAMPLE_VALUES",
)


def custom_variables() -> dict[str, Any]:
    import dataiku

    try:
        return dict(dataiku.get_custom_variables() or {})
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Could not read project variables: %s", exc)
        return {}


def apply_to_environment(variables: dict[str, Any]) -> None:
    for key in FORWARDED:
        value = variables.get(key)
        if value not in (None, ""):
            os.environ[key] = str(value)


def load_dataiku_settings(variables: dict[str, Any] | None = None) -> Settings:
    """Settings from config/settings.yaml with project variables applied. LLM mode defaults to mesh."""
    apply_to_environment(custom_variables() if variables is None else variables)
    os.environ.setdefault("AIBI_LLM_MODE", "mesh")
    return load_settings()
