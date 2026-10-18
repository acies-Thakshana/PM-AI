from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai4bi.config import ConfigError, load_settings
from ai4bi.config.settings import resolve_project_root


def test_defaults_resolve_paths_under_the_project(project: Path):
    settings = load_settings(project, env=False)
    assert settings.project_root == project.resolve()
    assert settings.semantic_root == project.resolve() / "storage" / "semantic" / "domains"
    assert settings.llm_mode == "local"
    assert settings.row_limit == 500
    assert "replace" not in settings.forbidden_keywords
    assert settings.followup_templates


def test_environment_overrides_domain_and_mode(project: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AIBI_DOMAIN", "generic_cube")
    monkeypatch.setenv("AIBI_LLM_MODE", "mesh")
    monkeypatch.setenv("AIBI_LLM_CONNECTION", "conn-1")
    settings = load_settings(project)
    assert settings.default_domain == "generic_cube"
    assert settings.llm_mode == "mesh"
    assert settings.llm_connection == "conn-1"


def test_overlay_file_merges_over_base(project: Path, monkeypatch: pytest.MonkeyPatch):
    overlay = project / "config" / "settings.local.yaml"
    overlay.write_text(yaml.safe_dump({"app": {"row_limit": 7}}), encoding="utf-8")
    monkeypatch.setenv("AIBI_SETTINGS_PATH", "config/settings.local.yaml")
    settings = load_settings(project)
    assert settings.row_limit == 7
    assert settings.default_domain == "service_ops"


def test_dotenv_file_is_read(project: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AIBI_LLM_MODE", raising=False)
    (project / ".env").write_text("AIBI_DOMAIN=generic_cube\n", encoding="utf-8")
    monkeypatch.setenv("AIBI_DOMAIN", "")
    monkeypatch.delenv("AIBI_DOMAIN")
    assert load_settings(project).default_domain == "generic_cube"


def test_invalid_mode_is_a_config_error(project: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AIBI_LLM_MODE", "bedrock")
    with pytest.raises(ConfigError, match="llm.mode"):
        load_settings(project)


def test_missing_settings_file_names_the_path(tmp_path: Path):
    (tmp_path / "config").mkdir()
    with pytest.raises(ConfigError, match="settings.yaml"):
        load_settings(tmp_path, env=False)


def test_missing_required_path_is_reported(project: Path):
    path = project / "config" / "settings.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    del payload["paths"]["samples_root"]
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ConfigError, match="samples_root"):
        load_settings(project, env=False)


def test_project_root_env_var_wins(project: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AIBI_PROJECT_ROOT", str(project))
    assert resolve_project_root() == project.resolve()
