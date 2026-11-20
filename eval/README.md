# Evaluation

Answers the assignment's hardest eval question: *"If we ran your system 100 times on the
same input, how would we know which runs were correct?"*

## The design
A live run has LLM nondeterminism (requirement wording, gray-zone adjudication). So we
don't eval a live run — we **freeze a known-good run as a fixture** and score *that*.
This separates two concerns:

1. **Is the deterministic core reproducible?** → `eval_determinism` re-derives the code map
   + lexical linking twice and asserts they're identical. This is the part that *must* be
   stable across 100 runs, and it is.
2. **Is the output correct?** → score the fixture against **hand-authored gold labels**
   (`gold/`), written by a human independently of the system (and deliberately disagreeing
   in a couple of places, so a passing score means something).

## What's measured
| Metric | Gold | Question |
|---|---|---|
| UI→Code accuracy | `gold/ui_code.json` | Is each element mapped to an acceptable component? |
| Requirement coverage | `gold/req_coverage.json` | verified/absent classification vs expert |
| Blast-radius recall | `gold/blast_radius.json` | Does the PR report flag the expected requirements? |
| Confidence calibration | — | Does higher confidence mean higher accuracy? |

## Run it
```bash
python -m eval.evaluate      # from repo root, venv active
```

## Current results (frozen fixture)
- **UI→Code linker: 100%** (18/18 labeled elements)
- **Requirement coverage: 89%** (16/18) — the 2 misses are real and informative:
  - `Hand-Drawn Visual Style` — system says *partial*, expert says *absent* (it's a render
    property, not a control).
  - `Excalidraw Format Import/Export` — system says *absent*, expert says *verified*
    (the Open / Save-to menu items are the import/export; the linker missed that connection).
- **Blast-radius recall: 100%** on both sample PRs
- **Deterministic core: stable**

The two coverage misses are exactly the kind of signal this eval exists to surface — they
point at concrete linker improvements (menu-item semantics, render-vs-control distinction)
rather than hiding behind a suspiciously perfect score.

## Extending
Add rows to the gold files, or freeze a new fixture with
`cp artifacts/<name>/*.json eval/fixtures/ && cp reports/*.json eval/fixtures/`.
