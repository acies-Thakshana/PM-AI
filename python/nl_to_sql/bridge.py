"""Thin bridge stub for an external NL-to-SQL engine.

Configure AI_BI_NL2SQL_ROOT to the existing engine project (src on PYTHONPATH).
Do not reimplement SQL generation in this standalone project.
"""

from __future__ import annotations

import os
import sys
from typing import Any

__all__ = ["ask", "ask_debug", "run_nlq", "NLQRunner", "configure_external_engine"]


def configure_external_engine(project_root: str | None = None) -> str:
    """Add ``<project_root>/src`` to ``sys.path`` so ``import nlq`` works."""
    root = project_root or os.environ.get("AI_BI_NL2SQL_ROOT", "").strip()
    if not root:
        raise RuntimeError(
            "Set AI_BI_NL2SQL_ROOT to your existing NL-to-SQL project root "
            "(the folder that contains src/nlq), or pass project_root=..."
        )
    src = os.path.join(root, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    return src


def ask(question: str, **kwargs: Any) -> str:
    configure_external_engine()
    from nlq.notebook_runner import ask_nlq

    return ask_nlq(question, **kwargs)


def ask_debug(question: str, **kwargs: Any) -> dict[str, Any]:
    configure_external_engine()
    from nlq.notebook_runner import ask_nlq_debug

    return ask_nlq_debug(question, **kwargs)


def run_nlq(question: str, **kwargs: Any) -> Any:
    configure_external_engine()
    from nlq.graph.runner import run_nlq as _run_nlq

    return _run_nlq(question, **kwargs)


def __getattr__(name: str) -> Any:
    if name == "NLQRunner":
        configure_external_engine()
        from nlq.graph.runner import NLQRunner

        return NLQRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
