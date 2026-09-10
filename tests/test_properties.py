"""Hypothesis properties for the pure pipeline building blocks."""

from __future__ import annotations

import json

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ocr_server.native_layout import normalize_box
from ocr_server.pages import parse_pages_spec
from ocr_server.pp_layout import (
    DEDUPE_IOU,
    LABELS,
    MAX_AREA_SHARE,
    MIN_DIM,
    SCORE_MIN,
    _iou,
    clean_regions,
)
from ocr_server.spans import Span, assign_ids, spans_to_jsonl

SETTINGS = settings(
    max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)

box_coord = st.floats(min_value=-5000, max_value=5000, allow_nan=False, allow_infinity=False)
page_dim = st.floats(min_value=1, max_value=10000, allow_nan=False, allow_infinity=False)


@SETTINGS
@given(
    a=box_coord,
    b=box_coord,
    c=box_coord,
    d=box_coord,
    width=page_dim,
    height=page_dim,
)
def test_normalize_box_is_always_in_bounds_and_sorted(a, b, c, d, width, height):
    x1, y1, x2, y2 = normalize_box([a, b, c, d], width, height)
    assert 0 <= x1 <= x2 <= 1000
    assert 0 <= y1 <= y2 <= 1000


@SETTINGS
@given(
    pages=st.lists(st.integers(min_value=1, max_value=30), min_size=1, max_size=30),
    labels=st.lists(
        st.sampled_from(["text", "title", "header", "footer", "image"]),
        min_size=1,
        max_size=30,
    ),
)
def test_assign_ids_unique_and_sequential_per_page(pages, labels):
    spans = [
        Span(page=page, label=labels[i % len(labels)], box=None, text="x")
        for i, page in enumerate(pages)
    ]
    assign_ids(spans)
    assert len({span.id for span in spans}) == len(spans)
    counters: dict[int, int] = {}
    for span in spans:
        counters[span.page] = counters.get(span.page, 0) + 1
        assert span.id == f"p{span.page}-{counters[span.page]}"


@SETTINGS
@given(
    entries=st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=9),
            st.sampled_from(["text", "title", "image"]),
            st.one_of(st.none(), st.lists(st.integers(0, 1000), min_size=4, max_size=4)),
            st.text(max_size=20),
            st.one_of(st.none(), st.text(min_size=1, max_size=20)),
        ),
        min_size=0,
        max_size=15,
    )
)
def test_spans_to_jsonl_round_trip_and_image_omission(entries):
    spans = [
        Span(page=page, label=label, box=box, text=text, image=image)
        for page, label, box, text, image in entries
    ]
    # JSONL contract: records are separated by "\n" only (json.dumps escapes
    # \n and \r; other Unicode line boundaries like NEL stay inline and are
    # valid inside JSON strings, so consumers must split on "\n").
    lines = [line for line in spans_to_jsonl(spans).split("\n") if line]
    assert len(lines) == len(spans)
    for line, span in zip(lines, spans):
        parsed = json.loads(line)
        assert parsed["page"] == span.page
        assert parsed["label"] == span.label
        assert parsed["box"] == span.box
        assert parsed["text"] == span.text
        assert ("image" in parsed) is (span.image is not None)


rows = st.lists(
    st.tuples(
        st.integers(min_value=-1, max_value=len(LABELS) + 2),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        st.floats(min_value=-200, max_value=1200, allow_nan=False),
        st.floats(min_value=-200, max_value=1200, allow_nan=False),
        st.floats(min_value=-200, max_value=1200, allow_nan=False),
        st.floats(min_value=-200, max_value=1200, allow_nan=False),
    ),
    max_size=30,
)
SHARED = dict(
    width=1000,
    height=1000,
)


@SETTINGS
@given(raw=rows)
def test_clean_regions_invariants(raw):
    kept = clean_regions([list(row) for row in raw], page=1, **SHARED)
    for region in kept:
        x1, y1, x2, y2 = region.box
        assert 0 <= x1 < x2 <= 1000
        assert 0 <= y1 < y2 <= 1000
        assert min(x2 - x1, y2 - y1) >= MIN_DIM
        assert region.score >= SCORE_MIN
        area_share = ((x2 - x1) / 1000) * ((y2 - y1) / 1000)
        assert area_share <= MAX_AREA_SHARE
    for i, first in enumerate(kept):
        for second in kept[i + 1 :]:
            assert _iou(first.box, second.box) <= DEDUPE_IOU


@SETTINGS
@given(
    total=st.integers(min_value=1, max_value=200),
    a=st.integers(min_value=1, max_value=200),
    b=st.integers(min_value=1, max_value=200),
)
def test_parse_pages_spec_invariants(total, a, b):
    low, high = min(a, b), max(a, b)
    if high > total:
        return
    pages = parse_pages_spec(f"{low}-{high}", total)
    assert pages == sorted(set(pages))
    assert all(1 <= page <= total for page in pages)
    assert pages[0] == low and pages[-1] <= total
