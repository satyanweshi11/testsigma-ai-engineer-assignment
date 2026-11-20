# Blast Radius Engine

[![CI](https://github.com/satyanweshi11/testsigma-ai-engineer-assignment/actions/workflows/ci.yml/badge.svg)](https://github.com/satyanweshi11/testsigma-ai-engineer-assignment/actions/workflows/ci.yml)

A tri-layer knowledge graph that connects **product intent** (requirements), the **running UI** (crawl), and the **code** behind it — then, given a real pull request, reports **what's at risk** in language a QA lead can read.

Built for the Testsigma AI Engineer assignment.

## Documentation
- [Design document](docs/design.md) — Part B: agent decomposition, schema, confidence, eval, scope, roadmap
- [Production architecture](docs/production-architecture.md) — security + the intended-but-not-wired scaling design (gateway, auth, queues, workers, rate limiters)
- [Architecture diagram](docs/architecture.html) — the visual pipeline
- [Sample reports](reports/) — blast radius for [PR #12064](reports/PR-12064.md) (broad) and [PR #12347](reports/PR-12347.md) (narrow)
- [Evaluation](eval/README.md) — fixture + hand-authored gold, run with `python -m eval.evaluate`

> **Design principle:** deterministic spine, LLM only at the seams. The graph, crawl mechanics, diff parsing and traversal are reproducible; the LLM is used only for prose→requirements, fuzzy cross-layer linking, and the final write-up.

---

## What it does (six stages)

| Stage | Command | Output |
|------|---------|--------|
| 1 · Crawl (UI) | `python run.py crawl` | `artifacts/<name>/ui.json` + screenshots |
| 2 · Ingest (Requirements) | `python run.py ingest` | `artifacts/<name>/requirements.json` |
| 3 · Code map (Code) | `python run.py codemap` | `artifacts/<name>/code.json` |
| 4 · Link (fuse layers) | `python run.py link` | `artifacts/<name>/edges.json` |
| 5 · Load (Neo4j) | `python run.py load` | graph in Neo4j |
| 6 · Reason (blast radius) | `python run.py reason --pr <N>` | `reports/PR-<N>.md` |

The target app, repo, docs and PR are all set in [`config/target.yaml`](config/target.yaml) — point the engine elsewhere by editing that one file.

---

## Setup

### 1. Prerequisites
- Python 3.11+ (tested on 3.15)
- Docker (for Neo4j)
- A free **Gemini API key** — [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (no credit card)

### 2. Install
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

### 3. Configure
```bash
cp .env.example .env        # then paste your GEMINI_API_KEY into .env
```

### 4. Start Neo4j
```bash
docker compose up -d
# Neo4j browser: http://localhost:7474  (neo4j / testsigma123)
```

### 5. Run the pipeline
```bash
python run.py all                 # stages 1–5: crawl, ingest, codemap, link, load
python run.py reason --pr 1234    # stage 6: blast radius for a real PR
```

---

## Explore the graph in Neo4j

Open **http://localhost:7474** and log in with `neo4j` / `testsigma123` (connect URL `bolt://localhost:7687`). Paste any of these into the query bar.

**1. The tri-layer graph — requirement → UI → code (the whole point):**
```cypher
MATCH p=(r:Requirement)-[:VERIFIED_BY]->(u:UIElement)-[:IMPLEMENTED_BY]->(c:CodeSymbol)
WHERE r.id IN ['REQ-002','REQ-006','REQ-010']
RETURN p
```

**2. Blast radius of the sticky-notes PR — everything touching `Tools.tsx`:**
```cypher
MATCH (c:CodeSymbol)<-[:IMPLEMENTED_BY]-(u:UIElement)<-[:VERIFIED_BY]-(r:Requirement)
WHERE c.path CONTAINS 'Tools.tsx'
RETURN c, u, r
```

**3. Absence — requirements with no UI (the `Gap` nodes):**
```cypher
MATCH p=(r:Requirement)-[:HAS_GAP]->(g:Gap) RETURN p
```

**4. One export dialog, full stack:**
```cypher
MATCH p=(r:Requirement)-[:VERIFIED_BY]->(u:UIElement)-[:IMPLEMENTED_BY]->(c:CodeSymbol)
WHERE c.path CONTAINS 'ImageExportDialog'
RETURN p
```

**5. Which requirements lose coverage if a set of files changes** (the core blast-radius query):
```cypher
MATCH (cs:CodeSymbol)<-[:IMPLEMENTED_BY]-(ui:UIElement)<-[:VERIFIED_BY]-(r:Requirement)
WHERE cs.path IN ['packages/excalidraw/components/Tools.tsx']
RETURN r.title AS requirement, collect(DISTINCT ui.label) AS at_risk_ui
```

**6. Overview of the whole schema:**
```cypher
CALL db.schema.visualization()
```

**7. Requirement coverage breakdown:**
```cypher
MATCH (r:Requirement) RETURN r.coverage AS coverage, count(*) AS n ORDER BY n DESC
```

---

## Scope (declared, not hidden)

Per the assignment's hard-scope note, depth is **deliberately uneven**:

- **Deep:** Code↔UI linking + blast-radius reasoning — the intelligence layer.
- **Kept real but modest:** Requirements ingestion — enough to make absence modeling meaningful.
- **Scoped down:** Crawl breadth — ~5–8 seed screens captured well, not autonomous full-site spidering.

Full reasoning in [`docs/design.md`](docs/design.md).

---

## Layout
```
config/target.yaml     # the one file that defines the target
run.py                 # stage CLI
src/
  llm/                 # swappable LLM client (Gemini) + embeddings
  common/models.py     # the graph schema, as dataclasses
  crawl/ ingest/ codemap/ link/ graph/ reason/
docs/                  # architecture diagram + design doc + sample report
eval/                  # fixtures + scoring
```
