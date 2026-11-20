"""Gemini implementation of LLMClient (free tier).

Uses the google-genai SDK. JSON mode is enforced via response_mime_type so the
mapping adjudicator and PRD parser get machine-parseable output. Rate-limit and
transient errors are retried with backoff (free tier is ~15 req/min)."""
from __future__ import annotations

import json
import os

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .base import LLMClient, LLMResult


class GeminiClient(LLMClient):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        embed_model: str | None = None,
    ):
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key or api_key == "your_key_here":
            raise RuntimeError(
                "GEMINI_API_KEY not set. Put a free key from "
                "https://aistudio.google.com/apikey into .env"
            )
        # Imported lazily so the package imports even before google-genai is installed.
        from google import genai  # type: ignore

        self._genai = genai
        self.client = genai.Client(api_key=api_key)
        self.model = model or os.environ.get("LLM_MODEL", "gemini-3.5-flash")
        self.embed_model = embed_model or os.environ.get("EMBED_MODEL", "gemini-embedding-001")

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def complete_json(self, system, user, schema=None, temperature=0.0) -> LLMResult:
        from google.genai import types  # type: ignore

        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
        )
        if schema is not None:
            cfg.response_schema = schema

        resp = self.client.models.generate_content(
            model=self.model, contents=user, config=cfg
        )
        text = resp.text or "{}"
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Last-resort salvage: grab the outermost JSON object/array.
            data = _loose_json(text)
        return LLMResult(data=data, raw=text, model=self.model)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.models.embed_content(model=self.embed_model, contents=texts)
        return [list(e.values) for e in resp.embeddings]


def _loose_json(text: str):
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1),
        default=-1,
    )
    end = max(text.rfind("}"), text.rfind("]"))
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}
