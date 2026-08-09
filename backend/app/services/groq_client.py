"""Thin wrapper around the Groq chat-completions API."""
from groq import Groq

from app.config import GROQ_API_KEY, GROQ_MODEL

_client: Groq | None = None


def get_client() -> Groq:
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Paste your key from "
                "https://console.groq.com/keys into backend/.env"
            )
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def chat_text(system_prompt: str, user_prompt: str, model: str = GROQ_MODEL, temperature: float = 0.3) -> str:
    """Single-shot call returning plain prose."""
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or ""
