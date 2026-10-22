"""One turn of the assistant: the model may look things up before it answers.

The protocol needs nothing from the model provider except the app's ordinary JSON call:

  1. The model answers with a JSON object.
  2. If it holds a non-empty "tool_calls" list ([{"name": ..., "args": {...}}]) the app runs those read-only
     tools (tools.py), adds their results to the prompt and asks again.
  3. Otherwise the object is the answer.

The loop is bounded so a turn can neither run away nor grow without limit:

  * at most MAX_ROUNDS rounds in which the model may ask for tools; the next call must answer;
  * at most MAX_CALLS_PER_ROUND tool calls per round and MAX_CALLS_TOTAL per turn;
  * each tool result is cut at MAX_RESULT_CHARS;
  * a TIME_BUDGET_SECONDS budget: past it, the model is told to answer with what it has.
  * a reply that is only a promise to look something up ("I'll look up that analysis.") gets ONE nudge to make the
    tool call instead (see promises_lookup).

Failures are not retried blindly: a tool that fails answers {"error": ...} (the model explains it), and a
model answer that is not JSON gets exactly one more chance.

After the loop, `ground` checks that the figures in the reply come from data the model was shown (grounding.py).
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.services.chat import tools
from app.services.chat.grounding import ungrounded_figures
from app.services.chat.tools import ToolContext

log = logging.getLogger(__name__)

MAX_ROUNDS = 4
MAX_CALLS_PER_ROUND = 3
MAX_CALLS_TOTAL = 6
MAX_RESULT_CHARS = 6000
TIME_BUDGET_SECONDS = 40.0

# (system prompt, user prompt) -> the model's JSON text.
AskModel = Callable[[str, str], str]

TOOLS_PROMPT = """
--- TOOLS ---
Before you answer you may look things up. To use tools, answer with ONLY {{"tool_calls":[{{"name":"...","args":{{...}}}}]}}: the app runs them and shows you the results, then you answer again. At most {per_round} tool calls at a time and a few rounds in total; when you have what you need, answer with the normal JSON object (without tool_calls). Tools only read: they never change anything, and you cannot name a session (it is fixed).
{tools}
"""

_ANSWER_NOW = "\n\n---\nYou have what you can get: answer now with the normal JSON object (no tool_calls)."
_NOT_JSON = "\n\n---\nYour last answer was not valid JSON. Answer again with the JSON object only, no other text."
_KEEP_YOUR_PROMISE = (
    "\n\n---\nYou said you would look something up but called no tool. Do it now: answer with "
    '{"tool_calls":[...]} for the tools you need, or answer from what you already have. Never answer with only a promise.'
)
_REVIEW = (
    "\n\n---\nREVIEW: your reply contained figures that appear in none of the data you were shown: {figures}. "
    "Answer again using only figures from the tool results and data above, or leave the figures out."
)


# A reply that is nothing but a promise to look something up: short, and it starts with the promise.
_PROMISE = re.compile(
    r"^(?:(?:sure|ok|okay|certainly|of course|absolutely)\b[\s,.!-]*)?"
    r"(?:i['\u2019]ll|i will|let me|allow me to|i['\u2019]m going to|i am going to)\s+(?:just\s+|quickly\s+)?"
    r"(?:look|check|find|pull|fetch|search|see|have a look|take a look)\b",
    re.IGNORECASE,
)
MAX_PROMISE_CHARS = 160


def promises_lookup(reply: str) -> bool:
    """Is `reply` only a promise to look something up ("I'll look up that analysis.")? A long answer that merely
    contains "let me know if you want me to check" is not."""
    text = reply.strip()
    return 0 < len(text) <= MAX_PROMISE_CHARS and bool(_PROMISE.match(text))


def tools_prompt() -> str:
    return TOOLS_PROMPT.format(per_round=MAX_CALLS_PER_ROUND, tools=tools.describe_tools())


# The tools that read one item, and what kind of item that is (the kinds `known_items` uses).
_OPENED_BY = {"get_analysis": "analysis", "get_feature": "feature"}


@dataclass
class TurnResult:
    raw: dict
    #: Everything the model was shown (prompt and tool results): the figures it may quote.
    evidence: str
    #: The tool results alone, so a review call can show them again.
    scratch: str
    tools_used: list[str]
    #: (kind, id) of every analysis ("analysis") or calculation ("feature") the model read successfully this turn.
    looked_at: list[tuple[str, str]] = field(default_factory=list)


def _parse(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("the model did not return an object")
    return data


def _calls(raw: dict) -> list[dict]:
    """The well-formed tool calls of an answer, capped per round."""
    found = []
    for call in raw.get("tool_calls") or []:
        if isinstance(call, dict) and isinstance(call.get("name"), str):
            args = call.get("args")
            found.append({"name": call["name"], "args": args if isinstance(args, dict) else {}})
    return found[:MAX_CALLS_PER_ROUND]


def _result_text(name: str, args: dict, result: dict) -> str:
    body = json.dumps(result, ensure_ascii=False, default=str)
    if len(body) > MAX_RESULT_CHARS:
        body = body[:MAX_RESULT_CHARS] + " ...(cut: too long, ask for something narrower)"
    return f"[{name} {json.dumps(args, ensure_ascii=False)}] -> {body}"


def run_turn(
    system_prompt: str,
    user_prompt: str,
    ask_model: AskModel,
    ctx: ToolContext | None,
    clock: Callable[[], float] = time.monotonic,
) -> TurnResult:
    """Ask the model, run the tools it asks for (when there is a session), and return its final answer.

    Raises ValueError when the model's answer is not JSON twice in a row (the caller turns that into an error)."""
    started = clock()
    scratch = ""
    used: list[str] = []
    looked_at: list[tuple[str, str]] = []
    retried_json = False
    nudged = False
    rounds = 0
    while True:
        out_of_budget = rounds >= MAX_ROUNDS or len(used) >= MAX_CALLS_TOTAL or clock() - started > TIME_BUDGET_SECONDS
        suffix = _ANSWER_NOW if (out_of_budget and used) else ""
        text = ask_model(system_prompt, user_prompt + scratch + suffix)
        try:
            raw = _parse(text)
        except ValueError:
            if retried_json:
                raise
            retried_json = True
            scratch += _NOT_JSON
            continue
        calls = [] if (ctx is None or out_of_budget) else _calls(raw)
        if not calls:
            # The model promised a lookup and called no tool: the loop would end here with the promise as the answer.
            # One nudge, so a lookup it meant to do is done; a second promise is passed on as it is.
            if ctx is not None and not out_of_budget and not nudged and not raw.get("actions") and promises_lookup(str(raw.get("reply") or "")):
                nudged = True
                scratch += _KEEP_YOUR_PROMISE
                continue
            return TurnResult(raw=raw, evidence=user_prompt + scratch, scratch=scratch, tools_used=used, looked_at=looked_at)
        rounds += 1
        lines = []
        for call in calls[: MAX_CALLS_TOTAL - len(used)]:
            used.append(call["name"])
            result = tools.run_tool(call["name"], call["args"], ctx)
            if call["name"] in _OPENED_BY and not result.get("error") and isinstance(result.get("id"), str):
                looked_at.append((_OPENED_BY[call["name"]], result["id"]))
            lines.append(_result_text(call["name"], call["args"], result))
        scratch += f"\n\n--- TOOL RESULTS (round {rounds}) ---\n" + "\n".join(lines)


def ground(
    result: TurnResult,
    system_prompt: str,
    user_prompt: str,
    ask_model: AskModel,
) -> tuple[dict, list[str]]:
    """Check the reply's figures against what the model was shown. A reply with figures it was never shown gets
    one review call; returns (answer, figures that are still unverified)."""
    figures = ungrounded_figures(str(result.raw.get("reply") or ""), result.evidence)
    if not figures:
        return result.raw, []
    log.warning("chat reply quoted figures not in the data: %s", figures)
    try:
        retry = _parse(ask_model(system_prompt, user_prompt + result.scratch + _REVIEW.format(figures=", ".join(figures))))
    except ValueError:
        return result.raw, figures
    still = ungrounded_figures(str(retry.get("reply") or ""), result.evidence)
    return (retry, still) if retry.get("reply") else (result.raw, figures)
