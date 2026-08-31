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


def test_history_included_in_messages(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["messages"] = kwargs["json"]["messages"]
        return FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm.generate_response(
        "ctx",
        "what about my order?",
        history=[
            {"transcript": "cancel my order", "response": "Go to order history."},
            {"transcript": "where is it?", "response": "Shipped."},
        ],
    )
    roles = [m["role"] for m in seen["messages"]]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]
    assert seen["messages"][1]["content"] == "cancel my order"
    assert seen["messages"][2]["content"] == "Go to order history."
    assert "what about my order?" in seen["messages"][-1]["content"]


def test_history_capped(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["messages"] = kwargs["json"]["messages"]
        return FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    long_history = [{"transcript": f"q{i}", "response": f"r{i}"} for i in range(20)]
    llm.generate_response("ctx", "q", history=long_history)
    # system + 2*cap history + final user message
    assert len(seen["messages"]) == 1 + 2 * llm.config.MAX_HISTORY_TURNS + 1
