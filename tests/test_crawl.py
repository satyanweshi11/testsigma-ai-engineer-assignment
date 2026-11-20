"""Unit tests for crawl helpers (pure functions, no browser)."""
from src.crawl.crawler import _selector_for


def test_selector_prefers_testid():
    e = {"testid": "toolbar-rectangle", "ariaLabel": "Rectangle", "cls": "ToolIcon"}
    assert _selector_for(e, "button") == '[data-testid="toolbar-rectangle"]'


def test_selector_falls_back_to_aria():
    e = {"testid": "", "ariaLabel": "Library", "cls": "x"}
    assert _selector_for(e, "button") == '[aria-label="Library"]'


def test_selector_falls_back_to_class():
    e = {"testid": "", "ariaLabel": "", "cls": "welcome-menu"}
    assert _selector_for(e, "button") == ".welcome-menu"


def test_selector_falls_back_to_role():
    e = {"testid": "", "ariaLabel": "", "cls": ""}
    assert _selector_for(e, "button") == "button"
