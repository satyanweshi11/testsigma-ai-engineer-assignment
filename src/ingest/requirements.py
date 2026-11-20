"""Stage 2 — Requirements layer.

Turns public docs (README + docs site) into atomic, *testable* requirements.
This is a genuine LLM job: prose → discrete requirements with acceptance criteria
and a type (functional / non_functional / infra). The type matters for absence:
a non_functional requirement like "end-to-end encrypted" legitimately has no single
UI element, and we want the linker to treat that differently from a functional one
that *should* appear in the UI but doesn't.

Deterministic: fetch + collect doc text. LLM: the extraction only.
"""
from __future__ import annotations

import json
from dataclasses import asdict

import httpx
from bs4 import BeautifulSoup

from src.config import Settings
from src.llm import get_client
from src.codemap.mapper import REPOS_DIR

_SYSTEM = """You are a QA analyst extracting testable product requirements from documentation.
Return requirements that describe WHAT THE PRODUCT DOES for a user or as a system property.
Each must be atomic (one capability), and testable (a QA engineer could write a check for it).
Classify type as:
  - functional: a user-facing capability that should be reachable in the UI
  - non_functional: a property (security, performance, offline, i18n) with no single UI control
  - infra: build/deploy/platform concerns
Prefer 15-25 high-signal requirements. Do not invent features not supported by the text."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "acceptance": {"type": "array", "items": {"type": "string"}},
                    "type": {"type": "string", "enum": ["functional", "non_functional", "infra"]},
                },
                "required": ["title", "description", "type"],
            },
        }
    },
    "required": ["requirements"],
}


def _collect_docs(settings: Settings) -> list[tuple[str, str]]:
    """Return list of (source_label, text)."""
    out: list[tuple[str, str]] = []
    for src in settings.cfg["docs"]["sources"]:
        if src["type"] == "github_readme":
            repo = src["repo"]
            readme = REPOS_DIR / repo.replace("/", "__") / "README.md"
            if readme.exists():
                out.append((f"{repo}/README.md", readme.read_text(encoding="utf-8", errors="ignore")))
            else:
                print(f"  ! README not found at {readme} (run codemap first to clone)")
        elif src["type"] == "url":
            try:
                html = httpx.get(src["url"], timeout=20, follow_redirects=True).text
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
                out.append((src["url"], text[:12000]))
            except Exception as e:
                print(f"  ! could not fetch {src['url']}: {e}")
    return out


def run(settings: Settings) -> None:
    docs = _collect_docs(settings)
    if not docs:
        raise SystemExit("No docs collected. Check config/target.yaml docs.sources.")
    corpus = "\n\n".join(f"### SOURCE: {label}\n{text}" for label, text in docs)
    print(f"  collected {len(docs)} doc source(s), {len(corpus)} chars")

    client = get_client()
    res = client.complete_json(_SYSTEM, f"Documentation:\n\n{corpus}", schema=_SCHEMA)
    raw = res.data.get("requirements", []) if isinstance(res.data, dict) else []

    requirements = []
    for i, r in enumerate(raw, 1):
        requirements.append({
            "id": f"REQ-{i:03d}",
            "title": r.get("title", "").strip(),
            "description": r.get("description", "").strip(),
            "acceptance": r.get("acceptance", []),
            "type": r.get("type", "functional"),
            "source": docs[0][0],
            "coverage": "ambiguous",   # set by the linker
        })

    out = settings.artifacts_dir / "requirements.json"
    out.write_text(json.dumps({"requirements": requirements}, indent=2))
    by_type = {}
    for r in requirements:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    print(f"✓ ingest: {len(requirements)} requirements {by_type} -> {out}")


if __name__ == "__main__":
    from src import config
    run(config.load())
