import pytest
import requests

from app.services import llm
from app.services.llm import LLMError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (payload and str(payload)) or ""

    def json(self):
        if self.status_code >= 400:
            raise ValueError("not json")
        return self._payload


def test_success(monkeypatch):
    payload = {"choices": [{"message": {"content": "  hello world  "}}]}
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: FakeResponse(200, payload))
    assert llm.generate_response("ctx", "query") == "hello world"


def test_http_error(monkeypatch):
    monkeypatch.setattr(llm.requests, "post",
                        lambda *a, **k: FakeResponse(429, text="rate limited"))
    with pytest.raises(LLMError, match="429"):
        llm.generate_response("ctx", "query")


def test_network_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(llm.requests, "post", boom)
    with pytest.raises(LLMError):
        llm.generate_response("ctx", "query")


def test_malformed_response(monkeypatch):
    monkeypatch.setattr(llm.requests, "post",
                        lambda *a, **k: FakeResponse(200, {"unexpected": True}))
    with pytest.raises(LLMError):
        llm.generate_response("ctx", "query")


def test_mojibake_normalized(monkeypatch):
    em_dash_mangled = "\u0393\u00c7\u00e6"
    payload = {"choices": [{"message": {"content": f"go {em_dash_mangled} stop"}}]}
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: FakeResponse(200, payload))
    out = llm.generate_response("ctx", "query")
    assert em_dash_mangled not in out
    assert "go - stop" == out
