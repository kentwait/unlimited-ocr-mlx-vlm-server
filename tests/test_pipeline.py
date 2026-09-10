"""End-to-end pipeline tests on the committed fixture (real engines, no mocks)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from ocr_server.pipeline import parse_pdf
from ocr_server.pp_layout import LayoutModel
from ocr_server.schemas import JobStatus

from conftest import PDF_PATH, make_image_pdf, make_text_pdf

#: Pages with real figures in the fixture (verified visually).
FIGURE_PAGES = {1, 3, 5, 6, 8, 9}


@pytest.fixture(scope="module")
def model() -> LayoutModel:
    return LayoutModel().load()


@pytest.fixture()
def fixture_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "altemose2022.pdf"
    path.write_bytes(PDF_PATH.read_bytes())
    return path


def _spans(page_result) -> list[dict]:
    return [json.loads(line) for line in page_result.spans_jsonl.splitlines()]


def test_full_document_figures_and_labels(fixture_pdf, model):
    response = parse_pdf(fixture_pdf, pages="all", dpi=150, layout_model=model)
    assert response.kind == "pdf"
    assert response.n_pages == 13
    assert response.total_elapsed_s >= 0

    figure_pages = set()
    for page in response.results:
        assert page.warnings == []
        spans = _spans(page)
        assert spans, f"page {page.page} produced no spans"

        ids = [span["id"] for span in spans]
        assert ids == [f"p{page.page}-{i + 1}" for i in range(len(spans))]
        assert len(set(ids)) == len(ids)
        assert all(span["page"] == page.page for span in spans)
        assert not any(span["label"] == "picture" for span in spans)

        figures = [span for span in spans if "image" in span]
        if figures:
            figure_pages.add(page.page)
            for figure in figures:
                assert figure["label"] == "image"
                assert figure["image"].startswith("data:image/png;base64,")
                assert len(figure["image"]) > 1000
                # page + box stay on the span for reconstitution.
                assert figure["page"] == page.page
                assert len(figure["box"]) == 4

    assert figure_pages == FIGURE_PAGES

    # Furniture is labeled and content survives across the document.
    all_spans = [span for page in response.results for span in _spans(page)]
    assert sum(1 for s in all_spans if s["label"] == "header") >= 10
    assert sum(1 for s in all_spans if s["label"] == "footer") >= 20
    assert sum(1 for s in all_spans if s["label"] == "text") > 50
    assert any(s["label"] == "title" for s in all_spans)


def test_subset_pages_only(fixture_pdf, model):
    response = parse_pdf(fixture_pdf, pages="2", dpi=150, layout_model=model)
    assert [page.page for page in response.results] == [2]
    assert not any("image" in span for span in _spans(response.results[0]))


def test_job_progress_is_reported(fixture_pdf, model):
    job = JobStatus(job_id="x", status="running", created_at=0.0)
    response = parse_pdf(fixture_pdf, pages="1-2", dpi=150, layout_model=model, job=job)
    assert job.phase == "parse"
    assert job.pages_total == 2
    assert job.pages_done == 2
    assert len(response.results) == 2


def test_crop_failure_degrades_with_warning(fixture_pdf, model, monkeypatch):
    import ocr_server.pipeline as pipeline

    monkeypatch.setattr(pipeline, "crop_data_uri", lambda *a, **k: None)
    response = parse_pdf(fixture_pdf, pages="1", dpi=150, layout_model=model)
    page = response.results[0]
    figures = [span for span in _spans(page) if span["label"] == "image"]
    assert figures and "image" not in figures[0]
    assert page.warnings == ["figure crop failed on page 1"]


def test_text_pdf_parses_without_figures(tmp_path, model):
    path = tmp_path / "text.pdf"
    path.write_bytes(make_text_pdf(1))
    response = parse_pdf(path, pages="all", dpi=150, layout_model=model)
    spans = _spans(response.results[0])
    assert spans
    assert all(span["label"] != "image" for span in spans)
    assert any("Test page 1" in span["text"] for span in spans)


def test_scanned_pdf_errors_with_page_list(tmp_path, model):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_image_pdf())
    with pytest.raises(HTTPException) as excinfo:
        parse_pdf(path, pages="all", dpi=150, layout_model=model)
    assert excinfo.value.status_code == 400
    assert "no text layer on page(s) 1" in excinfo.value.detail
    assert "digital-born" in excinfo.value.detail


def test_too_many_pages_rejected(tmp_path, model):
    path = tmp_path / "many.pdf"
    path.write_bytes(make_text_pdf(51))
    with pytest.raises(HTTPException) as excinfo:
        parse_pdf(path, pages="all", dpi=150, layout_model=model)
    assert excinfo.value.status_code == 400
    assert "max 50" in excinfo.value.detail


def test_bad_pages_spec_rejected(fixture_pdf, model):
    with pytest.raises(HTTPException) as excinfo:
        parse_pdf(fixture_pdf, pages="1-100", dpi=150, layout_model=model)
    assert excinfo.value.status_code == 400
    assert "out of range" in excinfo.value.detail


def test_bad_dpi_rejected(fixture_pdf, model):
    with pytest.raises(HTTPException) as excinfo:
        parse_pdf(fixture_pdf, pages="1", dpi=600, layout_model=model)
    assert excinfo.value.status_code == 400
    assert "dpi must be 72-300" in excinfo.value.detail


def test_unreadable_pdf_rejected(tmp_path, model):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"definitely not a pdf")
    with pytest.raises(HTTPException) as excinfo:
        parse_pdf(path, pages="all", dpi=150, layout_model=model)
    assert excinfo.value.status_code == 400
    assert "cannot open PDF" in excinfo.value.detail


def test_extract_failure_maps_to_400(fixture_pdf, model, monkeypatch):
    import ocr_server.pipeline as pipeline

    def boom(*args, **kwargs):
        raise RuntimeError("layout exploded")

    monkeypatch.setattr(pipeline, "extract_boxes", boom)
    with pytest.raises(HTTPException) as excinfo:
        parse_pdf(fixture_pdf, pages="1", dpi=150, layout_model=model)
    assert excinfo.value.status_code == 400
    assert "cannot extract text layout" in excinfo.value.detail


def test_extract_http_exception_passes_through(fixture_pdf, model, monkeypatch):
    import ocr_server.pipeline as pipeline

    def boom(*args, **kwargs):
        raise HTTPException(418, "teapot layout")

    monkeypatch.setattr(pipeline, "extract_boxes", boom)
    with pytest.raises(HTTPException) as excinfo:
        parse_pdf(fixture_pdf, pages="1", dpi=150, layout_model=model)
    assert excinfo.value.status_code == 418
    assert excinfo.value.detail == "teapot layout"


def test_render_failure_maps_to_400(fixture_pdf, model, monkeypatch):
    import ocr_server.pipeline as pipeline

    def boom(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(pipeline, "render_pdf_pages", boom)
    with pytest.raises(HTTPException) as excinfo:
        parse_pdf(fixture_pdf, pages="1", dpi=150, layout_model=model)
    assert excinfo.value.status_code == 400
    assert "render failed" in excinfo.value.detail
