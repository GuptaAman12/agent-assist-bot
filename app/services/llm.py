import requests

from .. import config


class LLMError(Exception):
    pass


# UTF-8 bytes (E2 80 XX) decoded as Latin-1 produce these mojibake sequences.
_MOJIBAKE_FIXES = {
    "\u0393\u00c7\u00e6": "-",   # em dash
    "\u0393\u00c7\u201d": "-",   # em dash variant
    "\u0393\u00c7\u2019": "'",   # right single quote
    "\u0393\u00c7\u2018": "'",   # left single quote
    "\u0393\u00c7\u0153": "\u201c",  # left double quote
    "\u0393\u00c7\u00a9": "\u201d",  # right double quote
    "\u0393\u00c7\u00a6": "\u2026",  # ellipsis
}


def _normalize_text(text: str) -> str:
    for bad, good in _MOJIBAKE_FIXES.items():
        text = text.replace(bad, good)
    return text


def generate_response(context: str, query: str, history: list[dict] | None = None) -> str:
    messages = [
        {"role": "system", "content": (
            "You are a helpful support assistant. Base your answer ONLY on the provided context. "
            "If the context lacks the information for any part of the user's query, say you are not sure about that part. "
            "Use earlier turns in the conversation to resolve references like 'my order from earlier' or 'the issue I mentioned'. "
            "Answer concisely in plain prose or short numbered steps. "
            "Do not use markdown tables, headings, or code blocks; responses may be spoken aloud. "
            "Use **bold** sparingly for key actions."
        )},
    ]
    for turn in (history or [])[-config.MAX_HISTORY_TURNS:]:
        if turn.get("transcript"):
            messages.append({"role": "user", "content": turn["transcript"]})
        if turn.get("response"):
            messages.append({"role": "assistant", "content": turn["response"]})
    messages.append({"role": "user", "content": f"Context:\n{context}\n\nQuery: {query}"})

    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.GROQ_MODEL,
        "messages": messages,
    }
    try:
        res = requests.post(
            config.GROQ_CHAT_URL,
            headers=headers,
            json=payload,
            timeout=config.REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise LLMError(f"Could not reach Groq API: {exc}") from exc

    if res.status_code >= 400:
        raise LLMError(f"Groq API error {res.status_code}: {res.text[:300]}")

    try:
        content = res.json()["choices"][0]["message"]["content"]
        return _normalize_text(content.strip())
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected Groq response shape: {res.text[:300]}") from exc
