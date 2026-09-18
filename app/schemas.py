from pydantic import BaseModel

class AssistRequest(BaseModel):
    transcript: str
    intent: str
    history: list[dict] = []
    voice: str | None = None

class KBEntryRequest(BaseModel):
    question: str = ""
    response: str
