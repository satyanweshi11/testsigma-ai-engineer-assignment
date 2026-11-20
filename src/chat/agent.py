"""Graph-grounded chat about the components.

A question goes through two steps:
  1. retrieve() — deterministic, read-only Cypher pulls the relevant subgraph
     (UI elements, code components, requirements and their cross-layer links,
     with confidence and coverage) by keyword, plus a graph summary as fallback.
  2. answer() — the LLM answers using ONLY that retrieved context, so every
     reply is grounded in the graph rather than the model's imagination.

This is intentionally retrieval-then-generate, not free-form text-to-Cypher:
the queries are parameterized and read-only, so the chat cannot mutate the graph
or run arbitrary Cypher.
"""
from __future__ import annotations

import re

_STOP = {"what", "which", "the", "is", "are", "does", "do", "a", "an", "of", "to", "in",
         "on", "for", "how", "show", "me", "list", "tell", "about", "with", "and", "or",
         "component", "components", "ui", "code", "that", "this", "it", "its", "has",
         "have", "can", "will", "would", "where", "when", "why", "who", "whom", "there",
         "any", "all", "give", "get", "find", "whats", "im", "i"}


def _terms(question: str) -> list[str]:
    words = re.split(r"[^a-z0-9]+", question.lower())
    return [w for w in words if w and w not in _STOP and len(w) > 2]


def retrieve(session, question: str, limit: int = 20) -> str:
    """Return a compact, grounded context block of facts from the graph."""
    terms = _terms(question)
    facts: list[str] = []

    if terms:
        # UI elements matched by label -> their code and requirements
        for row in session.run("""
            UNWIND $terms AS t
            MATCH (u:UIElement) WHERE toLower(u.label) CONTAINS t
            WITH DISTINCT u LIMIT $limit
            OPTIONAL MATCH (u)-[im:IMPLEMENTED_BY]->(c:CodeSymbol)
            OPTIONAL MATCH (u)<-[:VERIFIED_BY]-(r:Requirement)
            RETURN u.label AS label, u.role AS role,
                   collect(DISTINCT c.name + ' (' + c.path + ', conf ' + toString(im.confidence) + ')') AS impls,
                   collect(DISTINCT r.id + ' ' + r.title) AS reqs
        """, terms=terms, limit=limit).data():
            line = f"UI element '{row['label']}' (role {row['role']})"
            impls = [x for x in row["impls"] if x and "null" not in x]
            if impls:
                line += f" is implemented by: {', '.join(impls)}"
            reqs = [x for x in row["reqs"] if x and x.strip()]
            if reqs:
                line += f"; verifies requirements: {', '.join(reqs)}"
            facts.append(line + ".")

        # Code components matched by name -> which UI they implement
        for row in session.run("""
            UNWIND $terms AS t
            MATCH (c:CodeSymbol) WHERE toLower(c.name) CONTAINS t AND c.kind IN ['component','action','function']
            WITH DISTINCT c LIMIT $limit
            OPTIONAL MATCH (c)<-[im:IMPLEMENTED_BY]-(u:UIElement)
            RETURN c.name AS name, c.path AS path, c.kind AS kind,
                   collect(DISTINCT u.label + ' (conf ' + toString(im.confidence) + ')') AS uis
        """, terms=terms, limit=limit).data():
            line = f"Code {row['kind']} '{row['name']}' ({row['path']})"
            uis = [x for x in row["uis"] if x and "null" not in x]
            if uis:
                line += f" implements UI: {', '.join(uis)}"
            facts.append(line + ".")

        # Requirements matched by title/description -> coverage, verifying UI, gaps
        for row in session.run("""
            UNWIND $terms AS t
            MATCH (r:Requirement) WHERE toLower(r.title) CONTAINS t OR toLower(r.description) CONTAINS t
            WITH DISTINCT r LIMIT $limit
            OPTIONAL MATCH (r)-[:VERIFIED_BY]->(u:UIElement)
            OPTIONAL MATCH (r)-[:HAS_GAP]->(g:Gap)
            RETURN r.id AS id, r.title AS title, r.type AS type, r.coverage AS coverage,
                   collect(DISTINCT u.label) AS verified_by, collect(DISTINCT g.reason) AS gaps
        """, terms=terms, limit=limit).data():
            line = f"Requirement {row['id']} '{row['title']}' (type {row['type']}, coverage {row['coverage']})"
            vb = [x for x in row["verified_by"] if x]
            if vb:
                line += f"; verified by UI: {', '.join(vb)}"
            gaps = [x for x in row["gaps"] if x]
            if gaps:
                line += f"; gap: {gaps[0]}"
            facts.append(line + ".")

    # intent: coverage / absence questions -> include all gaps
    if any(w in question.lower() for w in ("gap", "absent", "missing", "coverage", "not tested", "no ui")):
        for row in session.run("""
            MATCH (r:Requirement)-[:HAS_GAP]->(g:Gap)
            RETURN r.id AS id, r.title AS title, r.type AS type, g.reason AS reason
        """).data():
            facts.append(f"ABSENCE: Requirement {row['id']} '{row['title']}' (type {row['type']}) "
                         f"has no verifying UI. Reason: {row['reason']}.")

    if not facts:
        # fallback: a summary of the graph so general questions still get grounded answers
        s = session.run("""
            CALL () { MATCH (r:Requirement) RETURN count(r) AS reqs }
            CALL () { MATCH (u:UIElement) RETURN count(u) AS ui }
            CALL () { MATCH (c:CodeSymbol) RETURN count(c) AS code }
            CALL () { MATCH (:Requirement)-[:HAS_GAP]->() RETURN count(*) AS gaps }
            RETURN reqs, ui, code, gaps
        """).single()
        facts.append(f"Graph summary: {s['reqs']} requirements, {s['ui']} UI elements, "
                     f"{s['code']} code symbols, {s['gaps']} coverage gaps.")
        sample = session.run("MATCH (c:CodeSymbol {kind:'component'}) RETURN c.name AS n LIMIT 15").data()
        facts.append("Example components: " + ", ".join(r["n"] for r in sample) + ".")

    return "\n".join(f"- {f}" for f in facts[:60])


_SYSTEM = """You are the Blast Radius assistant. You answer questions about a web
application's components using ONLY the knowledge-graph context provided with the
question. The graph connects three layers: Requirements (product intent), UI elements
(what was built), and Code symbols (components/functions that implement the UI), with a
confidence on each cross-layer link, and explicit coverage gaps for requirements with no UI.

Rules:
- Use only the provided context. If it does not contain the answer, say so plainly and
  suggest what to ask instead. Never invent component names, requirements, or links.
- Cite concrete names (UI label, code component, requirement id) and the confidence when relevant.
- When something is a coverage gap / absent, say so clearly.
- Be concise and readable for a QA lead. Prefer short paragraphs or tight bullet lists."""


def answer(client, question: str, context: str) -> str:
    res = client.complete_json(
        _SYSTEM,
        f"Question: {question}\n\nKnowledge-graph context:\n{context}\n\n"
        'Respond as JSON: {"answer": "<markdown answer>"}',
        schema={"type": "object", "properties": {"answer": {"type": "string"}},
                "required": ["answer"]})
    if isinstance(res.data, dict):
        return res.data.get("answer", "").strip() or "I could not find that in the graph."
    return str(res.data)
