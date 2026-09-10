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


def _echo_fragments(self, prompt, max_tokens):
    """Stub LLM: echo the numbered fragment block back unchanged."""
    start = prompt.index("<<<FRAGMENTS") + len("<<<FRAGMENTS\n")
    end = prompt.index("FRAGMENTS>>>")
    return prompt[start:end].strip(), 5, False


def _canonical_output(self, prompt, max_tokens):
    """Stub LLM: fixed non-fragment output (for reflow paths)."""
    return "canonical output", 5, False


@pytest.fixture()
def stubbed_llm(monkeypatch):
    monkeypatch.setattr(cleanup_mod.SupportEngine, "load", lambda self: None)
    # Canned 2-column profile: exercises hint injection + filter plumbing
    # without weights (filter no-ops on box-less MOCK spans).
    from ocr_server.layout import LayoutProfile

    def _canned_scan(self, image_path, page, max_tokens=384):
        return LayoutProfile(page=page, columns="2", confidence=0.9)

    monkeypatch.setattr(cleanup_mod.SupportEngine, "scan_layout", _canned_scan)
    yield


@pytest.fixture()
def client(monkeypatch, stubbed_llm):
    monkeypatch.setenv("OCR_FAKE_ENGINE", "1")
    monkeypatch.setenv("OCR_INTERNAL_TOKEN", TOKEN)
    holder.load()
    with TestClient(app) as c:
        # Lifespan re-loads the holder on entry: flip to the stubbed-LLM
        # configuration only after it runs.
        monkeypatch.setattr(api_mod, "_support_engine", None)
        holder.is_fake = False
        holder.engine = FakeEngine()
        holder.engine.load()
        yield c
    holder.engine = None
    holder.is_fake = False
    monkeypatch.setattr(api_mod, "_support_engine", None)


def test_pdf_pipeline_support_disabled_runs_unhinted(client, monkeypatch):
    # OCR_SUPPORT=0: no pre-scan (layout None), no correction — the raw
    # OCR text renders verbatim.
    monkeypatch.setenv("OCR_SUPPORT", "0")
    monkeypatch.setattr(api_mod, "_support_engine", None)
    try:
        r = client.post(
            "/parse/pdf",
            files={"file": ("t.pdf", _pdf_bytes(1), "application/pdf")},
            data={"pages": "all"},
        )
        assert r.status_code == 200, r.text
        page = r.json()["results"][0]
        assert page["markdown"] == "MOCK(page-0001.png|document parsing.)"
        assert page["layout"] is None
        assert page["support_method"] is None
    finally:
        monkeypatch.setattr(api_mod, "_support_engine", None)


def test_pdf_pipeline_with_support(client, monkeypatch):
    # Support echoes fragments: corrected spans == original spans, so the
    # markdown must be exactly the deterministic render of those spans.
    monkeypatch.setattr(cleanup_mod.SupportEngine, "_generate", _echo_fragments)
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(2), "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_pages"] == 2
    page = body["results"][0]
    assert page["markdown"].startswith("MOCK(page-0001.png|document parsing. Layout:")
    assert "two-column" in page["markdown"]
    assert page["layout"]["columns"] == "2"
    assert page["support_method"] == "support-spans-proofread"
    assert page["cleanup_method"] == "support-spans-proofread"
    assert page["corrections"]["formatting_only"] is True
    assert body["furniture"]["template"] is None
    # Spans are the authoritative output and carry identity.
    import json as _json

    spans = [_json.loads(line) for line in page["spans_jsonl"].splitlines()]
    assert spans[0]["id"] == "p1-1"
    assert spans[0]["text"].startswith("MOCK(page-0001.png|document parsing.")


def test_pdf_pipeline_applies_support_corrections(client, monkeypatch):
    def fix_typo(self, prompt, max_tokens):
        block = _echo_fragments(self, prompt, max_tokens)[0]
        return block.replace("MOCK", "MARK"), 5, False

    monkeypatch.setattr(cleanup_mod.SupportEngine, "_generate", fix_typo)
    r = client.post(
        "/parse/pdf",
        files={"file": ("t.pdf", _pdf_bytes(1), "application/pdf")},
        data={"pages": "all"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    page = body["results"][0]
    assert "MARK(page-0001.png" in page["markdown"]
    import json as _json

    spans = [_json.loads(line) for line in page["spans_jsonl"].splitlines()]
    assert spans[0]["text"].startswith("MARK(")
    assert page["corrections"]["formatting_only"] is False


def test_image_pipeline_with_cleanup(client, monkeypatch):
    monkeypatch.setattr(cleanup_mod.SupportEngine, "_generate", _echo_fragments)
    r = client.post(
        "/parse/image",
        files={"file": ("t.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"][0]["support_method"] == "support-spans-proofread"


def test_reflow_real_path_with_audit(client, monkeypatch):
    monkeypatch.setattr(cleanup_mod.SupportEngine, "_generate", _canonical_output)
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


def test_job_flow_with_support_tracks_phase(client, monkeypatch):
    monkeypatch.setattr(cleanup_mod.SupportEngine, "_generate", _echo_fragments)
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
    assert body["result"]["results"][0]["cleanup_method"] == "support-spans-proofread"


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


def test_parse_pdf_path_tracks_support_progress(client, tmp_path, monkeypatch):
    import asyncio
    import time

    monkeypatch.setattr(cleanup_mod.SupportEngine, "_generate", _echo_fragments)

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
            job=job,
        )
    )
    assert resp.journal == "generic"
    assert job.phase == "support"
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
