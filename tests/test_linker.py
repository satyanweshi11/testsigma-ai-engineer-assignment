"""Unit tests for the linker's scoring core — the deterministic heart of fusion."""
from src.link.linker import _tokens, _lexical, _build_idf, _weighted_match


def test_tokens_splits_camel_and_drops_stopwords():
    assert _tokens("RectangleToolButton") == {"rectangle"}       # tool, button stopped
    assert _tokens("toolbar-rectangle") == {"rectangle", "toolbar"}
    assert _tokens("Undo") == {"undo"}


def test_lexical_overlap():
    assert _lexical({"undo"}, {"undo", "redo"}) == 1.0
    assert _lexical({"undo"}, {"zoom"}) == 0.0


def test_idf_downweights_common_tokens():
    corpus = [{"rectangle", "toolbar"}, {"arrow", "toolbar"},
              {"line", "toolbar"}, {"text", "toolbar"}, {"ellipse", "toolbar"}]
    idf = _build_idf(corpus)
    assert idf["rectangle"] > idf["toolbar"]     # rare beats common


def test_weighted_match_prefers_specific_component():
    """The 'Rectangle' element (data-testid toolbar-rectangle) must map to the specific
    RectangleToolButton, not the generic Toolbar or a verbose lookalike that merely
    contains the token."""
    corpus = [{"rectangle", "toolbar"}, {"arrow", "toolbar"},
              {"line", "toolbar"}, {"text", "toolbar"}, {"ellipse", "toolbar"}]
    idf = _build_idf(corpus)
    elem = {"rectangle", "toolbar"}
    specific = _weighted_match(elem, {"rectangle"}, idf)              # RectangleToolButton
    generic = _weighted_match(elem, {"toolbar"}, idf)                 # Toolbar
    verbose = _weighted_match(elem, {"welcome", "top", "toolbar", "arrow"}, idf)
    assert specific > generic > verbose
    assert specific >= 0.8                                            # accept threshold


def test_weighted_match_no_overlap_is_zero():
    idf = _build_idf([{"rectangle"}, {"arrow"}])
    assert _weighted_match({"rectangle"}, {"zoom"}, idf) == 0.0
