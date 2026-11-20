"""Evaluation harness.

Answers Part B item 8: "If we ran your system 100 times on the same input, how would we
know which runs were correct?"

Approach:
  * Freeze a known-good run as a FIXTURE (eval/fixtures/). The eval scores the fixture, so
    it is stable and repeatable regardless of LLM nondeterminism in a live run.
  * Score the fixture against HAND-AUTHORED GOLD labels (eval/gold/) — an expert's judgment
    authored independently of the system output (and deliberately disagreeing in a few spots).
  * Four metrics:
      1. UI->Code linker accuracy        (is each element mapped to an acceptable component?)
      2. Requirement coverage accuracy   (verified / absent classification vs gold)
      3. Blast-radius recall             (does the PR report flag the expected requirements?)
      4. Confidence calibration          (does higher confidence => higher accuracy?)
  * Determinism check: the deterministic core (code map + lexical linking) is re-derived
    twice and asserted identical — the part that MUST be reproducible across 100 runs.

Run:  python -m eval.evaluate         (from repo root, venv active)
"""
from __future__ import annotations

import json
from pathlib import Path

from src.link.linker import _tokens, _build_idf, _weighted_match

ROOT = Path(__file__).resolve().parent
FIX = ROOT / "fixtures"
GOLD = ROOT / "gold"


def _load(p):
    return json.loads((FIX / p).read_text())


def _gold(p):
    return json.loads((GOLD / p).read_text())


# ---------- 1. UI -> Code linker accuracy ----------
def eval_ui_code():
    edges = _load("edges.json")["edges"]
    ui = {e["id"]: e for e in _load("ui.json")["elements"]}
    gold = _gold("ui_code.json")["mappings"]

    # best IMPLEMENTED_BY per element label (highest confidence across screens)
    best: dict[str, tuple[str, float]] = {}
    for e in edges:
        if e["rel"] != "IMPLEMENTED_BY":
            continue
        label = ui.get(e["src"], {}).get("label", "").split("\n")[0].strip()
        comp = e["dst"].split("::")[-1]
        if label not in best or e["confidence"] > best[label][1]:
            best[label] = (comp, e["confidence"])

    rows, correct = [], 0
    for g in gold:
        label = g["label"]
        got, conf = best.get(label, ("<none>", 0.0))
        ok = got in g["acceptable"]
        correct += ok
        rows.append((label, got, conf, ok, g["acceptable"]))

    print("\n=== 1. UI → Code linker accuracy ===")
    for label, got, conf, ok, acc in rows:
        mark = "✓" if ok else "✗"
        extra = "" if ok else f"  (expected one of {acc})"
        print(f"  {mark} {label:26} -> {got:24} conf={conf}{extra}")
    acc = correct / len(gold)
    print(f"  accuracy: {correct}/{len(gold)} = {acc:.0%}")
    return {"ui_code_accuracy": acc, "n": len(gold), "detail": rows}


# ---------- 2. Requirement coverage accuracy ----------
def eval_req_coverage():
    reqs = {r["id"]: r for r in _load("requirements.json")["requirements"]}
    gold = _gold("req_coverage.json")["expected"]
    gold = {k: v for k, v in gold.items() if not k.startswith("_")}

    # lenient: 'partial' counts as matching 'verified' (both mean "some UI verifies it")
    def norm(c):
        return "verified" if c in ("verified", "partial") else c

    print("\n=== 2. Requirement coverage vs gold ===")
    correct = 0
    for rid, exp in gold.items():
        got = reqs.get(rid, {}).get("coverage", "missing")
        ok = norm(got) == norm(exp)
        correct += ok
        if not ok:
            print(f"  ✗ {rid} {reqs.get(rid,{}).get('title','?')[:32]:32} got={got} gold={exp}")
    acc = correct / len(gold)
    print(f"  accuracy: {correct}/{len(gold)} = {acc:.0%} (mismatches shown above)")
    return {"coverage_accuracy": acc, "n": len(gold)}


# ---------- 3. Blast-radius recall ----------
def eval_blast_radius():
    gold = _gold("blast_radius.json")["prs"]
    print("\n=== 3. Blast-radius recall (did the report flag the expected requirements?) ===")
    out = {}
    for pr, spec in gold.items():
        report = json.loads((FIX / f"PR-{pr}.json").read_text())
        flagged = " | ".join(r["title"] for r in report["impacted_requirements"]).lower()
        kws = spec["expected_requirement_keywords"]
        hit = [k for k in kws if k.lower() in flagged]
        recall = len(hit) / len(kws)
        print(f"  PR #{pr} ({spec['title'][:34]}): {len(hit)}/{len(kws)} expected keywords flagged "
              f"-> {sorted(set(kws)-set(hit)) or 'all found'}")
        out[pr] = recall
    return {"blast_radius_recall": out}


# ---------- 4. Confidence calibration ----------
def eval_calibration():
    edges = _load("edges.json")["edges"]
    ui = {e["id"]: e for e in _load("ui.json")["elements"]}
    gold = {g["label"]: g["acceptable"] for g in _gold("ui_code.json")["mappings"]}

    buckets = {"[0.8,1.0]": [], "[0.5,0.8)": []}
    for e in edges:
        if e["rel"] != "IMPLEMENTED_BY":
            continue
        label = ui.get(e["src"], {}).get("label", "").split("\n")[0].strip()
        if label not in gold:
            continue
        comp = e["dst"].split("::")[-1]
        ok = comp in gold[label]
        (buckets["[0.8,1.0]"] if e["confidence"] >= 0.8 else buckets["[0.5,0.8)"]).append(ok)

    print("\n=== 4. Confidence calibration (higher confidence should mean higher accuracy) ===")
    out = {}
    for b, vals in buckets.items():
        if vals:
            acc = sum(vals) / len(vals)
            print(f"  {b}: {sum(vals)}/{len(vals)} correct = {acc:.0%}")
            out[b] = acc
    return {"calibration": out}


# ---------- 5. Determinism of the deterministic core ----------
def eval_determinism():
    ui = _load("ui.json")["elements"]
    code = [s for s in _load("code.json")["symbols"] if s["kind"] in ("component", "action")]

    def derive():
        el_tok = {e["id"]: _tokens(e["label"]) for e in ui}
        sym_tok = {s["id"]: _tokens(s["name"]) for s in code}
        idf = _build_idf(list(el_tok.values()))
        out = {}
        for e in ui:
            best, bs = None, 0.0
            for s in code:
                sc = _weighted_match(el_tok[e["id"]], sym_tok[s["id"]], idf)
                if sc > bs:
                    best, bs = s["id"], sc
            out[e["id"]] = (best, round(bs, 6))
        return out

    a, b = derive(), derive()
    same = a == b
    print("\n=== 5. Determinism of the deterministic core ===")
    print(f"  re-derived lexical UI→Code mapping twice: {'IDENTICAL ✓' if same else 'DIFFERED ✗'}")
    print("  (the LLM seams are nondeterministic by nature; this core is not)")
    return {"deterministic_core_stable": same}


def main():
    print("#" * 64)
    print("  BLAST RADIUS ENGINE — EVALUATION  (fixture vs hand-authored gold)")
    print("#" * 64)
    results = {}
    results.update(eval_ui_code())
    results.update(eval_req_coverage())
    results.update(eval_blast_radius())
    results.update(eval_calibration())
    results.update(eval_determinism())

    print("\n" + "=" * 64)
    print("SUMMARY")
    print(f"  UI→Code linker accuracy : {results['ui_code_accuracy']:.0%}")
    print(f"  Requirement coverage    : {results['coverage_accuracy']:.0%}")
    print(f"  Blast-radius recall     : " +
          ", ".join(f"PR#{k} {v:.0%}" for k, v in results['blast_radius_recall'].items()))
    print(f"  Deterministic core      : {'stable' if results['deterministic_core_stable'] else 'UNSTABLE'}")
    (ROOT / "results.json").write_text(json.dumps(
        {k: v for k, v in results.items() if k != "detail"}, indent=2, default=str))
    print(f"\n  full results -> eval/results.json")


if __name__ == "__main__":
    main()
