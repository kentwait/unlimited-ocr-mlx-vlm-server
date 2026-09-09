"""Full pipeline with stubbed LLM: fake OCR engine + canned checker output.

Covers the cleanup/reflow branches that need no MLX weights by stubbing
CleanupEngine._generate/_load. Real weight paths stay pragma-marked.
"""

from __future__ import annotations

import time

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from ocr_server import api as api_mod
from ocr_server import cleanup as cleanup_mod
from ocr_server.api import app, holder
from ocr_server.fake import FakeEngine

from test_api import _pdf_bytes, _png_bytes

TOKEN = "pipeline-token"


@pytest.fixture()
def stubbed_llm(monkeypatch):
    monkeypatch.setattr(cleanup_mod.CleanupEngine, "load", lambda self: None)
    monkeypatch.setattr(
        cleanup_mod.CleanupEngine,
        "_generate",
        lambda self, prompt, max_tokens: ("canonical output", 5, False),
    )
    yield


@pytest.fixture()
def client(monkeypatch, stubbed_llm):
    monkeypatch.setenv("OCR_FAKE_ENGINE", "1")
    monkeypatch.setenv("OCR_INTERNAL_TOKEN", TOKEN)
    holder.load()
    with TestClient(app) as c:
        # Lifespan re-loads the holder on entry: flip to the stubbed-LLM
        # configuration only after it runs.
        monkeypatch.setattr(api_mod, "_cleanup_engine", None)
        holder.is_fake = False
        holder.engine = FakeEngine()
        holder.engine.load()
        yield c
    holder.engine = None
    holder.is_fake = False
    monkeypatch.setattr(api_mod, "_cleanup_engine", None)


def test_pdf_pipeline_with_cleanup(client):
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(2), "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_pages"] == 2
    page = body["results"][0]
    assert page["markdown"] == "canonical output"
    assert page["cleanup_method"] == "ocr-llm-proofread"
    assert page["corrections"]["formatting_only"] is False
    assert body["furniture"]["template"] is None


def test_image_pipeline_with_cleanup(client):
    r = client.post(
        "/parse/image",
        files={"file": ("t.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"][0]["cleanup_method"] == "ocr-llm-proofread"


def test_reflow_real_path_with_audit(client):
    r = client.post(
        "/internal/reflow",
        json={
            "contract_version": 1,
            "journal": "science",
            "markdown": "# Title\n\nSome body text here.",
            "prompt_override": "Reflow {{journal}}:\n\n{{markdown}}",
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "reflow+journal-prompt"
    assert body["markdown"] == "canonical output"
    assert body["corrections"]["formatting_only"] is False
    assert "Qwen" in (body["model"] or "")


def test_reflow_loopback_guard_unit():
    def scope(host):
        return {
            "type": "http",
            "method": "POST",
            "path": "/internal/reflow",
            "headers": [(b"authorization", b"Bearer x")],
            "client": (host, 1234),
        }

    import os

    from fastapi import HTTPException

    os.environ["OCR_INTERNAL_TOKEN"] = "t"
    try:
        with pytest.raises(HTTPException) as exc:
            api_mod._require_internal_access(Request(scope("192.168.1.5")))
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            api_mod._require_internal_access(Request({**scope("x"), "client": None}))
        assert exc.value.status_code == 403
    finally:
        del os.environ["OCR_INTERNAL_TOKEN"]


def test_root_and_upload_validation(client):
    assert client.get("/").json()["service"] == "unlimited-ocr-server"
    r = client.post(
        "/parse/pdf",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 400
    r = client.post(
        "/parse/image",
        files={"file": ("t.txt", b"nope", "text/plain")},
        data={},
    )
    assert r.status_code == 415


def test_oversize_upload_rejected(client, monkeypatch):
    monkeypatch.setattr(api_mod, "MAX_UPLOAD_BYTES", 10)
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(1), "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 413


def test_job_flow_with_cleanup_tracks_phase(client):
    r = client.post(
        "/parse/jobs",
        files={"file": ("t.pdf", _pdf_bytes(2), "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        s = client.get(f"/parse/jobs/{job_id}")
        if s.json()["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    body = s.json()
    assert body["status"] == "done", body
    assert body["result"]["results"][0]["cleanup_method"] == "ocr-llm-proofread"


def test_infer_defaults_to_holder_engine(client, tmp_path):
    import asyncio
    from pathlib import Path

    from PIL import Image

    from ocr_server.schemas import InferenceParams

    img = tmp_path / "probe.png"
    Image.new("RGB", (8, 8)).save(img)
    text, _, _ = asyncio.run(
        api_mod._infer_image_path(img, InferenceParams(prompt="document parsing."))
    )
    assert "MOCK" in text


def test_parse_pdf_path_rejects_bad_furniture(client, tmp_path):
    import asyncio

    from ocr_server.schemas import InferenceParams

    pdf = tmp_path / "t.pdf"
    pdf.write_bytes(_pdf_bytes(1))
    with pytest.raises(Exception, match="unknown furniture mode"):
        asyncio.run(
            api_mod._parse_pdf_path(
                pdf,
                pages="all",
                dpi=100,
                params=InferenceParams(prompt="document parsing."),
                furniture="bogus",
            )
        )


def test_parse_pdf_path_tracks_cleanup_progress(client, tmp_path):
    import asyncio
    import time

    from ocr_server.schemas import InferenceParams, JobStatus

    pdf = tmp_path / "t.pdf"
    pdf.write_bytes(_pdf_bytes(2))
    job = JobStatus(job_id="x", status="running", created_at=time.time())
    resp = asyncio.run(
        api_mod._parse_pdf_path(
            pdf,
            pages="all",
            dpi=100,
            params=InferenceParams(prompt="document parsing."),
            journal="nature",
            job=job,
        )
    )
    assert resp.journal == "nature"
    assert job.phase == "cleanup"
    assert job.pages_total == 2
    # Fresh per-stage count: every page checked, none beyond the total.
    assert job.pages_done == 2


def test_image_inference_failure_is_500(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("gpu gone")

    monkeypatch.setattr(FakeEngine, "infer_image_file", boom)
    r = client.post(
        "/parse/image",
        files={"file": ("t.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 500
