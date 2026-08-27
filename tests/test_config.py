import json

import pytest

from app import config


@pytest.fixture
def isolated_kb_path(monkeypatch, tmp_path):
    p = tmp_path / "kb.json"
    monkeypatch.setattr(config, "KNOWLEDGE_BASE_PATH", p)
    return p


def test_load_knowledge_base_ok(isolated_kb_path):
    isolated_kb_path.write_text(
        json.dumps([{"question": "a", "response": "b"}]), encoding="utf-8"
    )
    assert config.load_knowledge_base() == [{"question": "a", "response": "b"}]


def test_load_knowledge_base_tolerates_bom(isolated_kb_path):
    isolated_kb_path.write_bytes(
        b"\xef\xbb\xbf" + json.dumps([{"response": "x"}]).encode("utf-8")
    )
    assert config.load_knowledge_base() == [{"response": "x"}]


def test_load_knowledge_base_rejects_non_list(isolated_kb_path):
    isolated_kb_path.write_text('{"response": "x"}', encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_knowledge_base()


def test_load_knowledge_base_rejects_missing_response(isolated_kb_path):
    isolated_kb_path.write_text('[{"question": "no response here"}]', encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_knowledge_base()


def test_missing_api_keys_reports_all(monkeypatch):
    monkeypatch.setattr(config, "ASSEMBLYAI_API_KEY", "")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    assert config.missing_api_keys() == ["ASSEMBLYAI_API_KEY", "GROQ_API_KEY"]
