import re

from .. import config


def _compile(keyword: str) -> "re.Pattern[str]":
    # Left word boundary only: "crash" still matches "crashing"/"crashed"
    # (verb forms users actually say) but "locked" no longer matches
    # "unlocked" and "balance" no longer matches "rebalance".
    parts = [re.escape(piece) for piece in keyword.split()]
    return re.compile(r"\b" + r"\s+".join(parts), re.IGNORECASE)


_PATTERNS: dict[str, list["re.Pattern[str]"]] = {
    intent: [_compile(keyword) for keyword in keywords]
    for intent, keywords in config.INTENT_KEYWORDS.items()
}


def detect_intent(transcript: str) -> str:
    matches = detect_intents(transcript)
    return matches[0] if matches else config.UNKNOWN_INTENT


def detect_intents(transcript: str) -> list[str]:
    """Return every intent whose keyword appears in the transcript."""
    return [
        intent
        for intent, patterns in _PATTERNS.items()
        if any(pattern.search(transcript) for pattern in patterns)
    ]
