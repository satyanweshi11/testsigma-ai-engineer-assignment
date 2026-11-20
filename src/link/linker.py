"""Stage 4 — Link / Fuse. The heart of the system.

Creates the cross-layer edges that make this a knowledge graph rather than three
disconnected dumps:

  UIElement  ─IMPLEMENTED_BY→  CodeSymbol
  Requirement ─VERIFIED_BY→    UIElement
  Requirement ─HAS_GAP→        Gap            (absence, recorded not inferred)

Signal, cheapest first:
  1. Lexical token match  (data-testid / label tokens ↔ component-name tokens)
     — strong and free here, because the app exposes data-testids and names components
       descriptively. This carries UI→Code almost entirely.
  2. Embeddings           (Gemini) — spent ONLY on Requirement→UI, where the match is
       semantic ("Real-Time Collaboration" ↔ "Live collaboration..."). Cached to disk
       and throttled for the free tier; falls back to lexical if quota is exhausted.
  3. LLM adjudication     — gray-zone UI→Code pairs, and the final requirement-coverage
       decision (which elements verify a requirement, or whether it's a Gap).

Every edge carries confidence ∈ [0,1] + evidence. Thresholds come from config.
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import asdict

from src.config import Settings
from src.llm import get_client
from src.llm.base import cosine
from src.common.models import Edge, Gap

_STOP = {"tool", "button", "btn", "action", "actions", "icon", "component", "menu",
         "the", "a", "of", "to", "and", "or", "item", "dialog", "panel", "ui", "app"}


def _tokens(s: str) -> set[str]:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    parts = re.split(r"[^A-Za-z0-9]+", s.lower())
    return {p for p in parts if p and p not in _STOP and len(p) > 1}


def _lexical(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    return len(inter) / min(len(a), len(b)) if inter else 0.0


def _build_idf(token_sets: list[set[str]]) -> dict[str, float]:
    """Inverse document frequency over element token sets. Makes a common token like
    'toolbar' (on every tool button) weigh far less than a rare one like 'rectangle',
    so an element maps to the SPECIFIC component (RectangleToolButton) over the generic
    container (Toolbar)."""
    n = max(1, len(token_sets))
    df = Counter(t for s in token_sets for t in s)
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


def _weighted_match(elem: set[str], sym: set[str], idf: dict[str, float]) -> float:
    """idf-weighted F1 of element-coverage and symbol-coverage.
      precision = how much of the ELEMENT's info the symbol explains
      recall    = how much of the SYMBOL's name the element accounts for
    F1 rewards a tight, specific match (RectangleToolButton) and punishes both the
    generic container (Toolbar: low precision) and a verbose name that merely contains
    the tokens (WelcomeScreenTopToolbarArrow: low recall)."""
    inter = elem & sym
    if not inter:
        return 0.0
    mass = sum(idf.get(t, 1.0) for t in inter)
    p = mass / sum(idf.get(t, 1.0) for t in elem)
    r = mass / sum(idf.get(t, 1.0) for t in sym)
    return 2 * p * r / (p + r) if (p + r) else 0.0


def _cached_embeddings(client, texts: list[str], cache_path) -> tuple[dict[str, list[float]], bool]:
    """Embed unique texts with a disk cache + throttle. Returns (vectors, available).
    `available` is False if the free-tier quota stopped us — caller falls back to lexical."""
    cache: dict[str, list[float]] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    missing = sorted({t for t in texts if t and t not in cache})
    available = True
    for i in range(0, len(missing), 20):
        batch = missing[i : i + 20]
        try:
            for t, v in zip(batch, client.embed(batch)):
                cache[t] = v
            time.sleep(1.0)  # stay comfortably under 100 embeds/min
        except Exception as e:
            print(f"  ! embeddings quota/err after {i} ({e.__class__.__name__}); "
                  f"falling back to lexical candidate selection")
            available = False
            break
    cache_path.write_text(json.dumps(cache))
    return cache, available


def run(settings: Settings) -> None:
    adir = settings.artifacts_dir
    ui = json.loads((adir / "ui.json").read_text())
    code = json.loads((adir / "code.json").read_text())
    reqs = json.loads((adir / "requirements.json").read_text())["requirements"]

    elements = ui["elements"]
    symbols = [s for s in code["symbols"] if s["kind"] in ("component", "action")]
    thr = settings.cfg.get("linking", {})
    accept = thr.get("accept_threshold", 0.80)
    review = thr.get("review_threshold", 0.50)
    client = get_client()

    sym_tokens = {s["id"]: _tokens(s["name"]) for s in symbols}
    el_tokens = {}
    for e in elements:
        toks = _tokens(e["label"])
        m = re.search(r'data-testid="([^"]+)"', e["selector"])
        if m:
            toks |= _tokens(m.group(1))
        el_tokens[e["id"]] = toks

    idf = _build_idf(list(el_tokens.values()))

    edges: list[Edge] = []
    gray_ui_code: list[tuple[str, str, float]] = []

    # ---------- UIElement -> CodeSymbol (idf-weighted lexical + LLM) ----------
    for e in elements:
        best_sym, best_score = None, 0.0
        for s in symbols:
            score = _weighted_match(el_tokens[e["id"]], sym_tokens[s["id"]], idf)
            if score > best_score:
                best_sym, best_score = s, score
        if best_sym is None or best_score == 0.0:
            continue
        shared = ",".join(sorted(el_tokens[e["id"]] & sym_tokens[best_sym["id"]]))
        if best_score >= accept:
            edges.append(Edge(src=e["id"], dst=best_sym["id"], rel="IMPLEMENTED_BY",
                              confidence=round(best_score, 3), evidence=f"lexical:{shared}"))
        elif best_score >= review:
            gray_ui_code.append((e["id"], best_sym["id"], best_score))

    if gray_ui_code:
        id2el = {e["id"]: e for e in elements}
        id2sym = {s["id"]: s for s in symbols}
        pairs = [{"pair_id": i, "ui_label": id2el[eid]["label"], "ui_role": id2el[eid]["role"],
                  "code_symbol": id2sym[sid]["name"], "code_path": id2sym[sid]["path"]}
                 for i, (eid, sid, _) in enumerate(gray_ui_code)]
        verdicts = _adjudicate_ui_code(client, pairs)
        for i, (eid, sid, score) in enumerate(gray_ui_code):
            v = verdicts.get(i)
            if v and v.get("match"):
                conf = max(review, min(0.79, float(v.get("confidence", 0.6))))
                edges.append(Edge(src=eid, dst=sid, rel="IMPLEMENTED_BY",
                                  confidence=round(conf, 3), evidence=f"llm-adjudicated({score:.2f})"))

    # ---------- Requirement -> UIElement candidate selection ----------
    # embeddings only here (semantic match); cache + fallback to lexical.
    uniq_labels = sorted({e["label"] for e in elements})
    req_text = {r["id"]: f'{r["title"]}. {r["description"]}' for r in reqs}
    vecs, emb_ok = _cached_embeddings(
        client, uniq_labels + list(req_text.values()), adir / "embed_cache.json")

    req_candidates: dict[str, list[tuple[float, dict]]] = {}
    for r in reqs:
        if emb_ok and req_text[r["id"]] in vecs:
            rv = vecs[req_text[r["id"]]]
            scored = sorted(
                ((cosine(rv, vecs.get(e["label"], [])), e) for e in elements),
                key=lambda x: x[0], reverse=True)
        else:  # lexical fallback
            rtok = _tokens(req_text[r["id"]])
            scored = sorted(
                ((_lexical(rtok, el_tokens[e["id"]]), e) for e in elements),
                key=lambda x: x[0], reverse=True)
        # keep top distinct-label candidates
        seen, top = set(), []
        for sc, e in scored:
            if e["label"] in seen:
                continue
            seen.add(e["label"]); top.append((sc, e))
            if len(top) >= 5:
                break
        req_candidates[r["id"]] = top

    # ---------- LLM decides coverage (+ absence) ----------
    gaps: list[Gap] = []
    coverage: dict[str, str] = {}
    verdicts = _adjudicate_req_ui(client, reqs, req_candidates)
    for r in reqs:
        v = verdicts.get(r["id"], {})
        kept = []
        for item in v.get("verifying", []):
            eid, conf = item.get("element_id"), float(item.get("confidence", 0.6))
            if eid and conf >= review:
                kept.append((eid, conf))
                edges.append(Edge(src=r["id"], dst=eid, rel="VERIFIED_BY",
                                  confidence=round(conf, 3), evidence="llm+embed"))
        if not kept:
            best = req_candidates[r["id"]][0] if req_candidates[r["id"]] else (0.0, None)
            reason = v.get("gap_reason") or (
                "no UI control expected (non-functional/infra)"
                if r["type"] in ("non_functional", "infra")
                else "no captured UI element above review threshold")
            gaps.append(Gap(id=f"GAP-{r['id']}", requirement_id=r["id"], reason=reason,
                            best_candidate=best[1]["id"] if best[1] else "",
                            best_score=round(best[0], 3)))
            coverage[r["id"]] = "absent"
        else:
            coverage[r["id"]] = "verified" if max(c for _, c in kept) >= accept else "partial"

    # ---------- persist ----------
    for r in reqs:
        r["coverage"] = coverage.get(r["id"], "ambiguous")
    (adir / "requirements.json").write_text(json.dumps({"requirements": reqs}, indent=2))
    (adir / "edges.json").write_text(json.dumps(
        {"edges": [asdict(e) for e in edges], "gaps": [asdict(g) for g in gaps]}, indent=2))

    n_impl = sum(1 for e in edges if e.rel == "IMPLEMENTED_BY")
    n_ver = sum(1 for e in edges if e.rel == "VERIFIED_BY")
    cov = {}
    for c in coverage.values():
        cov[c] = cov.get(c, 0) + 1
    print(f"✓ link: {n_impl} IMPLEMENTED_BY, {n_ver} VERIFIED_BY, {len(gaps)} gaps")
    print(f"        requirement coverage: {cov}")
    print(f"        -> {adir / 'edges.json'}")


def _adjudicate_ui_code(client, pairs):
    system = ("You decide whether a UI element is implemented by a given code symbol. "
              "Judge by name/role/path semantics. Be strict: only match if the symbol "
              "plausibly renders or handles that exact element.")
    schema = {"type": "object", "properties": {"verdicts": {"type": "array", "items": {
        "type": "object", "properties": {"pair_id": {"type": "integer"},
            "match": {"type": "boolean"}, "confidence": {"type": "number"}},
        "required": ["pair_id", "match"]}}}, "required": ["verdicts"]}
    res = client.complete_json(system, json.dumps({"pairs": pairs}), schema=schema)
    return {v["pair_id"]: v for v in (res.data.get("verdicts", []) if isinstance(res.data, dict) else [])}


def _adjudicate_req_ui(client, reqs, req_candidates):
    system = ("You are a QA analyst. For each requirement, decide which candidate UI "
              "elements (if any) actually verify it is present/testable in the UI. "
              "A non_functional or infra requirement usually has NO verifying UI element — "
              "return an empty 'verifying' list and a short gap_reason. Only list an element "
              "if a user could exercise the requirement through it. confidence in [0,1].")
    payload = {"requirements": [{
        "requirement_id": r["id"], "title": r["title"], "type": r["type"],
        "description": r["description"],
        "candidate_elements": [{"element_id": e["id"], "label": e["label"], "role": e["role"]}
                               for _, e in req_candidates[r["id"]]],
    } for r in reqs]}
    schema = {"type": "object", "properties": {"results": {"type": "array", "items": {
        "type": "object", "properties": {
            "requirement_id": {"type": "string"},
            "verifying": {"type": "array", "items": {"type": "object", "properties": {
                "element_id": {"type": "string"}, "confidence": {"type": "number"}},
                "required": ["element_id", "confidence"]}},
            "gap_reason": {"type": "string"}},
        "required": ["requirement_id", "verifying"]}}}, "required": ["results"]}
    res = client.complete_json(system, json.dumps(payload), schema=schema)
    return {r["requirement_id"]: r for r in
            (res.data.get("results", []) if isinstance(res.data, dict) else [])}


if __name__ == "__main__":
    from src import config
    run(config.load())
