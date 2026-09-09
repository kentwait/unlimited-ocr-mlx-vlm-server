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


def test_parse_pdf_rejects_unreadable_file(client):
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", b"not a pdf at all", "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 400


def test_parse_pdf_rejects_too_many_pages(client):
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(55), "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 400
    assert "max" in r.json()["detail"]


def test_parse_pdf_maps_render_failure(client, monkeypatch):
    from ocr_server import api as api_mod

    def boom(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(api_mod, "render_pdf_pages", boom)
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(1), "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 400
    assert "render failed" in r.json()["detail"]


def test_job_surfaces_parse_error(client):
    r = client.post(
        "/parse/jobs",
        files={"file": ("t.pdf", _pdf_bytes(2), "application/pdf")},
        data={"pages": "1-3,9"},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        s = client.get(f"/parse/jobs/{job_id}")
        if s.json()["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    body = s.json()
    assert body["status"] == "error"
    assert "out of range" in (body["error"] or "")


def test_job_surfaces_unexpected_error(client, monkeypatch):
    from ocr_server import api as api_mod

    # Raise past the render try/except (which converts to HTTPException) so
    # the job's generic-Exception handler is the one that records the error.
    def boom(*args, **kwargs):
        raise RuntimeError("furniture exploded")

    monkeypatch.setattr(api_mod, "apply_furniture", boom)
    r = client.post(
        "/parse/jobs",
        files={"file": ("t.pdf", _pdf_bytes(1), "application/pdf")},
        data={"pages": "all"},
    )
    job_id = r.json()["job_id"]
    for _ in range(100):
        s = client.get(f"/parse/jobs/{job_id}")
        if s.json()["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    body = s.json()
    assert body["status"] == "error"
    assert "furniture exploded" in (body["error"] or "")


def test_image_http_error_passes_through(client, monkeypatch):
    from fastapi import HTTPException

    from ocr_server.fake import FakeEngine

    def fail(*args, **kwargs):
        raise HTTPException(status_code=400, detail="bad image")

    monkeypatch.setattr(FakeEngine, "infer_image_file", fail)
    r = client.post(
        "/parse/image",
        files={"file": ("t.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "bad image"


def test_cleanup_engine_disabled_env(monkeypatch):
    from ocr_server import api as api_mod

    monkeypatch.setattr(api_mod.holder, "is_fake", False)
    monkeypatch.setenv("OCR_CLEANUP", "0")
    monkeypatch.setattr(api_mod, "_cleanup_engine", None)
    assert api_mod._get_cleanup_engine() is None
    monkeypatch.setattr(api_mod, "_cleanup_engine", None)


def test_prompt_registry_loads_once(client, monkeypatch):
    from ocr_server import api as api_mod
    from ocr_server.prompts import PromptRegistry

    calls = []
    orig_load = PromptRegistry.load
    monkeypatch.setattr(
        PromptRegistry, "load", lambda self: (calls.append(1), orig_load(self))
    )
    monkeypatch.setattr(api_mod, "_prompt_registry", None)
    api_mod._get_prompt_registry()
    api_mod._get_prompt_registry()
    assert len(calls) == 1
    monkeypatch.setattr(api_mod, "_prompt_registry", None)


# ---------- furniture (generic-only; journal templates live in Paperhub) ----------


def test_parse_pdf_furniture_none_ok(client):
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(2), "application/pdf")},
        data={"pages": "all", "furniture": "none"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["furniture"]["removed_total"] == 0


def test_parse_pdf_furniture_rejects_journal_template(client):
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(1), "application/pdf")},
        data={"pages": "all", "furniture": "nature"},
    )
    assert r.status_code == 400
    assert "auto" in r.json()["detail"]


def test_parse_jobs_furniture_rejects_before_creating_job(client):
    r = client.post(
        "/parse/jobs",
        files={"file": ("t.pdf", _pdf_bytes(1), "application/pdf")},
        data={"pages": "all", "furniture": "pmc"},
    )
    assert r.status_code == 400


def test_apply_furniture_rejects_unknown_mode():
    from ocr_server.furniture import apply_furniture

    with pytest.raises(ValueError, match="unknown furniture mode"):
        apply_furniture([[]], template="science")


def test_apply_furniture_none_is_noop():
    from ocr_server.furniture import apply_furniture
    from ocr_server.spans import Span

    spans = [[Span(page=1, label="text", box=[0, 0, 100, 10], text="Nature")]]
    info = apply_furniture(spans, template="none")
    assert info["template"] is None
    assert info["removed_total"] == 0
    assert spans[0][0].label == "text"


# ---------- internal reflow (token + loopback guarded, undocumented) ----------

_TEST_TOKEN = "test-internal-token"


def _reflow(client, body, token=_TEST_TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/internal/reflow", json=body, headers=headers)


def test_reflow_missing_token_config_is_404(client, monkeypatch):
    monkeypatch.delenv("OCR_INTERNAL_TOKEN", raising=False)
    r = client.post("/internal/reflow", json={"markdown": "# hi"})
    assert r.status_code == 404


def test_reflow_rejects_bad_token(client, monkeypatch):
    monkeypatch.setenv("OCR_INTERNAL_TOKEN", _TEST_TOKEN)
    assert _reflow(client, {"markdown": "# hi"}, token="wrong").status_code == 401
    assert _reflow(client, {"markdown": "# hi"}, token=None).status_code == 401


def test_reflow_fake_echo_round_trip(client, monkeypatch):
    monkeypatch.setenv("OCR_INTERNAL_TOKEN", _TEST_TOKEN)
    r = _reflow(
        client,
        {
            "contract_version": 1,
            "journal": "nature",
            "markdown": "  # Title\n\nBody.  ",
            "prompt_override": "Reflow for {{journal}}:\n\n{{markdown}}",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contract_version"] == 1
    assert body["journal"] == "nature"
    assert body["markdown"] == "# Title\n\nBody."
    assert body["method"] == "fake-echo"


def test_reflow_rejects_contract_mismatch(client, monkeypatch):
    monkeypatch.setenv("OCR_INTERNAL_TOKEN", _TEST_TOKEN)
    r = _reflow(client, {"contract_version": 999, "markdown": "# hi"})
    assert r.status_code == 400
    assert "contract_version" in r.json()["detail"]


def test_reflow_hidden_from_openapi(client):
    assert "/internal/reflow" not in client.get("/openapi.json").json()["paths"]
