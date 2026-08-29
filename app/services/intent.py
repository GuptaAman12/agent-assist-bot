from .. import config


def detect_intent(transcript: str) -> str:
    text = transcript.lower()
    for intent, keywords in config.INTENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return intent
    return config.UNKNOWN_INTENT


def detect_intents(transcript: str) -> list[str]:
    """Return every intent whose keyword appears in the transcript."""
    text = transcript.lower()
    return [
        intent
        for intent, keywords in config.INTENT_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
