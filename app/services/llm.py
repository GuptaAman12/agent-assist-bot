import requests

from .. import config


class LLMError(Exception):
    pass


def generate_response(context: str, query: str) -> str:
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": (
                "You are a helpful support assistant. Base your answer ONLY on the provided context. "
                "If the context lacks the information for any part of the user's query, say you are not sure about that part. "
                "Answer concisely in plain prose or short numbered steps. "
                "Do not use markdown tables, headings, or code blocks; responses may be spoken aloud. "
                "Use **bold** sparingly for key actions."
            )},
            {"role": "user", "content": f"Context:\n{context}\n\nQuery: {query}"},
        ],
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
        return res.json()["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected Groq response shape: {res.text[:300]}") from exc
