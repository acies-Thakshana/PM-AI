"""What the app can tell about a client brief without asking a model.

Only the obvious: text with no real words in it ("xxx", "asdf", "....") is not a brief, and fewer than
MIN_BRIEF_WORDS words is too short to be sure. Whether a short or odd text is really a brief is for the chat
assistant to judge and the PM to confirm (see routers/chat.py). The browser applies the same rule
(frontend/src/chat/rules.ts, briefQuality), so keep the two in step.
"""
from __future__ import annotations

import re

MIN_BRIEF_WORDS = 5

_LETTER_RUNS = re.compile(r"[^\W\d_]+")
_ASCII_VOWELS = set("aeiouy")


def _is_real_word(run: str) -> bool:
    """A run of letters that could be a word: two or more letters, not one letter repeated, and (for Latin
    letters) with a vowel in it. Words in other scripts are not judged by vowels."""
    if len(run) < 2 or len(set(run.lower())) < 2:
        return False
    return not run.isascii() or any(ch in _ASCII_VOWELS for ch in run.lower())


def brief_quality(text: str) -> str:
    """"junk" (no real word: not a brief), "short" (fewer than MIN_BRIEF_WORDS words: ask the PM) or "ok"."""
    if not any(_is_real_word(run) for run in _LETTER_RUNS.findall(text or "")):
        return "junk"
    return "short" if len((text or "").split()) < MIN_BRIEF_WORDS else "ok"
