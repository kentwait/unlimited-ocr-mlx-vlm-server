"""API endpoint tests. The pipeline is deterministic and weight-free, so the
real server runs in-process — no fake-engine mode exists anymore."""

from __future__ import annotations

import json
import time

from conftest import make_image_pdf, make_text_pdf


def _post_pdf(client, data: bytes, **fields):
    return client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", data, "application/pdf")},
        data=fields,
    )


def _submit_job(client, data: bytes, **fields):
    return client.post(
        "/parse/jobs",
        files={"file": ("t.pdf", data, "application/pdf")},
        data=fields,
    )


def _wait_for_job(client, job_id: str, attempts: int = 200):
    for _ in range(attempts):
        status = client.get(f"/parse/jobs/{job_id}")
        if status.json()["status"] in ("done", "error"):
            return status.json()
        time.sleep(0.02)
    raise AssertionError("job did not settle")


# ---------- health / root ----------


def test_health(client):
    body = client.get("/health").json()
    assert body == {
        "status": "ok",
        "parser": "pymupdf4llm",
        "layout_model": "pp_doclayout_s",
    }


def test_root_lists_endpoints(client):
    body = client.get("/").json()
    assert body["service"] == "paperhub-parser"
    assert set(body["endpoints"]) == {"/health", "/parse/pdf", "/parse/jobs"}


def test_removed_endpoints_are_gone(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/parse/image" not in paths
    assert "/internal/reflow" not in paths


# ---------- /parse/pdf ----------


def test_parse_fixture_page_with_figure(client, altemose_bytes):
    response = _post_pdf(client, altemose_bytes, pages="1", dpi="150")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "pdf"
    assert body["n_pages"] == 1
    page = body["results"][0]
    assert page["elapsed_s"] >= 0
    assert page["warnings"] == []
    spans = [json.loads(line) for line in page["spans_jsonl"].splitlines()]
    figures = [span for span in spans if span["label"] == "image"]
    assert len(figures) == 1
    assert figures[0]["image"].startswith("data:image/png;base64,")
    assert figures[0]["id"].startswith("p1-")


def test_parse_subset(client, altemose_bytes):
    response = _post_pdf(client, altemose_bytes, pages="2-3", dpi="150")
    assert response.status_code == 200, response.text
    assert [page["page"] for page in response.json()["results"]] == [2, 3]


def test_parse_bad_pages_spec(client):
    response = _post_pdf(client, make_text_pdf(2), pages="1-9")
    assert response.status_code == 400
    assert "out of range" in response.json()["detail"]


def test_parse_bad_dpi(client, altemose_bytes):
    response = _post_pdf(client, altemose_bytes, pages="1", dpi="600")
    assert response.status_code == 400
    assert "dpi must be 72-300" in response.json()["detail"]


def test_parse_empty_upload(client):
    response = _post_pdf(client, b"")
    assert response.status_code == 400
    assert "empty upload" in response.json()["detail"]


def test_parse_unsupported_type(client):
    response = client.post(
        "/parse/pdf",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={},
    )
    assert response.status_code == 415


def test_parse_unreadable_pdf(client):
    response = _post_pdf(client, b"not a pdf")
    assert response.status_code == 400
    assert "cannot open PDF" in response.json()["detail"]


def test_parse_scanned_pdf_rejected(client):
    response = _post_pdf(client, make_image_pdf(), pages="all")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "no text layer on page(s) 1" in detail
    assert "digital-born" in detail


def test_parse_too_many_pages(client):
    response = _post_pdf(client, make_text_pdf(51), pages="all")
    assert response.status_code == 400
    assert "max 50" in response.json()["detail"]


def test_upload_size_limit(client, monkeypatch):
    from ocr_server import api as api_mod

    monkeypatch.setattr(api_mod, "MAX_UPLOAD_BYTES", 10)
    response = _post_pdf(client, make_text_pdf(1))
    assert response.status_code == 413


# ---------- /parse/jobs ----------


def test_job_flow_reports_progress_and_result(client):
    submitted = _submit_job(client, make_text_pdf(2), pages="all")
    assert submitted.status_code == 202, submitted.text
    body = submitted.json()
    assert body["status"] in ("pending", "running")

    final = _wait_for_job(client, body["job_id"])
    assert final["status"] == "done", final
    assert final["error"] is None
    assert final["pages_total"] == 2
    assert final["pages_done"] == 2
    assert final["phase"] == "parse"
    assert final["result"]["n_pages"] == 2
    assert final["started_at"] is not None and final["finished_at"] is not None


def test_job_surfaces_parse_errors(client):
    submitted = _submit_job(client, make_image_pdf(), pages="all")
    job_id = submitted.json()["job_id"]
    final = _wait_for_job(client, job_id)
    assert final["status"] == "error"
    assert "no text layer" in final["error"]
    assert final["result"] is None


def test_job_surfaces_unexpected_errors(client, monkeypatch):
    from ocr_server import api as api_mod

    def boom(*args, **kwargs):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(api_mod, "run_parse_pdf", boom)
    submitted = _submit_job(client, make_text_pdf(1), pages="all")
    final = _wait_for_job(client, submitted.json()["job_id"])
    assert final["status"] == "error"
    assert "pipeline exploded" in final["error"]


def test_job_unknown_id(client):
    assert client.get("/parse/jobs/deadbeef").status_code == 404
