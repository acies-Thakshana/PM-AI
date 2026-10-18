"""Shared fixtures. Every test runs on a temporary copy of config/ and storage/."""

from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "lib" / "python", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ai4bi.config.settings import load_settings  # noqa: E402
from ai4bi.knowledge.store import MemoryGraphStore  # noqa: E402
from ai4bi.pipeline.context import build_context  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("AIBI_DOMAIN", "AIBI_LLM_CONNECTION", "AIBI_SETTINGS_PATH", "AIBI_PROJECT_ROOT"):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    monkeypatch.setenv("AIBI_LLM_MODE", "local")
    monkeypatch.setenv("AIBI_LOG_LEVEL", "WARNING")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(ROOT / "config", root / "config")
    shutil.copytree(ROOT / "storage", root / "storage", ignore=shutil.ignore_patterns("*.jsonl"))
    for folder in ("knowledge_graph", "history"):
        target = root / "storage" / folder
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
    return root


@pytest.fixture
def settings(project: Path):
    return load_settings(project, env=False)


@pytest.fixture
def ctx(settings):
    return build_context(settings, configure_logging=False, history=False, graph_store=MemoryGraphStore())


@pytest.fixture
def persistent_ctx(settings):
    return build_context(settings, configure_logging=False)


@pytest.fixture
def service_frames(project: Path) -> dict[str, pd.DataFrame]:
    folder = project / "storage" / "samples" / "service_ops"
    return {p.stem: pd.read_csv(p) for p in folder.glob("*.csv")}


class FakeDataset:
    def __init__(self, registry: "FakeDataiku", name: str) -> None:
        self.registry = registry
        self.name = name

    def get_dataframe(self) -> pd.DataFrame:
        if self.name not in self.registry.datasets:
            raise KeyError(f"dataset {self.name} does not exist")
        return self.registry.datasets[self.name].copy()

    def write_with_schema(self, frame: pd.DataFrame) -> None:
        self.registry.written[self.name] = frame.copy()
        self.registry.datasets[self.name] = frame.copy()

    def get_location_info(self) -> dict[str, Any]:
        return {"info": {}}


class FakeCompletion:
    def __init__(self, llm: "FakeLlm") -> None:
        self.llm = llm
        self.messages: list[tuple[str, str]] = []
        self.settings: dict[str, Any] = {}

    def with_message(self, text: str, role: str = "user") -> "FakeCompletion":
        self.messages.append((role, text))
        return self

    def execute(self) -> Any:
        self.llm.calls.append(self.messages)
        return types.SimpleNamespace(success=True, text=self.llm.reply)


class FakeLlm:
    def __init__(self, reply: str = "") -> None:
        self.reply = reply
        self.calls: list[list[tuple[str, str]]] = []

    def new_completion(self) -> FakeCompletion:
        return FakeCompletion(self)


class FakeDataiku:
    """Enough of the dataiku package for the adapter and recipes."""

    def __init__(self) -> None:
        self.datasets: dict[str, pd.DataFrame] = {}
        self.written: dict[str, pd.DataFrame] = {}
        self.variables: dict[str, Any] = {}
        self.inputs: list[str] = []
        self.outputs: list[str] = []
        self.llm_ids = ["openai:gpt", "anthropic:claude-opus"]
        self.llm = FakeLlm()

    def module(self) -> types.ModuleType:
        fake = self
        dataiku = types.ModuleType("dataiku")
        recipe = types.ModuleType("dataiku.recipe")
        dataiku.Dataset = lambda name: FakeDataset(fake, name)
        dataiku.get_custom_variables = lambda: dict(fake.variables)
        project = types.SimpleNamespace(
            list_llms=lambda: [{"id": i} for i in fake.llm_ids],
            get_llm=lambda llm_id: fake.llm,
        )
        dataiku.api_client = lambda: types.SimpleNamespace(get_default_project=lambda: project)
        recipe.get_input_names_for_role = lambda role: list(fake.inputs) if role == "main" else []
        recipe.get_output_names_for_role = lambda role: list(fake.outputs) if role == "main" else []
        dataiku.recipe = recipe
        return dataiku


@pytest.fixture
def fake_dataiku(monkeypatch: pytest.MonkeyPatch, project: Path) -> FakeDataiku:
    fake = FakeDataiku()
    module = fake.module()
    monkeypatch.setitem(sys.modules, "dataiku", module)
    monkeypatch.setitem(sys.modules, "dataiku.recipe", module.recipe)
    monkeypatch.setenv("AIBI_PROJECT_ROOT", str(project))
    monkeypatch.delenv("AIBI_LLM_MODE", raising=False)
    return fake
