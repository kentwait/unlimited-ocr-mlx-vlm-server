"""Unit tests for the layout pre-scan (pure logic: no model, no server)."""

from __future__ import annotations

import pytest

from ocr_server.layout import (
    LayoutProfile,
    apply_layout_filter,
    layout_hint,
    parse_layout_profile,
)
from ocr_server.spans import Span


def _span(page: int, label: str, box, text: str) -> Span:
    return Span(page=page, label=label, box=box, text=text)


# ---------- profile parsing ----------


def test_parse_valid_profile():
    raw = (
        '{"columns": "2", "header": "Article", '
        '"footer": "Nature | www.nature.com", '
        '"figures": [{"box": [100, 500, 900, 950]}], "confidence": 0.9}'
    )
    p = parse_layout_profile(raw, 3)
    assert p is not None
    assert (p.page, p.columns) == (3, "2")
    assert p.header == "Article"
    assert p.footer == "Nature | www.nature.com"
    assert p.figures == [[100, 500, 900, 950]]
    assert p.confidence == 0.9


def test_parse_columns_int_and_default_variants():
    assert parse_layout_profile('{"columns": 1}', 1).columns == "1"
    assert parse_layout_profile('{"columns": 2}', 1).columns == "2"
    assert parse_layout_profile("{}", 1).columns == "1"
    assert parse_layout_profile("{}", 1).confidence == 0.5
    assert parse_layout_profile('{"columns": 5}', 1) is None


def test_parse_tolerates_trailing_junk_after_final_brace():
    # The slice ends at the LAST "}": trailing prose is excluded. A junk
    # character immediately after would corrupt the slice instead.
    p = parse_layout_profile('{"columns": "2"}!', 1)
    assert p is not None and p.columns == "2"


def test_parse_tolerates_surrounding_prose_and_int_columns():
    p = parse_layout_profile('Here is the layout:\n{"columns": 3}\nDone.', 1)
    assert p is not None and p.columns == "3"
    assert p.header is None and p.footer is None and p.figures == []


def test_parse_rejects_garbage():
    assert parse_layout_profile("not json at all", 1) is None
    assert parse_layout_profile('{"columns": "5"}', 1) is None
    assert parse_layout_profile('["columns", "2"]', 1) is None
    assert parse_layout_profile("", 1) is None


def test_parse_drops_degenerate_boxes_and_clamps_confidence():
    raw = (
        '{"columns": "1", "figures": [[0, 0, 10, 10], [900, 900, 100, 100], '
        '"nope", [0, 0, 1000, 1000]], "confidence": 7}'
    )
    p = parse_layout_profile(raw, 1)
    assert p is not None
    # Tiny, inverted, and non-box entries dropped; the full-page box kept.
    assert p.figures == [[0, 0, 1000, 1000]]
    assert p.confidence == 1.0


def test_parse_drops_nonnumeric_and_out_of_range_boxes():
    raw = (
        '{"columns": "2", "figures": [["a", "b", "c", "d"], '
        "[0, 0, 1001, 500], [100, 100, 900, 900]]}"
    )
    p = parse_layout_profile(raw, 1)
    assert p is not None
    assert p.figures == [[100, 100, 900, 900]]


def test_clean_text_collapses_whitespace():
    p = parse_layout_profile('{"columns": "1", "header": "Nature  |\\t www.nature.com "}', 1)
    assert p is not None and p.header == "Nature | www.nature.com"


def test_clean_box_rejects_non_sequences_and_size_thresholds():
    from ocr_server.layout import _clean_box

    # Non-sequences never parse, even with four int-like keys.
    assert _clean_box({100: "a", 200: "b", 900: "c", 950: "d"}) is None
    # Narrow boxes: x2+x1 arithmetic must not leak them through.
    assert _clean_box([10, 0, 50, 500]) is None
    assert _clean_box([0, 10, 500, 60]) is None
    # Exactly MIN_FIGURE_SIZE (60) passes; one pixel under does not.
    assert _clean_box([0, 0, 60, 500]) == [0, 0, 60, 500]
    assert _clean_box([0, 0, 59, 500]) is None


def test_parse_rejects_bad_confidence_and_truncates_long_text():
    assert parse_layout_profile('{"columns": "1", "confidence": "high"}', 1) is None
    assert parse_layout_profile('{"columns": "1", "confidence": null}', 1) is None
    long_header = "H" * 300
    p = parse_layout_profile(f'{{"columns": "1", "header": "{long_header}"}}', 1)
    assert p is not None and p.header == "H" * 200
    # Non-string furniture is ignored, not fatal.
    p = parse_layout_profile('{"columns": "1", "header": 42, "footer": ""}', 1)
    assert p is not None and p.header is None and p.footer is None


def test_profile_to_dict_round_trip():
    p = LayoutProfile(page=2, columns="mixed", footer="p. 12", confidence=0.7)
    d = p.to_dict()
    assert d["columns"] == "mixed" and d["page"] == 2
    assert set(d) >= {"columns", "header", "footer", "figures", "confidence", "method"}


# ---------- hint ----------


def test_hint_empty_without_profile():
    assert layout_hint(None) == ""


def test_hint_names_columns_furniture_and_figures():
    p = LayoutProfile(
        page=1, columns="2", header="Article",
        footer="Nature | www.nature.com", figures=[[0, 600, 1000, 950]],
        confidence=0.9,
    )
    assert layout_hint(p) == (
        'Layout: two-column. Ignore running header/footer lines like '
        '"Article"; "Nature | www.nature.com". Skip 1 large figure '
        "region(s) — do not transcribe text inside them. Read body "
        "columns top-to-bottom in reading order."
    )


def test_hint_minimal_profile():
    p = LayoutProfile(page=2, columns="1", confidence=0.6)
    assert layout_hint(p) == (
        "Layout: single-column. Read body columns top-to-bottom in reading order."
    )


# ---------- filter ----------


def test_filter_flags_band_matched_furniture():
    profile = LayoutProfile(page=1, columns="1", footer="Nature | www.nature.com", confidence=0.9)
    spans = [
        _span(1, "text", [0, 960, 1000, 990], "Nature | www.nature.com 12"),
        _span(1, "text", [0, 960, 1000, 990], "Nature | www.nature.com 13"),
        _span(1, "text", [0, 400, 500, 420], "Body content here"),
    ]
    counts = apply_layout_filter(spans, profile)
    assert counts["furniture_flagged"] == 2
    assert spans[0].label == "furniture"
    assert spans[1].label == "furniture"
    assert spans[2].label == "text"


def test_filter_leaves_disjoint_text_alone():
    profile = LayoutProfile(page=1, columns="1", footer="Nature | www.nature.com", confidence=0.9)
    spans = [_span(1, "text", [0, 960, 1000, 990], "Unrelated bottom line")]
    counts = apply_layout_filter(spans, profile)
    assert counts["furniture_flagged"] == 0
    assert spans[0].label == "text"


def test_filter_boundary_confidence_still_filters():
    profile = LayoutProfile(page=1, columns="1", footer="Running head", confidence=0.5)
    spans = [_span(1, "text", [0, 10, 1000, 30], "Running head")]
    assert apply_layout_filter(spans, profile)["furniture_flagged"] == 1


def test_filter_never_reflags_or_breaks_early():
    # Idempotence: pre-labeled furniture is skipped, never recounted.
    # Loop integrity: a skippable span first must not stop later flags.
    profile = LayoutProfile(page=1, columns="1", footer="Running head", confidence=0.9)
    spans = [
        _span(1, "title", [0, 10, 1000, 30], "Running head"),
        _span(1, "text", [0, 500, 1000, 520], "mid-page body"),
        _span(1, "furniture", [0, 960, 1000, 990], "Running head"),
        _span(1, "text", [0, 960, 1000, 990], "Running head 7"),
    ]
    spans[2].id = "p1-3"
    counts = apply_layout_filter(spans, profile)
    assert counts == {"figures_skipped": 0, "furniture_flagged": 1}
    assert spans[0].label == "title"
    assert spans[2].label == "furniture"


def test_filter_skips_figure_interior_text():
    profile = LayoutProfile(page=1, columns="2", figures=[[0, 500, 1000, 950]], confidence=0.8)
    spans = [
        _span(1, "text", [100, 600, 400, 620], "axis label 123"),
        _span(1, "text", [200, 700, 500, 720], "legend entry"),
        _span(1, "text", [100, 100, 400, 120], "Body paragraph"),
        _span(1, "text", [100, 150, 400, 170], "More body paragraph"),
    ]
    counts = apply_layout_filter(spans, profile)
    assert counts["figures_skipped"] == 2
    assert spans[0].label == "furniture"
    assert spans[1].label == "furniture"
    assert spans[2].label == "text"
    assert spans[3].label == "text"


def test_inside_figure_boundary_is_inclusive_with_inset():
    from ocr_server.layout import FIGURE_INSET, _inside_figure

    fig = [100, 500, 900, 950]
    # Exactly on the shrunk boundary counts as inside; one pixel outside does not.
    assert _inside_figure(
        [100 + FIGURE_INSET, 500 + FIGURE_INSET, 900 - FIGURE_INSET, 950 - FIGURE_INSET], fig
    )
    assert not _inside_figure(
        [100 + FIGURE_INSET - 1, 600, 400, 620], fig
    )
    assert not _inside_figure(
        [200, 600, 400, 950 - FIGURE_INSET + 1], fig
    )
    assert not _inside_figure(
        [200, 500 + FIGURE_INSET - 1, 400, 620], fig
    )
    assert not _inside_figure(
        [200, 600, 900 - FIGURE_INSET + 1, 620], fig
    )


def test_filter_keeps_titles_and_prelabeled_spans_out_of_figures():
    # Titles (e.g. captions overlapping a rough box) and already-furniture
    # spans are never figure candidates — and are never recounted.
    profile = LayoutProfile(page=1, columns="2", figures=[[0, 500, 1000, 950]], confidence=0.8)
    spans = [
        _span(1, "title", [100, 600, 400, 620], "Figure 1: results"),
        _span(1, "furniture", [200, 700, 500, 720], "old furniture"),
        _span(1, "text", [100, 100, 400, 120], "Body paragraph"),
        _span(1, "text", [100, 150, 400, 170], "More body paragraph"),
    ]
    counts = apply_layout_filter(spans, profile)
    assert counts == {"figures_skipped": 0, "furniture_flagged": 0}
    assert spans[0].label == "title"
    assert spans[1].label == "furniture"


def test_filter_keeps_images_with_text_out_of_figures():
    # An image span carrying text inside a figure box keeps its label (and
    # its rendered figure marker downstream) — only text spans are skipped.
    profile = LayoutProfile(page=1, columns="2", figures=[[0, 500, 1000, 950]], confidence=0.8)
    spans = [
        _span(1, "image", [100, 600, 400, 620], "caption text"),
        _span(1, "text", [100, 100, 400, 120], "Body paragraph"),
        _span(1, "text", [100, 150, 400, 170], "More body paragraph"),
    ]
    counts = apply_layout_filter(spans, profile)
    assert counts == {"figures_skipped": 0, "furniture_flagged": 0}
    assert spans[0].label == "image"


def test_filter_single_span_page_reverts_figure_drop():
    # One content span inside a figure on a one-span page: 100% > 50% share,
    # so the degenerate guard reverts instead of blanking the page.
    profile = LayoutProfile(page=1, columns="1", figures=[[0, 0, 1000, 1000]], confidence=0.9)
    spans = [_span(1, "text", [100, 100, 400, 120], "only text")]
    counts = apply_layout_filter(spans, profile)
    assert counts["figures_skipped"] == 0
    assert spans[0].label == "text"


def test_filter_ignores_blank_furniture_text():
    # Whitespace-only furniture normalizes to an empty fingerprint:
    # no match, no relabel (hits the empty-fingerprint guard).
    profile = LayoutProfile(page=1, columns="1", footer="   ", confidence=0.9)
    spans = [_span(1, "text", [0, 960, 1000, 990], "Body words here")]
    counts = apply_layout_filter(spans, profile)
    assert counts["furniture_flagged"] == 0
    assert spans[0].label == "text"


def test_filter_never_touches_titles_boxless_or_low_confidence():
    profile = LayoutProfile(page=1, columns="1", footer="Running head", confidence=0.9)
    title = _span(1, "title", [0, 960, 1000, 990], "Running head")
    gap = _span(1, "text", None, "Running head")
    apply_layout_filter([title, gap], profile)
    assert title.label == "title" and gap.label == "text"

    weak = LayoutProfile(page=1, columns="1", footer="Running head", confidence=0.1)
    span = _span(1, "text", [0, 960, 1000, 990], "Running head")
    counts = apply_layout_filter([span], weak)
    assert counts == {"figures_skipped": 0, "furniture_flagged": 0}
    assert span.label == "text"
    assert apply_layout_filter([span], None) == counts


def test_filter_reverts_degenerate_figure_cover():
    profile = LayoutProfile(page=1, columns="1", figures=[[0, 0, 1000, 1000]], confidence=0.9)
    spans = [_span(1, "text", [100, 100 + i * 30, 400, 120 + i * 30], f"para {i}") for i in range(4)]
    counts = apply_layout_filter(spans, profile)
    assert counts["figures_skipped"] == 0
    assert all(s.label == "text" for s in spans)


def test_filter_preserves_identity():
    profile = LayoutProfile(page=2, columns="2", figures=[[0, 500, 1000, 950]], confidence=0.8)
    spans = [
        _span(2, "text", [100, 600, 400, 620], "inside figure"),
        _span(2, "text", [100, 100, 400, 120], "outside figure"),
    ]
    for i, s in enumerate(spans):
        s.id = f"p2-{i + 1}"
    apply_layout_filter(spans, profile)
    assert [s.id for s in spans] == ["p2-1", "p2-2"]


# ---------- scan_layout fallbacks (stubbed vision) ----------


def _support_engine(monkeypatch):
    from ocr_server import cleanup as cleanup_mod
    from ocr_server.prompts import PromptRegistry

    monkeypatch.setattr(cleanup_mod.SupportEngine, "load", lambda self: None)
    reg = PromptRegistry()
    reg.load()
    return cleanup_mod.SupportEngine("stub", prompts=reg)


def test_scan_layout_returns_none_when_vision_fails(monkeypatch):
    from ocr_server import cleanup as cleanup_mod

    engine = _support_engine(monkeypatch)

    def boom(self, prompt, image_path, max_tokens):
        raise RuntimeError("no weights here")

    monkeypatch.setattr(cleanup_mod.SupportEngine, "_generate_vision", boom)
    assert engine.scan_layout("thumb.png", 1) is None


def test_scan_layout_returns_none_when_unparsable(monkeypatch):
    from ocr_server import cleanup as cleanup_mod

    engine = _support_engine(monkeypatch)
    monkeypatch.setattr(
        cleanup_mod.SupportEngine,
        "_generate_vision",
        lambda self, prompt, image_path, max_tokens: ("not json", 3, False),
    )
    assert engine.scan_layout("thumb.png", 1) is None


def test_scan_layout_returns_profile_on_valid_json(monkeypatch):
    from ocr_server import cleanup as cleanup_mod

    engine = _support_engine(monkeypatch)
    seen = {}

    def canned(self, prompt, image_path, max_tokens):
        seen.update(prompt=prompt, image_path=image_path, max_tokens=max_tokens)
        return '{"columns": "3", "confidence": 0.8}', 5, False

    monkeypatch.setattr(cleanup_mod.SupportEngine, "_generate_vision", canned)
    profile = engine.scan_layout("thumb.png", 4)
    assert profile is not None
    assert (profile.page, profile.columns, profile.confidence) == (4, "3", 0.8)
    # Vision plumbing: the layout prompt names the page, the token budget
    # stays small (cheap pre-scan), and timing is recorded for the audit.
    assert "4" in seen["prompt"] and "columns" in seen["prompt"]
    assert seen["image_path"] == "thumb.png"
    assert seen["max_tokens"] == 384
    assert 0 <= profile.elapsed_s < 10
    assert profile.to_dict()["columns"] == "3"
