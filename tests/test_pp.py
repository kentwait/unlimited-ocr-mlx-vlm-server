"""PP-DocLayout-S: vendored model pin and real detection behavior."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest

from ocr_server.pdfrender import render_pdf_pages
from ocr_server.pp_layout import (
    CAPTURE_CLASSES,
    MODEL_PATH,
    SCORE_MIN,
    LayoutModel,
)

from conftest import PDF_PATH

#: Pinned digest of the vendored export (see models/MODEL_INFO.md).
EXPECTED_SHA256 = "33688dbee1c23e34b81777e97cb428eb40f24b242c02b5f623484959e830aec8"


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    out = tmp_path_factory.mktemp("pp-render")
    doc = pymupdf.open(PDF_PATH)
    paths = render_pdf_pages(doc, [1, 2], 150, out)
    doc.close()
    return {1: paths[0], 2: paths[1]}


def test_vendored_model_exists_and_sha_matches():
    assert MODEL_PATH.is_file()
    digest = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    assert digest == EXPECTED_SHA256


def test_layout_model_lazy_load_and_name(tmp_path):
    model = LayoutModel()
    assert model.name == "pp_doclayout_s"
    assert model.loaded is False
    assert model.load() is model
    assert model.loaded is True
    # Override path is honored (nonexistent here; only the path is checked).
    assert LayoutModel(tmp_path / "x.onnx").name == "x"


def test_detect_finds_page_one_figure(rendered):
    model = LayoutModel().load()
    regions = model.detect(rendered[1], 1)
    assert regions, "expected at least one figure region on page 1"
    for region in regions:
        assert region.kind in CAPTURE_CLASSES
        assert region.score >= SCORE_MIN
        x1, y1, x2, y2 = region.box
        assert 0 <= x1 < x2 <= 1000
        assert 0 <= y1 < y2 <= 1000
    # The big two-panel figure occupies the lower half of page 1.
    assert any(region.box[1] > 400 for region in regions)


def test_detect_text_page_has_no_regions(rendered):
    model = LayoutModel().load()
    assert model.detect(rendered[2], 2) == []


def test_detect_unreadable_image_raises():
    model = LayoutModel().load()
    with pytest.raises(Exception):
        model.detect(Path("/nonexistent/page.png"), 1)
