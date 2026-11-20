"""Smoke tests that the eval harness runs against the frozen fixture in CI."""
from eval.evaluate import eval_ui_code, eval_req_coverage, eval_determinism


def test_ui_code_accuracy_on_fixture():
    r = eval_ui_code()
    assert r["ui_code_accuracy"] == 1.0          # all labeled elements map correctly


def test_coverage_accuracy_reasonable():
    r = eval_req_coverage()
    # the gold deliberately disagrees in 2 spots; accuracy should be high but not perfect
    assert 0.8 <= r["coverage_accuracy"] < 1.0


def test_deterministic_core_is_stable():
    assert eval_determinism()["deterministic_core_stable"] is True
