"""Greeting reply and "that is not a brief" handling of the chat (routers/chat.py).

The model is never called in the greeting tests: if it were, the test would fail, because _ask_model is made to blow up.
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import chat, deps


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(deps, "AUTH_ENABLED", False)
    monkeypatch.setattr(deps, "USE_AWS_STORAGE", False)
    monkeypatch.setattr(chat.orchestrator, "run_turn", lambda *a, **k: SimpleNamespace(looked_at=[], tools_used=[]))
    monkeypatch.setattr(chat.orchestrator, "ground", lambda result, *a, **k: (MODEL_SAYS["raw"], []))
    return TestClient(app, raise_server_exceptions=False)


MODEL_SAYS = {"raw": {}}


def _say(client, text, brief="", state=None, hidden=False):
    body = {"brief": brief, "messages": [{"role": "user", "content": text}], "state": state or {}, "hidden": hidden}
    return client.post("/api/chat/turn", json=body)


@pytest.mark.parametrize("text", ["Hi", "hello", "Hey there", "good morning", "What should I do?", "How does this app work?"])
def test_greetings_and_app_questions_are_answered_by_the_model(client, text):
    """The reply is whatever the assistant wrote for this message: no stock sentence from the app, and no 'is this your brief?'."""
    MODEL_SAYS["raw"] = {"reply": f"model answer to: {text}", "intent": "other", "phase": "interview", "brief_check": "unsure"}
    body = _say(client, text, state={"brief_candidate": text, "brief_candidate_source": "message"}).json()
    assert body["reply"] == f"model answer to: {text}"
    assert body["brief_check"] == "na" and body["quick_replies"] == []


@pytest.mark.parametrize("text", ["xxx", "....", "qwrtp"])
def test_junk_brief_with_data_loaded_sends_the_pm_back_to_configure(text):
    """Negative: text that is not a brief, once data is loaded, asks to enter it again and opens the Configure page."""
    out = chat._normalise({"brief_check": "ok", "reply": "ok"}, {"brief_candidate": text, "brief_candidate_source": "brief"}, has_data=True)
    assert out["brief_check"] == "not_brief"
    assert "Configure" in out["reply"] and "again" in out["reply"]
    assert out["actions"] == [{"type": "navigate", "page": "upload"}]


def test_junk_brief_on_the_configure_page_stays_there():
    """Edge case: with no data loaded the PM is already on Configure, so no page change is asked for."""
    out = chat._normalise({}, {"brief_candidate": "xxx", "brief_candidate_source": "message"}, has_data=False)
    assert out["brief_check"] == "not_brief" and out["actions"] == []


def test_short_brief_is_asked_about_not_accepted():
    """Boundary: under 5 words is 'unsure': the PM is asked 'Is this your client brief?' with Yes / No buttons."""
    out = chat._normalise({"brief_check": "ok"}, {"brief_candidate": "reduce excursions please", "brief_candidate_source": "brief"}, has_data=True)
    assert out["brief_check"] == "unsure"
    assert out["reply"].startswith("Is this your client brief?")
    assert out["quick_replies"] == chat.BRIEF_CONFIRM_REPLIES


# ---------------------------------------------------------------- questions about the app are answered, not treated as a brief

@pytest.mark.parametrize("text", [
    "What should I do?",
    "what should i do now",
    "How does this app work",
    "What can you do",
    "How do I use this tool?",
    "Can you help me",
    "Explain the planner page",
    "who are you",
    "what next",
])
def test_app_questions_are_recognised(text):
    assert chat.is_app_question(text)


@pytest.mark.parametrize("text", [
    "Compare carriers by excursion rate for Acme last quarter",
    "We need to know which lanes have the most temperature excursions and why",
    "reduce manufacturing emissions",
])
def test_real_briefs_are_not_taken_for_app_questions(text):
    assert not chat.is_app_question(text)


def test_question_about_the_app_is_not_sent_to_the_brief_check():
    """Happy path: 'What should I do?' on the Configure page is answered (brief_check 'na'), not queried as a brief."""
    out = chat._normalise(
        {"reply": "Load your data, then press Load & continue.", "brief_check": "unsure"},
        {"brief_candidate": "What should I do?", "brief_candidate_source": "message"}, has_data=False,
    )
    assert out["brief_check"] == "na"
    assert out["reply"] == "Load your data, then press Load & continue."


def test_same_question_text_as_the_brief_itself_is_still_judged():
    """Edge case: only a typed MESSAGE is exempt; a stored brief text is always judged."""
    out = chat._normalise({"brief_check": "ok"}, {"brief_candidate": "What should I do?", "brief_candidate_source": "brief"}, has_data=True)
    assert out["brief_check"] == "unsure"


@pytest.mark.parametrize("text", [
    "thanks", "Thank you!", "thx", "ok", "okay", "cool", "hmm", "lol", "bye", "how are you", "How's it going?", "what's up",
    "Hi", "hello there", "good morning", "What should I do?", "how does this work",
])
def test_small_talk_is_recognised(text):
    assert chat.is_small_talk(text)


@pytest.mark.parametrize("text", [
    "Compare carriers by excursion rate for Acme last quarter",
    "reduce manufacturing emissions",
    "Show lanes with the most temperature excursions",
    "xxx",
    "write me a poem about the sea",
])
def test_briefs_and_non_briefs_are_not_small_talk(text):
    assert not chat.is_small_talk(text)


@pytest.mark.parametrize("text", ["thx", "hmm", "lol", "k"])
def test_small_talk_that_looks_like_junk_is_not_called_a_bad_brief(text):
    """'thx' has no vowel so the word rule calls it junk; as small talk it must reach the assistant instead."""
    out = chat._normalise({"reply": "You're welcome."}, {"brief_candidate": text, "brief_candidate_source": "message"}, has_data=False)
    assert out["brief_check"] == "na" and out["reply"] == "You're welcome."


def test_junk_that_is_not_small_talk_is_still_not_a_brief():
    out = chat._normalise({}, {"brief_candidate": "xxx", "brief_candidate_source": "message"}, has_data=False)
    assert out["brief_check"] == "not_brief"


def test_prompt_tells_the_assistant_to_explain_only_what_exists():
    """The assistant's instructions carry a guide of the real pages and forbid inventing features."""
    from app.prompts import chat_agent

    text = chat_agent.SYSTEM_PROMPT
    assert "EXPLAINING A FEATURE OR PART OF THE APP" in text and "Never invent a feature" in text
    for page in ("Configure page", "Planner page", "Audit page", "Features page", "Analysis page", "Report page"):
        assert page in text
