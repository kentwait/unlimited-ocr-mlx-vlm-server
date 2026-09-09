"""Unit tests for pure helpers: no model, no server, no weights."""

from __future__ import annotations

import pytest

from ocr_server.api import _audit_to_corrections
from ocr_server.cleanup import (
    CleanupEngine,
    audit_corrections,
    strip_det_markers,
)
from ocr_server.engine import (
    OcrEngine,
    _dedupe_long_lines,
    _loop_period,
    decode_byte_level,
)
from ocr_server.furniture import _apply_generic, apply_furniture
from ocr_server.pages import parse_pages_spec
from ocr_server.prompts import PromptRegistry
from ocr_server.schemas import InferenceParams, ReflowRequest
from ocr_server.spans import (
    Span,
    parse_spans,
    render_markdown,
    spans_to_jsonl,
    strip_det_markers as spans_strip,
)


# ---------- spans ----------


def test_parse_spans_markers_gaps_and_tail():
    text = (
        "leading plain\n"
        "<|det|>title [0, 0, 100, 10]<|/det|>My Title\n"
        "<|det|>text [0, 20, 50, 30]<|/det|>Body here<PAGE>\n"
        "trailing plain"
    )
    spans = parse_spans(text, page=2)
    # Gap text becomes a plain record; trailing text joins the last span —
    # content is preserved, never dropped.
    assert [(s.label, s.page) for s in spans] == [
        ("text", 2),
        ("title", 2),
        ("text", 2),
    ]
    assert spans[1].box == [0, 0, 100, 10]
    assert spans[2].text == "Body here\ntrailing plain"  # <PAGE> stripped
    assert spans[0].box is None  # gap record


def test_parse_spans_empty_and_plain():
    assert parse_spans("") == []
    assert parse_spans("   ") == []
    spans = parse_spans("just words")
    assert len(spans) == 1 and spans[0].text == "just words"
    assert spans[0].label == "text" and spans[0].page == 1  # defaults pinned


def test_parse_spans_empty_marker_label_falls_back():
    spans = parse_spans("<|det|>  [0,0,1,1]<|/det|>x")
    assert spans[0].label == "text"


def test_spans_jsonl_round_trip():
    spans = [Span(page=1, label="title", box=[0, 0, 1, 1], text="T")]
    assert spans[0].to_dict()["text"] == "T"
    assert '"page": 1' in spans_to_jsonl(spans)


def test_render_markdown_skips_furniture_and_figures():
    spans = [
        Span(page=1, label="title", box=None, text="T"),
        Span(page=1, label="furniture", box=None, text="running head"),
        Span(page=1, label="image", box=None, text=""),
        Span(page=1, label="text", box=None, text="body"),
        Span(page=1, label="text", box=None, text="  "),
    ]
    assert render_markdown(spans) == "# T\n\n*[figure]*\n\nbody"


def test_render_markdown_skips_page_duplicates():
    page = Span(page=1, label="page", box=[0, 0, 1000, 1000], text="whole page")
    title = Span(page=1, label="title", box=None, text="T")
    assert render_markdown([page, title]) == "# T"
    # Page-only output keeps its text: never silently drop content.
    assert render_markdown([page]) == "whole page"


def test_render_markdown_drops_structural_labels_per_journal():
    from ocr_server.spans import JOURNALS, drop_labels_for

    assert set(JOURNALS) == {"generic", "nature", "science", "pmc"}
    header = Span(page=1, label="header", box=None, text="SPECIAL SECTION")
    footer = Span(page=1, label="footer", box=None, text="journal boilerplate")
    pagenum = Span(page=1, label="page_number", box=None, text="12")
    aside = Span(page=1, label="aside_text", box=None, text="Downloaded from x")
    affil = Span(page=1, label="page_footnote", box=None, text="Dept of X")
    body = Span(page=1, label="text", box=None, text="real content here")
    for journal in JOURNALS:
        assert drop_labels_for(journal) >= {
            "header",
            "footer",
            "page_number",
            "aside_text",
            "page_footnote",
        }
        assert render_markdown([header, footer, pagenum, aside, affil, body], journal) == (
            "real content here"
        )
    # Unknown journals fall back to the universal set, never to nothing.
    assert "header" in drop_labels_for("cell")


def test_strip_helpers():
    raw = "<|det|>text [0,0,1,1]<|/det|>hi [1, 2]"
    assert "det" not in spans_strip(raw)
    assert "det" not in strip_det_markers(raw)


def test_strip_det_drops_leftover_markers():
    raw = "<|det|>text [0,0,1,1]<|/det|>hi\n[12, 34]\n<|note|>\nbye"
    cleaned = strip_det_markers(raw)
    assert "[12, 34]" not in cleaned and "<|note|>" not in cleaned
    assert "hi" in cleaned and "bye" in cleaned


def test_strip_det_markers_exact():
    assert strip_det_markers("<|det|>title [1,2,3,4]<|/det|>Hello") == "Hello"
    assert strip_det_markers("plain") == "plain"


def test_content_words_drops_shorts_and_digits():
    from ocr_server.cleanup import _content_words

    assert _content_words("answer 42 x") == ["answer"]


# ---------- pages ----------


def test_pages_spec_edges():
    assert parse_pages_spec("", 3) == [1, 2, 3]
    assert parse_pages_spec("*", 2) == [1, 2]
    assert parse_pages_spec("2,2,1", 3) == [1, 2]
    assert parse_pages_spec("1,,2", 3) == [1, 2]
    assert parse_pages_spec(" 2 - 3 ", 3) == [2, 3]
    with pytest.raises(ValueError):
        parse_pages_spec("all", 0)
    with pytest.raises(ValueError):
        parse_pages_spec("0", 3)
    with pytest.raises(ValueError):
        parse_pages_spec("3-1", 5)
    with pytest.raises(ValueError):
        parse_pages_spec(",,,", 5)


# ---------- schemas ----------


def test_inference_params_validation():
    assert InferenceParams().prompt == "document parsing."
    with pytest.raises(ValueError):
        InferenceParams(prompt="   ")
    with pytest.raises(ValueError):
        InferenceParams(prompt="x" * 201)
    with pytest.raises(ValueError):
        InferenceParams(prompt="emoji \U0001f600 here")


def test_reflow_request_bounds():
    assert ReflowRequest(markdown="# hi").contract_version == 1
    with pytest.raises(ValueError):
        ReflowRequest(markdown="  ")
    with pytest.raises(ValueError):
        ReflowRequest(markdown="# hi", journal="j" * 65)
    with pytest.raises(ValueError):
        ReflowRequest(markdown="# hi", max_tokens=10**9)


# ---------- prompts ----------


def test_prompt_registry_loads_repo_prompts():
    reg = PromptRegistry()
    reg.load()
    assert reg.loaded
    out = reg.render("checker_scan", ocr="hi", page=1)
    assert "hi" in out
    with pytest.raises(RuntimeError):
        reg.render("nope")


def test_prompt_registry_failures(tmp_path):
    reg = PromptRegistry(tmp_path / "missing")
    with pytest.raises(RuntimeError, match="not found"):
        reg.load()
    tmp_path.joinpath("checker_digital.md").write_text("ok {{ ocr }}")
    with pytest.raises(RuntimeError, match="missing"):
        PromptRegistry(tmp_path).load()
    tmp_path.joinpath("checker_scan.md").write_text("{% if %}")
    with pytest.raises(RuntimeError, match="syntax"):
        PromptRegistry(tmp_path).load()
    tmp_path.joinpath("checker_scan.md").write_text("uses {{ nope }} {{ ocr }}")
    with pytest.raises(RuntimeError, match="dry-render"):
        PromptRegistry(tmp_path).load()
    tmp_path.joinpath("checker_scan.md").write_text("   \n  ")
    with pytest.raises(RuntimeError, match="empty"):
        PromptRegistry(tmp_path).load()


# ---------- cleanup pure helpers ----------


def test_audit_corrections_attribution():
    audit = audit_corrections("the cat sat", "the dog sat", "a dog runs")
    assert audit.text_layer_backed == ["dog"]
    assert audit.invented == []
    assert not audit.formatting_only


def test_audit_corrections_ocr_vocab_backed():
    audit = audit_corrections("cat sat", "cat cat", None)
    assert audit.ocr_vocab_backed == ["cat"]
    assert audit.invented == []


def test_audit_to_corrections_none():
    assert _audit_to_corrections(None) is None


def test_audit_removed_only_edits():
    audit = audit_corrections("alpha beta", "alpha", None)
    assert not audit.formatting_only
    assert audit.n_edits == 0
    audit.log_summary("test")  # exercises the no-edit branch


def _stubbed_engine(monkeypatch, text="canonical output"):
    from ocr_server import cleanup as cleanup_mod
    from ocr_server.prompts import PromptRegistry

    monkeypatch.setattr(cleanup_mod.CleanupEngine, "load", lambda self: None)
    monkeypatch.setattr(
        cleanup_mod.CleanupEngine,
        "_generate",
        lambda self, prompt, max_tokens: (text, 5, False),
    )
    reg = PromptRegistry()
    reg.load()
    return cleanup_mod.CleanupEngine("stub", prompts=reg)


def test_cleanup_engine_requires_prompts():
    with pytest.raises(ValueError, match="PromptRegistry"):
        CleanupEngine("stub", prompts=None)


def test_cleanup_engine_starts_unloaded(monkeypatch):
    from ocr_server.prompts import PromptRegistry

    reg = PromptRegistry()
    reg.load()
    assert not CleanupEngine("stub", prompts=reg).loaded


def test_cleanup_page_digital_branch(monkeypatch):
    engine = _stubbed_engine(monkeypatch)
    text, stats = engine.cleanup_page(
        "<|det|>text [0,0,1,1]<|/det|>hello world, this is a long enough body",
        "hello world, this is the publisher text layer " * 10,
    )
    assert stats.method == "ocr+pymupdf+llm"
    assert text == "canonical output"


def test_cleanup_page_degenerate_falls_back(monkeypatch):
    engine = _stubbed_engine(monkeypatch, text="x")
    text, _ = engine.cleanup_page("some reasonably long ocr body here", None)
    assert "some reasonably long" in text


def test_reflow_text_variants(monkeypatch):
    engine = _stubbed_engine(monkeypatch)
    text, stats = engine.reflow_text("some markdown body here", journal="pmc")
    assert stats.method == "reflow+checker-proofread"
    assert text == "canonical output"
    _, stats = engine.reflow_text(
        "some markdown body here",
        journal="pmc",
        text_layer="publisher layer " * 20,
    )
    assert stats.method == "reflow+checker-digital"
    text, _ = engine.reflow_text("x" * 100, journal="nature", prompt_override="Q")
    assert text == "x" * 100  # degenerate stub output falls back to input


def test_audit_corrections_invented_and_format_only():
    audit = audit_corrections("make this bold", "make this **bold**", None)
    assert audit.formatting_only
    audit.log_summary("format")  # exercises the formatting-only branch
    audit = audit_corrections("alpha beta", "alpha zzz", None)
    assert audit.invented == ["zzz"]
    assert audit.n_words_in == 2 and audit.n_words_out == 2
    audit.log_summary("test")  # must not raise


# ---------- engine pure helpers ----------


def test_dedupe_long_lines():
    long = "x" * 50
    assert _dedupe_long_lines(f"{long}\n{long}\nshort") == f"{long}\nshort"


def test_loop_period():
    assert _loop_period([1, 2] * 70) == 2
    assert _loop_period(list(range(200))) is None
    assert _loop_period([1]) is None


class _StubTokenizer:
    all_special_ids = [0]
    pad_token_id = 1

    def convert_ids_to_tokens(self, i):
        return {2: "Ġ", 3: "a"}.get(i, "")


def test_decode_byte_level_drops_specials():
    assert decode_byte_level(_StubTokenizer(), [0, 1, 2, 3]) == " a"
    assert decode_byte_level(_StubTokenizer(), [9]) == ""


class _UnicodeTokenizer(_StubTokenizer):
    def convert_ids_to_tokens(self, i):
        return {2: "€"}.get(i, "")


def test_decode_byte_level_falls_back_to_utf8():
    assert decode_byte_level(_UnicodeTokenizer(), [2]) == "€"


def test_ocr_engine_load_early_return():
    eng = OcrEngine("some-ref")
    assert eng.model_ref == "some-ref"
    assert not eng.loaded
    eng.model = object()  # pretend loaded: load() must not touch mlx
    eng.load()
    assert eng.loaded


def test_get_ocr_engine_shortcuts():
    from ocr_server.api import EngineHolder
    from ocr_server.fake import FakeEngine

    holder = EngineHolder()
    holder.engine = FakeEngine()
    holder.is_fake = False
    holder.model_ref = "m"
    assert holder.get_ocr_engine(None) is holder.engine
    assert holder.get_ocr_engine("") is holder.engine
    assert holder.get_ocr_engine("default") is holder.engine
    assert holder.get_ocr_engine("m") is holder.engine


def test_holder_load_fake_branch(monkeypatch):
    from ocr_server import api as api_mod

    monkeypatch.setenv("OCR_FAKE_ENGINE", "1")
    monkeypatch.delenv("OCR_MODEL_REF", raising=False)
    holder = api_mod.EngineHolder()
    holder.load()
    assert holder.is_fake and holder.engine.loaded
    assert holder.model_ref == api_mod.DEFAULT_MODEL_REF


def test_holder_load_real_branch_without_weights(monkeypatch):
    from ocr_server import api as api_mod
    from ocr_server.engine import OcrEngine as RealEngine

    monkeypatch.delenv("OCR_FAKE_ENGINE", raising=False)
    monkeypatch.setenv("OCR_MODEL_REF", "some-ref")
    monkeypatch.setattr(RealEngine, "load", lambda self: None)
    holder = api_mod.EngineHolder()
    holder.load()
    assert not holder.is_fake and holder.model_ref == "some-ref"


def test_get_ocr_engine_lazy_alternate_without_weights(monkeypatch):
    from ocr_server.api import DEFAULT_MODEL_BF16, EngineHolder
    from ocr_server.engine import OcrEngine as RealEngine
    from ocr_server.fake import FakeEngine

    monkeypatch.setattr(RealEngine, "load", lambda self: None)
    holder = EngineHolder()
    holder.engine = FakeEngine()
    holder.is_fake = False
    holder.model_ref = "m"
    alt = holder.get_ocr_engine("bf16")
    assert isinstance(alt, RealEngine)
    assert alt.model_ref == DEFAULT_MODEL_BF16
    assert holder.get_ocr_engine("bf16") is alt  # resident afterwards


# ---------- furniture generic pass ----------


def _span(page: int, y1: int, text: str) -> Span:
    return Span(page=page, label="text", box=[0, y1, 100, y1 + 10], text=text)


def test_generic_fingerprinting_flags_repeats():
    pages = [
        [_span(1, 10, "Journal of Tests 2024"), _span(1, 500, "Body one")],
        [_span(2, 10, "Journal of Tests 2025"), _span(2, 500, "Body two")],
    ]
    assert _apply_generic(pages) == 2
    assert all(s.label == "furniture" for p in pages for s in p if s.text.startswith("Journal"))
    assert pages[0][1].label == "text"  # body untouched


def test_generic_needs_two_pages():
    pages = [[_span(1, 10, "Repeated")]]
    assert _apply_generic(pages) == 0
    info = apply_furniture(pages, template="auto")
    assert info["removed_total"] == 0 and info["template"] is None


def test_band_edge_cases():
    from ocr_server.furniture import _band

    assert _band(Span(page=1, label="text", box=None, text="x")) is None
    assert _band(_span(1, 500, "mid")) is None
    assert _band(_span(1, 10, "top")) == "top"


def test_generic_ignores_non_repeating_pages():
    pages = [
        [_span(1, 10, "Header one"), _span(1, 500, "Body one")],
        [_span(2, 10, "Totally different"), _span(2, 500, "Body two")],
    ]
    assert _apply_generic(pages) == 0


def test_generic_skips_bottom_band_and_relabeled():
    bottom = _span(1, 960, "Footer")
    bottom.box = [0, 900, 100, 960]
    assert bottom.box is not None
    pages = [
        [bottom, _span(1, 500, "Body one")],
        [_span(2, 960, "Footer"), _span(2, 500, "Body two")],
    ]
    pages[0][1].label = "furniture"  # already relabeled: skipped outright
    assert _apply_generic(pages) >= 1


# ---------- CLI entry point ----------


def test_main_parses_flags_and_starts_uvicorn(monkeypatch):
    import os
    import sys

    import uvicorn

    import ocr_server.__main__ as main_mod

    calls: dict = {}
    monkeypatch.setattr(
        uvicorn, "run", lambda *a, **k: calls.update(args=a, kwargs=k)
    )
    monkeypatch.setattr(
        sys, "argv", ["ocr-server", "--fake-engine", "--port", "8311"]
    )
    monkeypatch.delenv("OCR_FAKE_ENGINE", raising=False)
    main_mod.main()
    assert os.environ["OCR_FAKE_ENGINE"] == "1"
    assert calls["kwargs"]["port"] == 8311
    assert calls["kwargs"]["host"] == "127.0.0.1"
    assert calls["args"] == ("ocr_server.api:app",)
