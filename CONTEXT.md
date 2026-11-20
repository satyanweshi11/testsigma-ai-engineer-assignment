# CONTEXT — decisions & scope log

Living scratchpad for the build. Seeds the design doc (`docs/design.md`). Opinionated on purpose.

## Target
- **App:** Excalidraw (https://excalidraw.com) — zero auth, instant crawl.
- **Repo:** excalidraw/excalidraw — React/TS, human-readable component names (`ToolButton`, `ExportDialog`, `LibraryMenu`) → clean Code↔UI mapping.
- **Docs:** repo README + docs.excalidraw.com → curated requirements.
- **Why:** lets us spend the 16h on the graph + reasoning (what's scored), not on auth flows or a giant monorepo.

## The bet (where depth goes)
The assignment rewards **two deep layers + one honestly scoped**. We go deep on **Code↔UI linking + blast-radius reasoning** because that's the "intelligence layer" Testsigma is building and the most demonstrable deliverable. Crawl breadth is scoped down; requirements kept modest but real.

## Stack decisions
- **Neo4j** via Docker (assignment requires Neo4j; Docker = zero signup).
- **Crawl:** LLM-guided Playwright over ~5–8 seed screens. Not `browser-use` free-roam — controllable + reproducible beats autonomous-but-flaky for a gradeable slice. Say so in the doc.
- **LLM:** Gemini free tier (`gemini-2.5-flash`), behind `src/llm/LLMClient`. Swappable to Groq/Ollama in one line.
- **Embeddings:** Gemini `text-embedding-004` (NOT sentence-transformers) — avoids torch, which has no Python 3.15 wheels. Pure-python cosine, no numpy.
- **Code parse:** heuristic TS/TSX symbol extraction (component/function/action names → file + line) + import graph. Deliberately not a full type-aware AST — documented simplification.

## Deterministic vs LLM (the boundary)
- Deterministic: navigation + capture, doc chunking, symbol parse, exact matches, graph load, diff parse, traversal, confidence math.
- LLM (3 seams only): prose→requirements, adjudicate ambiguous cross-layer matches, write the report.

## Modeling absence (the graded bit)
A missing edge is ambiguous (unmapped vs. not-yet-analyzed). So absence is recorded, not inferred:
- `Requirement.coverage ∈ {verified, partial, absent, ambiguous}`, **plus**
- explicit `(Requirement)-[:HAS_GAP]->(:Gap {reason, best_candidate, best_score})`.
Makes absence queryable and auditable; can even surface in a blast radius.

## Confidence
- Every cross-layer edge: `confidence ∈ [0,1]` + `evidence`.
- Path confidence = product of edge confidences (decays with hops).
- Thresholds: ≥0.80 accept · 0.50–0.80 tentative/flag · <0.50 → absence/unmapped + "human review required".
- A changed code symbol with no UI mapping is never guessed — it's surfaced for a human.

## Eval plan
- Freeze crawl + PR as a fixture → deterministic stages bit-identical across 100 runs; only LLM stages vary.
- Hand-label ~15–20 UIElement↔CodeSymbol + Requirement↔UI mappings → linker precision/recall.
- 1–2 PRs with a hand-authored "expected blast radius" → rubric score the report.
- Confidence calibration: hit-rate per confidence bucket.

## Open TODOs
- [ ] Pin a concrete merged PR in `config/target.yaml` that touches a mapped component.
- [ ] Implement stages: codemap → ingest → crawl → link → load → reason.
- [ ] Sample report in `docs/`.
- [ ] Design doc `docs/design.md` (8–12 pages).
- [ ] Create GitHub repo + push (name/visibility TBD with owner).

## Build order (deterministic-first, so progress isn't blocked on the API key)
1. **codemap** — no key, no browser, no DB. ✅ unblockable now.
2. **graph loader + Neo4j** — needs Docker only.
3. **crawl** — needs Playwright browser.
4. **ingest** + **link** — need Gemini key.
5. **reason** — needs the graph populated + a PR.
