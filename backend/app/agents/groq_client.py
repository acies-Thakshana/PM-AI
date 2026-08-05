"""Thin wrapper around the Groq chat-completions API. Both agents share this
so the retry/JSON-mode/tool-calling plumbing exists in exactly one place."""
import json

from groq import Groq

from app.config import GROQ_API_KEY, GROQ_MODEL

_client = None


def get_client() -> Groq:
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy backend/.env.example to backend/.env "
                "and add your key from https://console.groq.com/keys"
            )
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def chat_json(system_prompt: str, user_prompt: str, model: str = GROQ_MODEL, temperature: float = 0.3) -> dict:
    """Single-shot call constrained to return a JSON object."""
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return json.loads(response.choices[0].message.content)


def chat_with_tools(system_prompt: str, user_prompt: str, tools: list[dict], tool_executor,
                     model: str = GROQ_MODEL, temperature: float = 0.2, max_turns: int = 20):
    """Runs a tool-calling loop: the model may call any of `tools` any number
    of times; `tool_executor(name, args) -> result_dict` actually performs the
    action. Returns the list of (tool_name, args, result) calls that were made
    once the model stops calling tools."""
    client = get_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    calls_made = []

    for _ in range(max_turns):
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        if not tool_calls:
            break

        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [tc.model_dump() for tc in tool_calls],
        })

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            result = tool_executor(name, args)
            calls_made.append((name, args, result))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    return calls_made
