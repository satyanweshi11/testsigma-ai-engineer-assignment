"""Stage 6 — Reason: blast radius.

Given a real PR, answer three questions a QA lead actually asks:
  1. Which UI is at risk?
  2. Which discovered user flows / screens are affected?
  3. Which requirements might lose coverage?

Everything up to the write-up is deterministic graph work:
  PR diff (GitHub)  →  changed files  →  changed CodeSymbols
     →  (reverse IMPLEMENTED_BY)  impacted UIElements
     →  (reverse VERIFIED_BY)     impacted Requirements
     →  (+ DEPENDS_ON expansion for indirectly affected code)
  path confidence = product of edge confidences along the way (× hop decay).

Only the final human-readable narrative is LLM-written, from the structured impact
set — so the facts are auditable and the model only does prose.
"""
from __future__ import annotations

import json
import os
import subprocess

import httpx
from neo4j import GraphDatabase

from src.config import Settings
from src.llm import get_client


# ---------- GitHub ----------
def _gh_token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        return out.stdout.strip() or None
    except Exception:
        return None


def _fetch_pr(repo: str, number: int) -> tuple[dict, list[str]]:
    headers = {"Accept": "application/vnd.github+json"}
    tok = _gh_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    with httpx.Client(headers=headers, timeout=30) as c:
        meta = c.get(f"https://api.github.com/repos/{repo}/pulls/{number}").json()
        files, page = [], 1
        while True:
            batch = c.get(f"https://api.github.com/repos/{repo}/pulls/{number}/files",
                          params={"per_page": 100, "page": page}).json()
            if not isinstance(batch, list) or not batch:
                break
            files.extend(batch)
            page += 1
            if len(batch) < 100:
                break
    changed = [f["filename"] for f in files]
    return meta, changed


# ---------- graph traversal ----------
def _impact(tx, changed_files: list[str], hops: int, decay: float):
    # direct: UI implemented by changed code + the requirements those UI verify
    direct = tx.run("""
        MATCH (c:CodeSymbol)<-[impl:IMPLEMENTED_BY]-(u:UIElement)
        WHERE c.path IN $files
        OPTIONAL MATCH (u)<-[ver:VERIFIED_BY]-(r:Requirement)
        OPTIONAL MATCH (u)<-[:CONTAINS]-(s:Screen)
        RETURN c.name AS symbol, c.path AS path, u.id AS uid, u.label AS label,
               u.role AS role, s.id AS screen, impl.confidence AS impl_conf,
               impl.evidence AS impl_ev, r.id AS req_id, r.title AS req_title,
               r.type AS req_type, r.coverage AS coverage, ver.confidence AS ver_conf
    """, files=changed_files).data()

    # indirectly affected files via the import graph (reverse DEPENDS_ON).
    # var-length upper bound must be a literal, so inline the validated int.
    h = max(1, int(hops))
    dependents = tx.run(f"""
        MATCH (dep:CodeSymbol)-[:DEPENDS_ON*1..{h}]->(c:CodeSymbol)
        WHERE c.path IN $files AND dep.kind = 'file' AND NOT dep.path IN $files
        RETURN DISTINCT dep.path AS path
    """, files=changed_files).data()

    # changed symbols with NO UI mapping (components/actions only) -> human review
    unmapped = tx.run("""
        MATCH (c:CodeSymbol)
        WHERE c.path IN $files AND c.kind IN ['component','action']
          AND NOT (c)<-[:IMPLEMENTED_BY]-(:UIElement)
        RETURN c.name AS symbol, c.path AS path, c.kind AS kind
    """, files=changed_files).data()

    # total verifying UI per requirement — to tell "loses coverage" (ALL verifying UI
    # impacted) from "partially affected" (other UI still verifies it).
    totals = tx.run("""
        MATCH (r:Requirement)-[:VERIFIED_BY]->(u:UIElement)
        RETURN r.id AS req_id, collect(DISTINCT trim(split(u.label,'\n')[0])) AS labels
    """).data()

    # requirements already recorded as absent whose best candidate touches changed code
    gaps = tx.run("""
        MATCH (r:Requirement)-[:HAS_GAP]->(g:Gap)
        RETURN r.id AS req_id, r.title AS req_title, r.type AS req_type,
               g.reason AS reason, g.best_candidate AS best
    """).data()
    return direct, dependents, unmapped, gaps, totals


def _assemble(direct, dependents, unmapped, gaps, totals, changed_files, decay):
    total_verifying = {t["req_id"]: set(t["labels"]) for t in totals}
    # impacted UI elements deduped by label — "the Undo button" is one UI area even
    # though persistent chrome is captured on several screens. Aggregate the screens.
    ui_map: dict[str, dict] = {}
    req_map: dict[str, dict] = {}
    for row in direct:
        pc = (row["impl_conf"] or 0.0)
        key = (row["label"] or "").strip().split("\n")[0]
        u = ui_map.setdefault(key, {
            "label": key, "role": row["role"], "screens": set(),
            "via_symbol": row["symbol"], "via_path": row["path"],
            "confidence": round(pc, 3)})
        if row["screen"]:
            u["screens"].add(row["screen"])
        if pc > u["confidence"]:
            u["confidence"], u["via_symbol"], u["via_path"] = round(pc, 3), row["symbol"], row["path"]
        if row["req_id"]:
            path_conf = pc * (row["ver_conf"] or 0.0)
            r = req_map.setdefault(row["req_id"], {
                "id": row["req_id"], "title": row["req_title"], "type": row["req_type"],
                "coverage": row["coverage"], "impacted_via": set(), "confidence": 0.0})
            r["impacted_via"].add(row["label"])
            r["confidence"] = round(max(r["confidence"], path_conf), 3)

    for r in req_map.values():
        impacted = r["impacted_via"]
        total = total_verifying.get(r["id"], set())
        # loses coverage when every UI element that verifies it is impacted
        r["loses_coverage"] = bool(total) and impacted >= total
        r["verified_by_total"] = len(total)
        r["verified_by_impacted"] = len(impacted)
        r["impacted_via"] = sorted(impacted)

    screens = sorted({s for u in ui_map.values() for s in u["screens"]})
    for u in ui_map.values():
        u["screens"] = sorted(u["screens"])
    gap_hits = [g for g in gaps if g["best"] and any(
        g["best"].split("::")[0] in u["via_symbol"] for u in ui_map.values())]

    return {
        "changed_files_in_map": sorted({u["via_path"] for u in ui_map.values()}),
        "impacted_ui": sorted(ui_map.values(), key=lambda x: -x["confidence"]),
        "impacted_screens": screens,
        "impacted_requirements": sorted(req_map.values(), key=lambda x: -x["confidence"]),
        "indirect_files": [d["path"] for d in dependents],
        "unmapped_changes": unmapped,
        "gaps_possibly_affected": gap_hits,
    }


# ---------- report ----------
_REPORT_SYSTEM = """You are writing a blast-radius report for a QA lead who understands the
product but NOT the code. Input is a structured impact set from a knowledge graph.
Write a clear, scannable Markdown report with these sections:
  # Blast Radius — PR #<n>: <title>
  **Bottom line** — 2-3 sentences: what changed and the headline risk.
  ## What to re-test (ranked) — a table: UI area | why at risk | confidence (High/Med/Low)
  ## Requirements affected — which product requirements these UI areas verify, and whether
     any could LOSE test coverage. Use the `loses_coverage` flag: if true, state clearly
     that EVERY UI path that verifies this requirement runs through changed code, so it is
     AT RISK of losing coverage; if false, note other UI still verifies it.
  ## Needs a human — code changes we could not map to any UI, and low-confidence calls.
Rules: translate component names into product language (ImageExportDialog -> "Export image dialog").
Confidence: >=0.8 High, 0.5-0.8 Medium, <0.5 Low. Never invent impact not in the data.
Be concise. No code jargon in the body."""


def run(settings: Settings, pr_number: int | None = None) -> None:
    pr_cfg = settings.cfg["pr"]
    repo = pr_cfg["repo"]
    number = pr_number or pr_cfg.get("number")
    if not number:
        raise SystemExit("No PR number. Set pr.number in config or pass --pr N")
    hops = pr_cfg.get("dependency_hops", 1)
    decay = pr_cfg.get("hop_decay", 0.6)

    print(f"  fetching PR #{number} from {repo} ...")
    meta, changed = _fetch_pr(repo, number)
    title = meta.get("title", "")
    print(f"  '{title}' — {len(changed)} files changed")

    driver = GraphDatabase.driver(settings.neo4j_uri,
                                  auth=(settings.neo4j_user, settings.neo4j_password))
    with driver.session() as sess:
        direct, dependents, unmapped, gaps, totals = sess.execute_read(_impact, changed, hops, decay)
    driver.close()

    impact = _assemble(direct, dependents, unmapped, gaps, totals, changed, decay)
    impact["pr"] = {"number": number, "title": title, "repo": repo,
                    "files_changed": len(changed)}

    reports = settings.artifacts_dir.parent.parent / "reports"
    reports.mkdir(exist_ok=True)
    (reports / f"PR-{number}.json").write_text(json.dumps(impact, indent=2))

    client = get_client()
    res = client.complete_json(
        _REPORT_SYSTEM,
        "Produce the report as JSON {\"markdown\": \"...\"}. Impact data:\n" + json.dumps(impact),
        schema={"type": "object", "properties": {"markdown": {"type": "string"}},
                "required": ["markdown"]})
    md = res.data.get("markdown", "") if isinstance(res.data, dict) else str(res.data)
    (reports / f"PR-{number}.md").write_text(md)

    print(f"✓ reason: {len(impact['impacted_ui'])} UI areas, "
          f"{len(impact['impacted_requirements'])} requirements, "
          f"{len(impact['unmapped_changes'])} unmapped changes")
    print(f"        report -> reports/PR-{number}.md  (+ .json)")


if __name__ == "__main__":
    from src import config
    run(config.load())
