from pydantic import BaseModel

class AssistRequest(BaseModel):
    transcript: str
    intent: str
    history: list[dict] = []
    voice: str | None = None

class KBEntryRequest(BaseModel):
    question: str = ""
    response: str

class FeedbackRequest(BaseModel):
    transcript: str
    positive: bool
    assist_request_id: str | None = None

