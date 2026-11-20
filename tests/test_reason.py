"""Unit tests for blast-radius assembly — the 'loses coverage' logic and UI dedup.
Uses synthetic graph rows, so no Neo4j / GitHub needed."""
from src.reason.blast_radius import _assemble


def _row(symbol, path, label, screen, impl, req_id, req_title, ver):
    return {"symbol": symbol, "path": path, "uid": f"{screen}:{label}", "label": label,
            "role": "button", "screen": screen, "impl_conf": impl, "impl_ev": "lex",
            "req_id": req_id, "req_title": req_title, "req_type": "functional",
            "coverage": "verified", "ver_conf": ver}


def test_loses_coverage_when_all_verifying_ui_impacted():
    direct = [
        _row("RectangleToolButton", "Tools.tsx", "Rectangle", "canvas", 0.8, "REQ-1", "Shapes", 0.9),
        _row("ArrowToolButton", "Tools.tsx", "Arrow", "canvas", 0.8, "REQ-1", "Shapes", 0.9),
    ]
    totals = [{"req_id": "REQ-1", "labels": ["Rectangle", "Arrow"]}]
    out = _assemble(direct, [], [], [], totals, ["Tools.tsx"], 0.6)
    req = out["impacted_requirements"][0]
    assert req["loses_coverage"] is True
    assert req["verified_by_impacted"] == 2 and req["verified_by_total"] == 2


def test_partial_coverage_when_other_ui_still_verifies():
    direct = [
        _row("RectangleToolButton", "Tools.tsx", "Rectangle", "canvas", 0.8, "REQ-1", "Shapes", 0.9),
    ]
    totals = [{"req_id": "REQ-1", "labels": ["Rectangle", "Zoom"]}]   # Zoom not impacted
    out = _assemble(direct, [], [], [], totals, ["Tools.tsx"], 0.6)
    req = out["impacted_requirements"][0]
    assert req["loses_coverage"] is False
    assert req["verified_by_impacted"] == 1 and req["verified_by_total"] == 2


def test_ui_deduped_by_label_across_screens():
    direct = [
        _row("UndoIcon", "Undo.tsx", "Undo", "canvas", 1.0, "REQ-2", "Undo", 0.95),
        _row("UndoIcon", "Undo.tsx", "Undo", "main_menu", 1.0, "REQ-2", "Undo", 0.95),
    ]
    totals = [{"req_id": "REQ-2", "labels": ["Undo"]}]
    out = _assemble(direct, [], [], [], totals, ["Undo.tsx"], 0.6)
    ui = out["impacted_ui"]
    assert len(ui) == 1                              # one "Undo" area
    assert set(ui[0]["screens"]) == {"canvas", "main_menu"}


def test_unmapped_changes_passed_through():
    out = _assemble([], [], [{"symbol": "exportScene", "path": "x.ts", "kind": "function"}],
                    [], [], ["x.ts"], 0.6)
    assert out["unmapped_changes"][0]["symbol"] == "exportScene"
