"""Checks that the figures in an assistant reply come from data the assistant was actually shown.

The model explains; it must not invent numbers. A reply is "grounded" when every figure that matters in it
(a percentage, a decimal, a count of 100 or more) also appears in the tool results, the data block or the
conversation that the model had in front of it. Small whole numbers ("2 analyses", "step 3") are not checked:
they are ordinary words, not results.
"""
from __future__ import annotations

import re

# A number as people write it: 1,234 / 12.5 / 87% / -3.2
_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?")
_YEAR_RANGE = range(1900, 2101)
_REL_TOLERANCE = 0.005  # 0.5 %: the model may round a figure the tool returned with more decimals


def _value(token: str) -> float | None:
    try:
        return float(token.rstrip("%").replace(",", ""))
    except ValueError:
        return None


def numbers_in(text: str) -> list[float]:
    """Every number in `text` (the evidence the model was shown)."""
    values = (_value(m.group(0)) for m in _NUMBER.finditer(text))
    return [v for v in values if v is not None]


def _needs_check(token: str, value: float) -> bool:
    if token.endswith("%") or "." in token:
        return True
    digits = len(token.lstrip("-").replace(",", ""))
    if digits < 3:
        return False  # "2 analyses", "step 3": words, not results
    return not (float(value).is_integer() and int(value) in _YEAR_RANGE)  # years are dates, not figures


def _decimals(token: str) -> int:
    return len(token.rstrip("%").split(".", 1)[1]) if "." in token else 0


def _matches(value: float, evidence: float, token: str) -> bool:
    places = _decimals(token)
    candidates = [evidence]
    if token.endswith("%"):
        candidates.append(evidence * 100)  # the data holds the share as 0.12, the reply says 12%
    for candidate in candidates:
        if round(candidate, places) == value:
            return True
        if abs(candidate - value) <= max(abs(value) * _REL_TOLERANCE, 0.5 * 10 ** -places):
            return True
    return False


def ungrounded_figures(reply: str, evidence: str) -> list[str]:
    """The figures in `reply` that appear nowhere in `evidence` (empty when the reply is grounded)."""
    known = numbers_in(evidence)
    missing: list[str] = []
    for match in _NUMBER.finditer(reply):
        token = match.group(0)
        value = _value(token)
        if value is None or not _needs_check(token, value):
            continue
        if not any(_matches(value, e, token) for e in known) and token not in missing:
            missing.append(token)
    return missing
