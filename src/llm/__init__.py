"""Swappable LLM layer. The rest of the system talks only to `LLMClient`,
so the provider (Gemini today, Groq/Ollama tomorrow) is one line to change."""
from .base import LLMClient, LLMResult
from .factory import get_client

__all__ = ["LLMClient", "LLMResult", "get_client"]
