"""Unit tests: spans, pages, rendering, boxes, crops, region filtering, merge."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pymupdf
import pytest

from ocr_server import spans as spans_mod
from ocr_server.figures import DATA_URI_PREFIX, crop_data_uri
from ocr_server.native_layout import (
    FIGURE_CONTAINABLE,
    LABEL_MAP,
    NativeBox,
    _box_text,
    missing_text_pages,
    normalize_box,
)
from ocr_server.pages import parse_pages_spec
from ocr_server.pdfrender import render_pdf_pages
from ocr_server.pipeline import (
    _center_inside,
    _figure_span,
    _iou,
    _picture_matches,
    merge_page,
    select_figures,
)
from ocr_server.pp_layout import (
    CAPTURE_CLASSES,
    DEDUPE_IOU,
    MAX_AREA_SHARE,
    MIN_DIM,
    SCORE_MIN,
    FigureRegion,
    _clamp_box,
    clean_regions,
)
from ocr_server.spans import Span, assign_ids, spans_to_jsonl

from conftest import PDF_PATH, make_image_pdf, make_text_pdf


# ---------- pages spec ----------


def test_pages_specs():
    assert parse_pages_spec(None, 5) == [1, 2, 3, 4, 5]
    assert parse_pages_spec("all", 2) == [1, 2]
    assert parse_pages_spec("1-3,5", 5) == [1, 2, 3, 5]
    assert parse_pages_spec("3,1,3", 5) == [1, 3]
    with pytest.raises(ValueError, match="out of range"):
        parse_pages_spec("1-3,9", 5)
    with pytest.raises(ValueError, match="invalid page spec"):
        parse_pages_spec("abc", 5)
    with pytest.raises(ValueError, match="invalid page range"):
        parse_pages_spec("5-2", 5)
    with pytest.raises(ValueError, match="empty pages spec"):
        parse_pages_spec(",", 5)
    with pytest.raises(ValueError, match="no pages"):
        parse_pages_spec("all", 0)


# ---------- rendering ----------


def test_render_pdf_pages(tmp_path):
    doc = pymupdf.open(stream=make_text_pdf(3), filetype="pdf")
    paths = render_pdf_pages(doc, [1, 3], 100, tmp_path)
    assert [p.name for p in paths] == ["page-0001.png", "page-0003.png"]
    assert all(p.stat().st_size > 0 for p in paths)
    doc.close()


# ---------- spans ----------


def test_span_to_dict_omits_none_image():
    span = Span(page=1, label="text", box=[0, 0, 10, 10], text="hi")
    assert span.to_dict() == {
        "id": "",
        "page": 1,
        "label": "text",
        "box": [0, 0, 10, 10],
        "text": "hi",
    }


def test_span_to_dict_includes_image():
    span = Span(page=2, label="image", box=None, text="", image="data:image/png;base64,x")
    data = span.to_dict()
    assert data["image"] == "data:image/png;base64,x"
    assert data["box"] is None


def test_assign_ids_per_page_and_preserves_order():
    items = [
        Span(page=2, label="text", box=None, text="a"),
        Span(page=1, label="text", box=None, text="b"),
        Span(page=2, label="text", box=None, text="c"),
    ]
    assign_ids(items)
    assert [s.id for s in items] == ["p2-1", "p1-1", "p2-2"]


def test_spans_to_jsonl_round_trip():
    spans = [
        Span(page=1, label="title", box=[0, 0, 10, 10], text="T", id="p1-1"),
        Span(page=1, label="image", box=[0, 0, 5, 5], text="", id="p1-2", image="x"),
    ]
    lines = spans_to_jsonl(spans).splitlines()
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["label"] == "title"
    assert "image" not in parsed[0]
    assert parsed[1]["image"] == "x"
    assert spans_mod.spans_to_jsonl([]) == ""


# ---------- native layout ----------


def test_normalize_box_scales_and_repairs_inversion():
    assert normalize_box([594, 756, 0, 0], 594, 756) == [0, 0, 1000, 1000]
    assert normalize_box([59.4, 75.6, 297, 378], 594, 756) == [100, 100, 500, 500]


def test_normalize_box_clamps_out_of_range_and_degenerate_pages():
    assert normalize_box([-10, -10, 700, 900], 594, 756) == [0, 0, 1000, 1000]
    assert normalize_box([1, 2, 3, 4], 0, 756) == [0, 0, 0, 0]
    assert normalize_box([1, 2, 3, 4], 594, 0) == [0, 0, 0, 0]


def test_box_text_joins_spans_across_lines():
    box = {
        "textlines": [
            {"spans": [{"text": "Hello"}, {"text": "world"}]},
            {"spans": [{"text": "again"}]},
            {"spans": []},
        ]
    }
    assert _box_text(box) == "Hello world again"


def test_box_text_handles_missing_keys():
    assert _box_text({}) == ""
    assert _box_text({"textlines": None}) == ""


def test_label_map_covers_known_classes():
    assert LABEL_MAP["section-header"] == "title"
    assert LABEL_MAP["page-header"] == "header"
    assert LABEL_MAP["page-footer"] == "footer"
    assert LABEL_MAP["picture"] == "picture"
    assert FIGURE_CONTAINABLE == {"text", "list-item"}


def test_missing_text_pages_detects_scans():
    image_doc = pymupdf.open(stream=make_image_pdf(), filetype="pdf")
    assert missing_text_pages(image_doc, [1]) == [1]
    image_doc.close()
    text_doc = pymupdf.open(stream=make_text_pdf(2), filetype="pdf")
    assert missing_text_pages(text_doc, [1, 2]) == []
    text_doc.close()


# ---------- figure crops ----------


@pytest.fixture(scope="module")
def page_render(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("render")
    doc = pymupdf.open(PDF_PATH)
    path = render_pdf_pages(doc, [1], 150, out)[0]
    doc.close()
    return path


def test_crop_data_uri_returns_png_payload(page_render):
    uri = crop_data_uri(page_render, [60, 600, 640, 880])
    assert uri is not None
    assert uri.startswith(DATA_URI_PREFIX)
    import base64

    payload = base64.b64decode(uri.split(",", 1)[1])
    assert payload.startswith(b"\x89PNG")


def test_crop_data_uri_degenerate_box_is_none(page_render):
    assert crop_data_uri(page_render, [10, 10, 10, 10]) is None
    assert crop_data_uri(page_render, [900, 900, 10, 10]) is None


def test_crop_data_uri_unreadable_path_is_none(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    assert crop_data_uri(bad, [0, 0, 100, 100]) is None
    assert crop_data_uri(tmp_path / "missing.png", [0, 0, 100, 100]) is None


def test_crop_data_uri_downscales_large_crops(page_render, monkeypatch):
    from PIL import Image

    import ocr_server.figures as figures

    monkeypatch.setattr(figures, "MAX_CROP_PX", 100)
    uri = crop_data_uri(page_render, [0, 0, 1000, 1000])
    assert uri is not None
    import base64
    import io

    image = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    assert max(image.size) <= 100


def test_main_sets_layout_model_env(monkeypatch):
    import sys

    import uvicorn

    import ocr_server.__main__ as cli

    seen: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: seen.update(target=a, kwargs=k))
    monkeypatch.setattr(
        sys,
        "argv",
        ["ocr-server", "--port", "9999", "--layout-model", "/tmp/custom.onnx"],
    )
    monkeypatch.delenv("OCR_LAYOUT_MODEL", raising=False)
    cli.main()
    assert seen["target"][0] == "ocr_server.api:app"
    assert seen["kwargs"]["port"] == 9999
    assert os.environ["OCR_LAYOUT_MODEL"] == "/tmp/custom.onnx"


def test_main_without_layout_model_keeps_env(monkeypatch):
    import sys

    import uvicorn

    import ocr_server.__main__ as cli

    seen: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: seen.update(kwargs=k))
    monkeypatch.setattr(sys, "argv", ["ocr-server"])
    monkeypatch.delenv("OCR_LAYOUT_MODEL", raising=False)
    cli.main()
    assert "OCR_LAYOUT_MODEL" not in os.environ
    assert seen["kwargs"]["port"] == 8300


# ---------- PP-DocLayout post-processing ----------


def _row(class_id: int, score: float, box: list[float]) -> list[float]:
    return [class_id, score, *box]


def test_clean_regions_keeps_only_capture_classes_and_score():
    rows = [
        _row(1, 0.9, [0, 0, 400, 400]),  # image -> kept
        _row(18, 0.9, [500, 0, 900, 400]),  # chart -> kept
        _row(2, 0.9, [0, 500, 400, 900]),  # text -> dropped
        _row(1, SCORE_MIN - 0.01, [500, 500, 900, 900]),  # low score -> dropped
        _row(99, 0.9, [0, 0, 10, 10]),  # unknown class id -> dropped
    ]
    kept = clean_regions(rows, page=1, width=1000, height=1000)
    assert [(r.kind, r.box) for r in kept] == [
        ("image", [0, 0, 400, 400]),
        ("chart", [500, 0, 900, 400]),
    ]


def test_clean_regions_drops_small_and_oversized_regions():
    rows = [
        _row(1, 0.9, [0, 0, MIN_DIM - 1, 500]),  # thin -> dropped
        _row(1, 0.9, [0, 0, 500, MIN_DIM - 1]),  # short -> dropped
        _row(1, 0.9, [0, 0, 1000, 1000]),  # whole page -> dropped
    ]
    assert clean_regions(rows, 1, 1000, 1000) == []


def test_clean_regions_dedupes_contained_and_overlapping():
    rows = [
        _row(1, 0.9, [100, 100, 500, 500]),  # small sub-panel
        _row(18, 0.8, [0, 0, 1000, 600]),  # bigger surrounding region
        _row(1, 0.7, [0, 0, 100, 100]),  # tiny, below min dim
    ]
    kept = clean_regions(rows, 1, 1000, 1000)
    assert len(kept) == 1
    assert kept[0].box == [0, 0, 1000, 600]
    assert kept[0].kind == "chart"


def test_clean_regions_area_share_boundary():
    rows = [_row(1, 0.9, [0, 0, 1000, int(1000 * (MAX_AREA_SHARE + 0.01))])]
    assert clean_regions(rows, 1, 1000, 1000) == []
    rows = [_row(1, 0.9, [0, 0, 1000, int(1000 * (MAX_AREA_SHARE - 0.01))])]
    assert len(clean_regions(rows, 1, 1000, 1000)) == 1


def test_clamp_box_scales_and_sorts():
    assert _clamp_box([0, 0, 500, 1000], 1000, 1000) == [0, 0, 500, 1000]
    assert _clamp_box([500, 1000, 0, 0], 1000, 1000) == [0, 0, 500, 1000]
    assert _clamp_box([-50, -50, 1200, 1200], 1000, 1000) == [0, 0, 1000, 1000]
    assert _clamp_box([1, 2, 3, 4], 0, 10) == [0, 0, 0, 0]


def test_iou_and_center_inside_helpers():
    assert _iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert _iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    assert _center_inside([0, 0, 10, 10], [-5, -5, 20, 20])
    assert not _center_inside([0, 0, 10, 10], [20, 20, 30, 30])


# ---------- merge ----------


def _native(label: str, box: list[int], text: str = "body", order: int = 0) -> NativeBox:
    return NativeBox(page=1, label=label, box=box, text=text, order=order)


def _region(box: list[int]) -> FigureRegion:
    return FigureRegion(page=1, box=box, kind="image", score=0.9)


def test_merge_replaces_matching_picture_with_figure():
    native = [
        _native("header", [0, 0, 1000, 40], "running head"),
        _native("picture", [100, 100, 500, 500], ""),
        _native("text", [100, 600, 900, 700], "body"),
    ]
    spans, warnings = merge_page(native, [(_region([100, 100, 500, 500]), "data:x")], 1)
    assert warnings == []
    assert [s.label for s in spans] == ["header", "image", "text"]
    assert spans[1].image == "data:x"
    assert spans[1].box == [100, 100, 500, 500]
    assert spans[1].text == ""


def test_merge_emits_multi_matched_region_once():
    native = [
        _native("picture", [0, 0, 1000, 60], ""),
        _native("picture", [0, 100, 1000, 900], ""),
    ]
    spans, _ = merge_page(native, [(_region([0, 50, 1000, 950]), "data:x")], 1)
    assert [s.label for s in spans] == ["image"]


def test_merge_appends_unmatched_figures_in_reading_order():
    native = [_native("text", [100, 700, 900, 800], "body")]
    figures = [
        (_region([100, 400, 900, 600]), "data:b"),
        (_region([100, 100, 900, 300]), "data:a"),
    ]
    spans, _ = merge_page(native, figures, 1)
    assert [s.image for s in spans if s.label == "image"] == ["data:a", "data:b"]
    assert [s.label for s in spans] == ["text", "image", "image"]


def test_merge_relabels_content_inside_figures():
    native = [
        _native("text", [200, 200, 400, 300], "axis label"),
        _native("caption", [200, 250, 400, 280], "fig 1"),
        _native("text", [50, 50, 100, 60], "outside"),
    ]
    figures = [(_region([100, 100, 500, 500]), None)]
    spans, warnings = merge_page(native, figures, 1)
    labels = {s.text: s.label for s in spans}
    assert labels["axis label"] == "figure_text"
    assert labels["fig 1"] == "caption"  # captions are never relabeled
    assert labels["outside"] == "text"
    # Unmatched region appended with a warning (crop failed -> still a span).
    assert warnings == ["figure crop failed on page 1"]
    figure_spans = [s for s in spans if s.label == "image"]
    assert len(figure_spans) == 1 and figure_spans[0].image is None


def test_select_figures_requires_native_corroboration():
    native = [_native("picture", [100, 100, 500, 500])]
    aligned = _region([110, 110, 490, 490])
    text_region = _region([0, 600, 1000, 1000])
    assert select_figures([aligned, text_region], native) == [aligned]
    assert select_figures([text_region], []) == []


def test_figure_span_shape():
    span = _figure_span(3, _region([1, 2, 3, 4]), "data:x")
    assert (span.page, span.label, span.text, span.image) == (3, "image", "", "data:x")
    # Box is copied, not aliased.
    assert span.box == [1, 2, 3, 4]


def test_picture_matches_by_iou_or_containment():
    assert _picture_matches([100, 100, 500, 500], [110, 110, 490, 490])
    assert _picture_matches([0, 0, 100, 100], [50, 50, 900, 900])
    assert _picture_matches([800, 800, 900, 900], [0, 0, 1000, 1000])
    assert not _picture_matches([0, 0, 10, 10], [500, 500, 600, 600])


def test_capture_classes_are_figures_only():
    assert CAPTURE_CLASSES == {"image", "chart"}
    assert DEDUPE_IOU > 0.5
