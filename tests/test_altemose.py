"""Real-PDF coverage for the layout-first flow, via the committed fixture.

tests/assets/altemose2022.pdf (Altemose et al. 2022, Science — 13
digital-born pages) exercises the new flow with real page renders and real
page geometry, still without MLX weights: page OCR comes from FakeEngine
and the support LLM is stubbed, exactly like test_pipeline.py. The stages
under test for real are: PDF open, page render, scan thumbnail, hint
injection into the OCR prompt, the layout span filter, generic furniture,
markdown render, and the scan-failure fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ocr_server import api as api_mod
from ocr_server import cleanup as cleanup_mod
from ocr_server.api import app, holder
from ocr_server.fake import FakeEngine
from ocr_server.layout import LayoutProfile

PDF_PATH = Path(__file__).resolve().parent / "assets" / "altemose2022.pdf"
TOKEN = "altemose-token"


def _echo_fragments(self, prompt, max_tokens):
    """Stub LLM: echo the numbered fragment block back unchanged."""
    start = prompt.index("<<<FRAGMENTS") + len("<<<FRAGMENTS\n")
    end = prompt.index("FRAGMENTS>>>")
    return prompt[start:end].strip(), 5, False


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(cleanup_mod.SupportEngine, "load", lambda self: None)
    monkeypatch.setenv("OCR_FAKE_ENGINE", "1")
    monkeypatch.setenv("OCR_INTERNAL_TOKEN", TOKEN)
    holder.load()
    with TestClient(app) as c:
        # Lifespan re-loads the holder on entry: flip to the stubbed
        # configuration only after it runs.
        monkeypatch.setattr(api_mod, "_support_engine", None)
        holder.is_fake = False
        holder.engine = FakeEngine()
        holder.engine.load()
        yield c
    holder.engine = None
    holder.is_fake = False
    monkeypatch.setattr(api_mod, "_support_engine", None)


@pytest.fixture()
def canned_scan(monkeypatch):
    """Realistic stub pre-scan: two-column Science page, high confidence.

    Records per-page calls (thumbnail path, page, token budget) so tests
    can pin the scan plumbing, not just its output.
    """
    calls: list[dict] = []

    def _scan(self, image_path, page, max_tokens=384):
        # The thumbnail must be a real downscaled render while it exists —
        # the pipeline deletes temp pages after the request.
        from PIL import Image

        thumb = Path(image_path)
        assert thumb.is_file()
        with Image.open(thumb) as img:
            size = img.size
        assert max(size) <= 1024
        calls.append({"image": image_path, "page": page, "max_tokens": max_tokens})
        return LayoutProfile(page=page, columns="2", confidence=0.9)

    monkeypatch.setattr(cleanup_mod.SupportEngine, "scan_layout", _scan)
    return calls


def _line_spans(page_no: int) -> list:
    """One text span per text-layer line, with real 0-1000 page geometry."""
    import pymupdf

    from ocr_server.spans import Span

    doc = pymupdf.open(str(PDF_PATH))
    try:
        pg = doc[page_no - 1]
        w_pt, h_pt = pg.rect.width, pg.rect.height
        lines: dict[tuple[int, int], list] = {}
        for x0, y0, x1, y1, word, bno, lno, _wno in pg.get_text("words"):
            lines.setdefault((bno, lno), []).append((x0, y0, x1, y1, word))
        spans = []
        for key in sorted(lines):
            ws = sorted(lines[key], key=lambda w: w[0])
            spans.append(
                Span(
                    page=page_no,
                    label="text",
                    box=[
                        int(min(w[0] for w in ws) / w_pt * 1000),
                        int(min(w[1] for w in ws) / h_pt * 1000),
                        int(max(w[2] for w in ws) / w_pt * 1000),
                        int(max(w[3] for w in ws) / h_pt * 1000),
                    ],
                    text=" ".join(w[4] for w in ws),
                )
            )
        for i, span in enumerate(spans):
            span.id = f"p{page_no}-{i + 1}"
        return spans
    finally:
        doc.close()


def test_fixture_is_digital_thirteen_pages():
    import pymupdf

    assert PDF_PATH.is_file(), f"committed test PDF missing: {PDF_PATH}"
    doc = pymupdf.open(str(PDF_PATH))
    try:
        assert doc.page_count == 13
        for i in range(doc.page_count):
            assert doc[i].get_text().strip(), f"page {i + 1} has no text layer"
    finally:
        doc.close()


def test_real_pdf_new_flow_end_to_end(client, canned_scan, monkeypatch):
    # Real file through the whole new flow: render -> thumbnail -> stubbed
    # scan -> hinted OCR -> filter -> generic furniture -> support correct.
    monkeypatch.setattr(cleanup_mod.SupportEngine, "_generate", _echo_fragments)
    r = client.post(
        "/parse/pdf",
        files={"file": ("altemose2022.pdf", PDF_PATH.read_bytes(), "application/pdf")},
        data={"pages": "1-2", "dpi": "100"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_pages"] == 2

    # The scan ran once per page, on a real downscaled thumbnail
    # (existence + max 1024px asserted inside the stub, while temp
    # pages still live).
    assert [c["page"] for c in canned_scan] == [1, 2]
    assert all(c["max_tokens"] == 384 for c in canned_scan)

    # The OCR prompt carried the one-sentence hint for every page.
    prompts = [params["prompt"] for _, params in holder.engine.calls]
    assert len(prompts) == 2
    assert all("Layout: two-column." in p for p in prompts)

    for page in body["results"]:
        assert page["layout"]["columns"] == "2"
        assert page["layout"]["method"] == "support-scan"
        assert page["layout"]["figures_skipped"] == 0
        assert page["layout"]["furniture_flagged"] == 0
        assert page["support_method"] == "support-spans-digital"  # real text layer -> digital branch
        assert page["markdown"].startswith("MOCK(")
    import json as _json

    spans = [_json.loads(line) for line in body["results"][0]["spans_jsonl"].splitlines()]
    assert spans[0]["id"] == "p1-1"


def test_layout_filter_flags_real_running_heads():
    from ocr_server.furniture import _band
    from ocr_server.layout import apply_layout_filter

    spans = _line_spans(1)
    header = next(s for s in spans if "COMPLETING THE HUMAN GENOME" in s.text)
    footer = next(s for s in spans if "Altemose et al." in s.text)
    # Pin the test's own assumptions: these lines really live in the bands.
    assert _band(header) == "top"
    assert _band(footer) == "bottom"

    profile = LayoutProfile(
        page=1, columns="2", header=header.text, footer=footer.text, confidence=0.9
    )
    ids_before = [s.id for s in spans]
    counts = apply_layout_filter(spans, profile)

    assert counts["furniture_flagged"] >= 2
    assert header.label == "furniture"
    assert footer.label == "furniture"
    # Relabel-only: identity and order preserved.
    assert [s.id for s in spans] == ids_before


def test_layout_filter_skips_real_body_line_in_figure():
    from ocr_server.furniture import _band, apply_furniture
    from ocr_server.layout import apply_layout_filter
    from ocr_server.spans import render_markdown

    spans = _line_spans(1)
    body = [s for s in spans if _band(s) is None and len(s.text) > 40]
    target = min(body, key=lambda s: abs((s.box[1] + s.box[3]) / 2 - 500))
    witness = next(s for s in body if s.box[1] > target.box[3] + 200)
    x1, y1, x2, y2 = target.box
    figure = [
        max(0, x1 - 30),
        max(0, y1 - 30),
        min(1000, x2 + 30),
        min(1000, y2 + 30),
    ]
    profile = LayoutProfile(page=1, columns="2", figures=[figure], confidence=0.9)

    counts = apply_layout_filter(spans, profile)

    assert counts["figures_skipped"] >= 1
    assert target.label == "furniture"
    assert witness.label == "text"
    assert [s.id for s in spans] == [s.id for s in _line_spans(1)][: len(spans)]

    # Pipeline order on real geometry: layout filter, then the generic
    # repetition pass, then the deterministic render — no crash, markdown
    # survives, filtered spans stay out of it.
    page2 = _line_spans(2)
    info = apply_furniture([spans, page2], template="auto")
    assert info["template"] is None
    markdown = render_markdown(spans, "generic")
    assert markdown.strip()
    assert target.text not in markdown
    assert witness.text in markdown


def test_scan_failure_falls_back_unhinted_on_real_pdf(client, monkeypatch):
    # Scan outage degrades to the unhinted pipeline: the document still
    # parses and the OCR prompt is the bare default.
    monkeypatch.setattr(
        cleanup_mod.SupportEngine,
        "scan_layout",
        lambda self, image_path, page, max_tokens=384: None,
    )
    monkeypatch.setattr(cleanup_mod.SupportEngine, "_generate", _echo_fragments)
    r = client.post(
        "/parse/pdf",
        files={"file": ("altemose2022.pdf", PDF_PATH.read_bytes(), "application/pdf")},
        data={"pages": "1", "dpi": "100"},
    )
    assert r.status_code == 200, r.text
    page = r.json()["results"][0]
    assert page["layout"] is None
    assert page["markdown"].startswith("MOCK(")
    assert page["support_method"] == "support-spans-digital"  # real text layer -> digital branch
    prompts = [params["prompt"] for _, params in holder.engine.calls]
    assert prompts == ["document parsing."]
