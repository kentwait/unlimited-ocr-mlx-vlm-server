"""Tests: parse_pages_spec, PDF rendering, and API endpoints (fake engine)."""

from __future__ import annotations

import io
import time

import pymupdf
import pytest
from fastapi.testclient import TestClient

from ocr_server.api import app, holder
from ocr_server.fake import FakeEngine
from ocr_server.pages import parse_pages_spec


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("OCR_FAKE_ENGINE", "1")
    holder.load()
    with TestClient(app) as c:
        yield c
    holder.engine = None


def _pdf_bytes(n_pages: int) -> bytes:
    doc = pymupdf.open()
    for i in range(n_pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"Test page {i + 1}")
    return doc.tobytes()


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 100, 50)).save(buf, "PNG")
    return buf.getvalue()


# ---------- pages spec ----------


def test_pages_all():
    assert parse_pages_spec(None, 5) == [1, 2, 3, 4, 5]


def test_pages_ranges_and_singles():
    assert parse_pages_spec("1-3,5", 5) == [1, 2, 3, 5]


def test_pages_out_of_range():
    with pytest.raises(ValueError):
        parse_pages_spec("1-3,9", 5)


def test_pages_malformed():
    with pytest.raises(ValueError):
        parse_pages_spec("abc", 5)


def test_pages_empty_range():
    with pytest.raises(ValueError):
        parse_pages_spec("5-2", 5)


# ---------- PDF rendering ----------


def test_render_pdf_pages(tmp_path):
    from ocr_server.pdfrender import render_pdf_pages

    doc = pymupdf.open(stream=_pdf_bytes(3), filetype="pdf")
    paths = render_pdf_pages(doc, [1, 3], 100, tmp_path)
    assert [p.name for p in paths] == ["page-0001.png", "page-0003.png"]
    assert all(p.stat().st_size > 0 for p in paths)
    doc.close()


# ---------- API (fake engine) ----------


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "fake"
    assert body["model_loaded"] is True


def test_parse_image(client):
    r = client.post(
        "/parse/image",
        files={"file": ("t.png", _png_bytes(), "image/png")},
        data={"prompt": "document parsing."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "image"
    assert body["results"][0]["markdown"].startswith("MOCK(")
    assert body["results"][0]["elapsed_s"] >= 0


def test_parse_image_rejects_bad_type(client):
    r = client.post(
        "/parse/image",
        files={"file": ("t.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 415


def test_parse_pdf_all_pages(client):
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(3), "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "pdf"
    assert body["n_pages"] == 3
    assert [p["page"] for p in body["results"]] == [1, 2, 3]
    assert all(p["markdown"].startswith("MOCK(page-000") for p in body["results"])


def test_parse_pdf_subset(client):
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(5), "application/pdf")},
        data={"pages": "2-3,5"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["page"] for p in body["results"]] == [2, 3, 5]


def test_parse_pdf_bad_pages(client):
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(3), "application/pdf")},
        data={"pages": "1-3,9"},
    )
    assert r.status_code == 400
    assert "out of range" in r.json()["detail"]


def test_parse_pdf_bad_dpi(client):
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(1), "application/pdf")},
        data={"dpi": "600"},
    )
    assert r.status_code == 400


def test_parse_pdf_invalid_prompt(client):
    r = client.post(
        "/parse/image",
        files={"file": ("t.png", _png_bytes(), "image/png")},
        data={"prompt": "x" * 250},
    )
    assert r.status_code == 400


def test_job_flow(client):
    r = client.post(
        "/parse/jobs",
        files={"file": ("t.pdf", _pdf_bytes(2), "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    assert r.json()["status"] in ("pending", "running")

    for _ in range(100):
        s = client.get(f"/parse/jobs/{job_id}")
        assert s.status_code == 200
        if s.json()["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    body = s.json()
    assert body["status"] == "done", body
    assert body["result"]["n_pages"] == 2


def test_job_unknown_id(client):
    r = client.get("/parse/jobs/deadbeef")
    assert r.status_code == 404
