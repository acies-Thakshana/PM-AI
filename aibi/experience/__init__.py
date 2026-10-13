"""Frozen experience layer: visuals, drills, explainability, Excel Escape."""

from aibi.experience.drill import apply_drill, load_drills
from aibi.experience.eval import run_excel_escape
from aibi.experience.explain import explain_answer
from aibi.experience.visuals import render_visual, validate_visual_bindings

__all__ = [
    "apply_drill",
    "explain_answer",
    "load_drills",
    "render_visual",
    "run_excel_escape",
    "validate_visual_bindings",
]
