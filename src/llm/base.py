"""The one interface every LLM-touching stage depends on.

Design intent (Part B — the deterministic/LLM boundary): the system never calls a
provider SDK directly. It calls these two methods. That keeps LLM usage auditable
(every call can be logged here), bounded, and swappable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResult:
    """A structured LLM response plus the metadata we need for confidence + eval."""
    data: Any                       # parsed JSON (dict/list) when a schema was requested, else str
    raw: str                        # raw text returned
    model: str
    usage: dict = field(default_factory=dict)


class LLMClient(ABC):
    """Two capabilities, nothing more: structured completion and embeddings."""

    @abstractmethod
    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        """Return parsed JSON. `schema` is a JSON-schema-ish dict the provider enforces.
        temperature defaults to 0.0 so reasoning stages are as reproducible as the
        provider allows (see eval approach)."""
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input string. Used by the linker (Stage 4)
        for similarity before any LLM adjudication is spent."""
        ...


def cosine(a: list[float], b: list[float]) -> float:
    """Pure-python cosine similarity — no numpy dependency (keeps install clean)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
