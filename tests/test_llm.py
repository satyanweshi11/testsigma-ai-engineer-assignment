"""Unit tests for the LLM layer (no network)."""
import os

import pytest

from src.llm.base import cosine
from src.llm.factory import get_client


def test_cosine_identical():
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_factory_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError):
        get_client()


def test_gemini_requires_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from src.llm.gemini import GeminiClient
    with pytest.raises(RuntimeError):
        GeminiClient()
