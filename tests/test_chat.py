"""Unit tests for the chat agent and web endpoints (no Neo4j / LLM needed).

The graph session and the LLM are faked, so these run in CI offline. They cover the
deterministic term extraction and the request/response contract of the API."""
from fastapi.testclient import TestClient

from src.chat import agent, server


def test_terms_extraction_drops_stopwords():
    t = agent._terms("What implements the Rectangle tool?")
    assert "rectangle" in t and "implements" in t
    assert "the" not in t and "what" not in t and "tool" in t


def test_terms_ignores_short_and_punctuation():
    assert agent._terms("Is it a UI?") == []        # all stopwords / too short


class _FakeResult:
    def single(self):
        return {"n": 123}


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, *a, **k):
        return _FakeResult()


class _FakeDriver:
    def session(self):
        return _FakeSession()


def _patch(monkeypatch):
    monkeypatch.setitem(server._state, "driver", _FakeDriver())
    monkeypatch.setitem(server._state, "llm", object())
    monkeypatch.setattr(server, "_init", lambda: server._state)
    monkeypatch.setattr(server, "retrieve", lambda se, q: "- grounded fact")
    monkeypatch.setattr(server, "answer", lambda llm, q, ctx: "grounded answer about " + q)


def test_health_reports_node_count(monkeypatch):
    _patch(monkeypatch)
    r = TestClient(server.app).get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True, "nodes": 123}


def test_chat_returns_grounded_answer(monkeypatch):
    _patch(monkeypatch)
    r = TestClient(server.app).post("/api/chat", json={"question": "what is X"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].startswith("grounded answer")
    assert body["context"] == "- grounded fact"


def test_chat_rejects_empty_question(monkeypatch):
    _patch(monkeypatch)
    r = TestClient(server.app).post("/api/chat", json={"question": "   "})
    assert r.status_code == 400


def test_index_served():
    assert "<html" in TestClient(server.app).get("/").text.lower()
