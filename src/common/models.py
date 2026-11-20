"""The graph schema, as code. These dataclasses are the contract between stages:
each stage writes these to artifacts/, and the graph loader (Stage 5) turns them
into Neo4j nodes/edges. Keeping the schema here (not only in Cypher) means the
three layers agree on field names before anything touches the database.

Layers:  Requirements (intent) · UI (built) · Code (how)
Absence is a first-class Gap node, never a missing edge (see CONTEXT.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

Coverage = Literal["verified", "partial", "absent", "ambiguous"]


# ---------- Requirements layer ----------
@dataclass
class Requirement:
    id: str
    title: str
    description: str
    acceptance: list[str] = field(default_factory=list)
    type: str = "functional"            # functional | non_functional | infra
    source: str = ""                    # where in the docs it came from
    coverage: Coverage = "ambiguous"    # computed by the linker


# ---------- UI layer ----------
@dataclass
class Screen:
    id: str
    url: str
    title: str
    screenshot: str = ""                # relative path into artifacts/


@dataclass
class UIElement:
    id: str
    screen_id: str
    role: str                           # button | input | menuitem | dialog | ...
    label: str                          # visible/accessible label
    selector: str                       # stable selector used by the crawler
    text: str = ""


@dataclass
class UIFlow:
    """A discovered user path (ordered UIElements across screens)."""
    id: str
    name: str
    steps: list[str] = field(default_factory=list)   # UIElement ids, in order


# ---------- Code layer ----------
@dataclass
class CodeSymbol:
    id: str                             # f"{path}::{name}"
    kind: str                           # file | component | function | action
    name: str
    path: str
    repo: str
    start_line: int = 0
    end_line: int = 0


# ---------- Cross-layer edges (carry confidence + evidence) ----------
@dataclass
class Edge:
    src: str                            # node id
    dst: str                            # node id
    rel: str                            # IMPLEMENTED_BY | VERIFIED_BY | DEPENDS_ON | ...
    confidence: float = 1.0
    evidence: str = ""                  # what matched: exact-testid | embed:0.82 | llm-vote


# ---------- Absence ----------
@dataclass
class Gap:
    """Records that we searched the captured UI for a requirement and found nothing
    above threshold. A positive, auditable assertion — not an inferred silence."""
    id: str
    requirement_id: str
    reason: str                         # e.g. "no UI element above review threshold"
    best_candidate: str = ""            # closest UIElement id we considered
    best_score: float = 0.0


def to_jsonable(obj) -> dict:
    return asdict(obj)
