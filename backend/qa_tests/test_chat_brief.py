"""Greeting reply and "that is not a brief" handling of the chat (routers/chat.py).

The model is never called in the greeting tests: if it were, the test would fail, because _ask_model is made to blow up.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import chat, deps


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(deps, "AUTH_ENABLED", False)
    monkeypatch.setattr(deps, "USE_AWS_STORAGE", False)

    def no_model(*a, **k):
        raise AssertionError("the model must not be called for a greeting")

    monkeypatch.setattr(chat, "_ask_model", no_model)
    return TestClient(app, raise_server_exceptions=False)


def _say(client, text, brief="", state=None, hidden=False):
    body = {"brief": brief, "messages": [{"role": "user", "content": text}], "state": state or {}, "hidden": hidden}
    return client.post("/api/chat/turn", json=body)


@pytest.mark.parametrize("text", ["Hi", "hi", "HI!", "Hello", "hello.", "Hey there", "good morning", "Hi Polar", "hiii", "  hello  "])
def test_greeting_gets_hi_and_asks_for_the_brief(client, text):
    """Happy path: a bare greeting is answered with a greeting that asks for the client brief."""
    r = _say(client, text)
    assert r.status_code == 200
    body = r.json()
    assert body["reply"].startswith("Hi!")
    assert "client brief" in body["reply"]
    assert body["actions"] == [] and body["brief_check"] == "na"


@pytest.mark.parametrize("text", [
    "Hi, compare carriers by excursion rate for all shipments last quarter",
    "hello world",
    "Hi what can you do?",
    "high",
    "compare carriers by excursion rate",
])
def test_more_than_a_greeting_is_not_short_circuited(monkeypatch, text):
    """Negative: only a bare greeting is intercepted; anything else still goes to the model."""
    assert chat._greeting_response(chat.ChatTurnRequest(messages=[chat.ChatMessage(role="user", content=text)])) is None


def test_greeting_with_a_brief_already_set_goes_to_the_model():
    """Edge case: once a brief exists the greeting is a normal chat message (the brief stays; no 'enter your brief')."""
    req = chat.ChatTurnRequest(brief="Compare carriers by excursion rate for Acme", messages=[chat.ChatMessage(role="user", content="Hi")])
    assert chat._greeting_response(req) is None


def test_greeting_after_the_interview_started_goes_to_the_model():
    """Edge case: in the build/refine phases the greeting is not a request for the brief."""
    req = chat.ChatTurnRequest(state={"phase": "refine"}, messages=[chat.ChatMessage(role="user", content="Hi")])
    assert chat._greeting_response(req) is None


def test_hidden_app_prompt_is_never_a_greeting():
    """Edge case: the app's own hidden turn that starts the interview is not answered as a greeting."""
    req = chat.ChatTurnRequest(hidden=True, messages=[chat.ChatMessage(role="user", content="Hi")])
    assert chat._greeting_response(req) is None


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
