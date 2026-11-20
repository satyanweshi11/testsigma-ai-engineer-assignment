"""Stage 5 — Load the fused graph into Neo4j.

Reads the artifacts from stages 1-4 and MERGEs them into Neo4j. Idempotent: run it
as many times as you like, the graph converges to the same state (MERGE on id).
This is pure plumbing — no LLM, no heuristics — so the graph is a faithful, auditable
projection of the artifacts on disk.
"""
from __future__ import annotations

import json

from neo4j import GraphDatabase

from src.config import Settings

CONSTRAINTS = [
    "CREATE CONSTRAINT req_id IF NOT EXISTS FOR (n:Requirement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT screen_id IF NOT EXISTS FOR (n:Screen) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT uiel_id IF NOT EXISTS FOR (n:UIElement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT code_id IF NOT EXISTS FOR (n:CodeSymbol) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT gap_id IF NOT EXISTS FOR (n:Gap) REQUIRE n.id IS UNIQUE",
]


def _load(tx, ui, code, reqs, edges):
    # ---- nodes ----
    tx.run("""UNWIND $rows AS r
              MERGE (n:Requirement {id:r.id})
              SET n += {title:r.title, description:r.description, type:r.type,
                        acceptance:r.acceptance, coverage:r.coverage, source:r.source}""",
           rows=reqs)
    tx.run("""UNWIND $rows AS s
              MERGE (n:Screen {id:s.id}) SET n += {url:s.url, title:s.title, screenshot:s.screenshot}""",
           rows=ui["screens"])
    tx.run("""UNWIND $rows AS e
              MERGE (n:UIElement {id:e.id})
              SET n += {screen_id:e.screen_id, role:e.role, label:e.label,
                        selector:e.selector, text:e.text}""",
           rows=ui["elements"])
    tx.run("""UNWIND $rows AS s
              MERGE (n:CodeSymbol {id:s.id})
              SET n += {kind:s.kind, name:s.name, path:s.path, repo:s.repo,
                        start_line:s.start_line, end_line:s.end_line}""",
           rows=code["symbols"])
    tx.run("""UNWIND $rows AS g
              MERGE (n:Gap {id:g.id})
              SET n += {reason:g.reason, best_candidate:g.best_candidate, best_score:g.best_score}""",
           rows=edges["gaps"])

    # ---- structural edges ----
    tx.run("""UNWIND $rows AS e
              MATCH (s:Screen {id:e.screen_id}), (u:UIElement {id:e.id})
              MERGE (s)-[:CONTAINS]->(u)""", rows=ui["elements"])
    tx.run("""UNWIND $rows AS t
              MATCH (s:Screen {id:t.dst})
              SET s.reached_by = t.evidence""", rows=ui["transitions"])

    # ---- code dependency edges (file -> file) ----
    tx.run("""UNWIND $rows AS e
              MATCH (a:CodeSymbol {id:e.src}), (b:CodeSymbol {id:e.dst})
              MERGE (a)-[:DEPENDS_ON]->(b)""", rows=code["edges"])

    # ---- cross-layer edges (carry confidence + evidence) ----
    impl = [e for e in edges["edges"] if e["rel"] == "IMPLEMENTED_BY"]
    ver = [e for e in edges["edges"] if e["rel"] == "VERIFIED_BY"]
    tx.run("""UNWIND $rows AS e
              MATCH (u:UIElement {id:e.src}), (c:CodeSymbol {id:e.dst})
              MERGE (u)-[r:IMPLEMENTED_BY]->(c)
              SET r.confidence=e.confidence, r.evidence=e.evidence""", rows=impl)
    tx.run("""UNWIND $rows AS e
              MATCH (q:Requirement {id:e.src}), (u:UIElement {id:e.dst})
              MERGE (q)-[r:VERIFIED_BY]->(u)
              SET r.confidence=e.confidence, r.evidence=e.evidence""", rows=ver)
    tx.run("""UNWIND $rows AS g
              MATCH (q:Requirement {id:g.requirement_id}), (n:Gap {id:g.id})
              MERGE (q)-[:HAS_GAP]->(n)""", rows=edges["gaps"])


def run(settings: Settings) -> None:
    adir = settings.artifacts_dir
    ui = json.loads((adir / "ui.json").read_text())
    code = json.loads((adir / "code.json").read_text())
    reqs = json.loads((adir / "requirements.json").read_text())["requirements"]
    edges = json.loads((adir / "edges.json").read_text())

    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    with driver.session() as sess:
        # The graph must mirror the current artifacts exactly. Requirement/element ids can
        # shift between runs (the LLM may extract a different requirement set), so MERGE
        # alone would leave orphans — reset first for a reproducible, faithful projection.
        sess.run("MATCH (n) DETACH DELETE n")
        for c in CONSTRAINTS:
            sess.run(c)
        sess.execute_write(_load, ui, code, reqs, edges)
        counts = sess.run("""
            CALL () { MATCH (n:Requirement) RETURN count(n) AS req }
            CALL () { MATCH (n:UIElement) RETURN count(n) AS ui }
            CALL () { MATCH (n:CodeSymbol) RETURN count(n) AS code }
            CALL () { MATCH (n:Gap) RETURN count(n) AS gap }
            CALL () { MATCH ()-[r:IMPLEMENTED_BY]->() RETURN count(r) AS impl }
            CALL () { MATCH ()-[r:VERIFIED_BY]->() RETURN count(r) AS ver }
            RETURN req, ui, code, gap, impl, ver""").single()
    driver.close()
    print(f"✓ load: Neo4j populated — {counts['req']} requirements, {counts['ui']} UI "
          f"elements, {counts['code']} code symbols, {counts['gap']} gaps, "
          f"{counts['impl']} IMPLEMENTED_BY, {counts['ver']} VERIFIED_BY")
    print(f"        browse: http://localhost:7474  (neo4j / {settings.neo4j_password})")


if __name__ == "__main__":
    from src import config
    run(config.load())
