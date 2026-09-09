"""Property tests (hypothesis): pure-logic invariants + API robustness.

Pure properties run under the default profile. API fuzzing uses small
example counts and no deadlines (server timing under load is not the
property under test).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ocr_server.cleanup import audit_corrections
from ocr_server.furniture import _apply_generic, _fingerprint, apply_furniture
from ocr_server.pages import parse_pages_spec
from ocr_server.spans import Span, parse_spans, render_markdown
from test_api import _pdf_bytes

words = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=12,
)

ascii_words = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789 ",
    min_size=1,
    max_size=12,
)


@given(st.lists(ascii_words, min_size=1, max_size=8))
def test_fingerprint_normalizes_case_space_and_digits(toks):
    # Contract is lower()-based normalization (not full casefold: lookalikes
    # like MICRO SIGN vs GREEK MU intentionally stay distinct).
    text = "  ".join(toks)
    assert _fingerprint(text) == _fingerprint(text.upper())
    assert _fingerprint(text) == _fingerprint(" ".join(text.split()))
    assert _fingerprint("page 12 of 34") == _fingerprint("page 1 of 2")


@given(st.text(min_size=1, max_size=60))
def test_parse_never_drops_content(text):
    spans = parse_spans(text)
    joined = " ".join(s.text for s in spans)
    for token in text.split():
        if token == "<PAGE>":
            continue
        assert token in joined or token.startswith("<|")


@given(
    st.lists(
        st.builds(
            Span,
            page=st.integers(min_value=1, max_value=5),
            label=st.sampled_from(["text", "title", "image", "furniture"]),
            box=st.none()
            | st.lists(st.integers(min_value=0, max_value=1000), min_size=4, max_size=4),
            text=st.text(max_size=40),
        ),
        max_size=10,
    )
)
def test_render_markdown_invariants(spans):
    md = render_markdown(spans)
    assert "<|det|>" not in md
    # Furniture contributes nothing: longer texts unique to furniture spans
    # are absent (short texts are substring-noise; shared content and the
    # synthetic *[figure]* marker may legitimately contain them).
    body_texts = [s.text for s in spans if s.label != "furniture"]
    for s in spans:
        if s.label == "furniture" and len(s.text.strip()) >= 8:
            if not any(s.text in b for b in body_texts):
                assert s.text not in md.replace("*[figure]*", "")
    titles = [s.text for s in spans if s.label == "title" and s.text.strip()]
    for title in titles:
        # Render strips document-edge whitespace; compare stripped.
        assert title.strip() in md


@given(st.lists(words, min_size=1, max_size=10), st.lists(words, min_size=1, max_size=10))
def test_audit_invented_has_no_source(before_words, after_words):
    before, after = " ".join(before_words), " ".join(after_words)
    audit = audit_corrections(before, after, None)
    vocab = {w.lower() for w in before.split()}
    for w in audit.invented:
        assert w not in vocab


@given(st.integers(min_value=1, max_value=50))
def test_pages_all_is_identity(total):
    assert parse_pages_spec("all", total) == list(range(1, total + 1))


@given(st.text(max_size=20))
def test_pages_spec_never_returns_garbage(spec):
    try:
        pages = parse_pages_spec(spec, 10)
    except ValueError:
        return
    assert pages == sorted(set(pages))
    assert all(1 <= p <= 10 for p in pages)


@given(st.integers(min_value=1, max_value=10))
def test_generic_furniture_keeps_body_text(n):
    pages = [
        [_span(1, 10, "Same header"), _span(1, 500, f"unique body {i}")]
        for i in range(n)
    ]
    _apply_generic(pages)
    for i, spans in enumerate(pages):
        body = next(s for s in spans if f"unique body {i}" in s.text)
        assert body.label == "text"


def _span(page: int, y1: int, text: str) -> Span:
    return Span(page=page, label="text", box=[0, y1, 100, y1 + 10], text=text)


# ---------- API robustness (fake engine) ----------

import contextlib
import os


@contextlib.contextmanager
def _api_client():
    """Fresh TestClient without fixtures (@given forbids function-scoped
    fixtures via a health check; this context manager is equivalent)."""
    from fastapi.testclient import TestClient

    from ocr_server.api import app, holder

    saved = {
        k: os.environ.get(k) for k in ("OCR_FAKE_ENGINE", "OCR_INTERNAL_TOKEN")
    }
    os.environ["OCR_FAKE_ENGINE"] = "1"
    os.environ.pop("OCR_INTERNAL_TOKEN", None)
    holder.load()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        holder.engine = None
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@settings(max_examples=25, deadline=None)
@given(st.text(max_size=20))
def test_furniture_field_never_500s(spec):
    with _api_client() as api_client:
        r = api_client.post(
            "/parse/jobs",
            files={"file": ("t.pdf", _pdf_bytes(1), "application/pdf")},
            data={"pages": "all", "furniture": spec},
        )
        assert r.status_code in (202, 400)
        # Empty string falls back to the field default ("auto") — FastAPI
        # substitutes defaults for empty form values; pinned here.
        if spec not in ("auto", "none", ""):
            assert r.status_code == 400


@settings(max_examples=25, deadline=None)
@given(st.text(max_size=20))
def test_pages_field_never_500s(spec):
    with _api_client() as api_client:
        r = api_client.post(
            "/parse/jobs",
            files={"file": ("t.pdf", _pdf_bytes(3), "application/pdf")},
            data={"pages": spec},
        )
        assert r.status_code in (202, 400)


@settings(max_examples=25, deadline=None)
@given(st.integers())
def test_reflow_contract_ints_never_500(version):
    with _api_client() as api_client:
        r = api_client.post(
            "/internal/reflow",
            json={"contract_version": version, "markdown": "# hi"},
            headers={"Authorization": "Bearer t"},
        )
        # No token configured -> 404 regardless of version (fail closed).
        assert r.status_code == 404


def test_apply_furniture_rejects_garbage_modes():
    from ocr_server.furniture import apply_furniture

    for bad in ["NATURE", "auto ", "", "null", "generic"]:
        with pytest.raises(ValueError):
            apply_furniture([[]], template=bad)
