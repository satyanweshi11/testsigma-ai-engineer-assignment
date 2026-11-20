"""Picks the provider from env. One place to add Groq/Ollama later."""
from __future__ import annotations

import os

from .base import LLMClient


def get_client() -> LLMClient:
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if provider == "gemini":
        from .gemini import GeminiClient
        return GeminiClient()
    # Future: "groq", "ollama", "openai" — each a small LLMClient subclass.
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")
