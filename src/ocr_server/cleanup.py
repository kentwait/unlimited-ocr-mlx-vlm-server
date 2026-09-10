"""Support stage: layout pre-scan plus post-OCR correction, both WITHIN spans.

Pipeline per page:
  0. Layout pre-scan (vision): the support model looks at a low-resolution
     page thumbnail and reports a coarse LayoutProfile (column count,
     running header/footer text, large figure boxes). Any failure yields
     None and the pipeline proceeds unhinted.
  1. OCR output is parsed into spans (see ocr_server.spans); structural
     labels are excluded.
  2. Content spans are numbered and sent to the LLM (Qwen3.5-0.8B MLX 8-bit
     via mlx_vlm) as an ID'd plain-text list:
     - digital pages (text layer >= 200 chars): reconcile fragment wording
       against the publisher text layer AND proofread (misspellings etc.)
     - scanned pages: proofread-only — fix obvious OCR misspellings from
       context; never paraphrase; preserve names/numbers/units
  3. The numbered output is parsed strictly: every fragment number must be
     present exactly once, else the page falls back to the original spans.

The server never asks the support model for markdown — span texts are
corrected in place and markdown rendering is downstream (server-side
frozen render; Paperhub renders its own). Every LLM edit is audited per
span: the original fragment is word-diffed against the corrected one, and
each changed word is attributed as
  - text-layer-backed: the replacement exists in the page's text layer
  - ocr-vocab-backed:  replacement appears elsewhere in the fragment/page
  - invented:          replacement exists in neither (model "intuition") —
                       the hallucination-risk category, surfaced in logs
Corrections are logged at INFO per page and summarized in SupportStats.

Naming history: this was the "checker"/"cleanup" stage (OCR_CLEANUP* env,
CleanupEngine). Those names survive as deprecated aliases; the canonical
names are now support/* (OCR_SUPPORT* env, SupportEngine).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any

from .engine import _dedupe_long_lines, _loop_period
from .layout import LayoutProfile, parse_layout_profile
from .prompts import PromptRegistry
from .spans import STRUCTURAL_LABELS, Span

log = logging.getLogger("ocr_server")

#: Canonical support-model ref. OCR_CLEANUP_MODEL is still honored as a
#: fallback (see api._get_support_engine); this constant is the default.
DEFAULT_SUPPORT_MODEL = "mlx-community/Qwen3.5-0.8B-MLX-8bit"
#: Deprecated alias (pre-rename name).
DEFAULT_CLEANUP_MODEL = DEFAULT_SUPPORT_MODEL

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_MARKDOWN_RE = re.compile(r"[#*_>`\[\]()\\|⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]")


# ---------------------------------------------------------------------------
# Numbered-fragment format (the support model's I/O contract)
# ---------------------------------------------------------------------------

_SPAN_MARK_RE = re.compile(r"^[ \t]*\[(\d+)\][ \t]?", re.MULTILINE)


def format_fragments(spans: list[Span]) -> str:
    """Render spans as the support model's numbered plain-text list: a `[n]`
    marker line per fragment followed by its text."""
    lines: list[str] = []
    for i, s in enumerate(spans, 1):
        lines.append(f"[{i}]")
        lines.append(s.text)
    return "\n".join(lines)


def parse_numbered_fragments(output: str, expected: int) -> dict[int, str] | None:
    """Parse support output back into `{number: text}`.

    Strict: returns None unless every number in 1..expected appears exactly
    once (duplicate, missing, or extra numbers mean the model broke the
    contract — callers fall back to the original spans rather than guess)."""
    matches = list(_SPAN_MARK_RE.finditer(output))
    if not matches:
        return None
    frags: dict[int, str] = {}
    for i, m in enumerate(matches):
        n = int(m.group(1))
        if n in frags:
            return None
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(output)
        frags[n] = output[start:end].strip()
    if set(frags) != set(range(1, expected + 1)):
        return None
    return frags


# ---------------------------------------------------------------------------
# Correction auditing (word-level diff with attribution)
# ---------------------------------------------------------------------------

def _norm_word(w: str) -> str:
    """Loose word key for vocabulary checks: lowercase, markdown stripped,
    superscript/subscript unicode folded to ascii digits."""
    w = _MARKDOWN_RE.sub("", w)
    w = w.translate(_SUP_MAP)
    return w.lower()


_SUP_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUPERSCRIPT_RE = re.compile("[⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]")

# Words whose presence differs only because of markdown transformation
# (superscripts, citations, urls split/join) — formatting, not content.
_FORMAT_WORD_RE = re.compile(r"^(?:\d+[.,]?\d*|[a-z])$", re.IGNORECASE)


def _content_words(text: str) -> list[str]:
    """Normalized content words for the content-edit diff."""
    return [
        w
        for w in (_norm_word(x) for x in _WORD_RE.findall(text))
        if len(w) >= 2 and not w.isdigit()
    ]


@dataclass
class CorrectionAudit:
    """Diff between the support model's input and output, split into:

    - content edits: word-level changes (the misspellings/hallucinations)
      attributed to text-layer / OCR vocabulary / invented
    - formatting: markdown-transform churn, reported as counts only
    """

    n_words_in: int = 0
    n_words_out: int = 0
    text_layer_backed: list[str] = field(default_factory=list)
    ocr_vocab_backed: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    formatting_only: bool = False
    format_removed_words: int = 0
    format_added_words: int = 0

    @property
    def n_edits(self) -> int:
        return (
            len(self.text_layer_backed)
            + len(self.ocr_vocab_backed)
            + len(self.invented)
        )

    def log_summary(self, page_label: str) -> None:
        if self.formatting_only:
            log.info(
                "%s: support formatting-only (%d -> %d content words, "
                "+%d/-%d markdown-structure words) — no content edits",
                page_label,
                self.n_words_in,
                self.n_words_out,
                self.format_added_words,
                self.format_removed_words,
            )
            return
        if self.n_edits == 0:
            log.info("%s: support made no content edits", page_label)
            return
        samples = lambda xs: ", ".join(repr(x) for x in xs[:6]) + (
            f" …(+{len(xs) - 6})" if len(xs) > 6 else ""
        )
        log.info(
            "%s: support CONTENT edits — %d | text-layer-backed: %s | "
            "ocr-vocab-backed: %s | INVENTED (no source): %s",
            page_label,
            self.n_edits,
            samples(self.text_layer_backed) or "none",
            samples(self.ocr_vocab_backed) or "none",
            samples(self.invented) or "none",
        )


def audit_corrections(
    before: str, after: str, text_layer: str | None
) -> CorrectionAudit:
    """Content-edit diff between support input and output.

    Works on normalized *content word multisets* (order-independent, so
    markdown reflow doesn't produce phantom edits): counts words removed from
    and added to the page, then attributes each added word against the
    text-layer vocabulary and the page's own OCR vocabulary.
    """
    from collections import Counter

    audit = CorrectionAudit()
    b = _content_words(before)
    a = _content_words(after)
    audit.n_words_in = len(b)
    audit.n_words_out = len(a)
    tl_vocab = {_norm_word(w) for w in _WORD_RE.findall(text_layer or "")}
    ocr_vocab = set(Counter(b))

    removed = Counter(b) - Counter(a)  # words dropped by the support model
    added = Counter(a) - Counter(b)  # words introduced by the support model
    audit.format_removed_words = sum(removed.values())
    audit.format_added_words = sum(added.values())

    # Nothing meaningfully removed => output kept the page's words: any added
    # words are format-adjacent; anything else would have shown up as removals.
    audit.formatting_only = not removed and not added
    for w, n in added.items():
        for _ in range(n):
            if w in tl_vocab:
                audit.text_layer_backed.append(w)
            elif w in ocr_vocab:
                audit.ocr_vocab_backed.append(w)
            else:
                audit.invented.append(w)
    return audit


def merge_audits(audits: list[CorrectionAudit]) -> CorrectionAudit:
    """Aggregate per-span audits into one page-level audit (counts sum,
    sample lists concatenate)."""
    merged = CorrectionAudit()
    for a in audits:
        merged.n_words_in += a.n_words_in
        merged.n_words_out += a.n_words_out
        merged.text_layer_backed.extend(a.text_layer_backed)
        merged.ocr_vocab_backed.extend(a.ocr_vocab_backed)
        merged.invented.extend(a.invented)
        merged.format_removed_words += a.format_removed_words
        merged.format_added_words += a.format_added_words
    merged.formatting_only = (
        merged.format_removed_words == 0 and merged.format_added_words == 0
    )
    return merged


# ---------------------------------------------------------------------------
# Support engine
# ---------------------------------------------------------------------------

@dataclass
class SupportStats:
    method: str  # "support-spans-digital" | "support-spans-proofread" | "reflow+..."
    elapsed_s: float
    tokens: int | None = None
    early_stop: bool = False
    audit: CorrectionAudit | None = None


#: Deprecated alias (pre-rename name).
CleanupStats = SupportStats


class SupportEngine:
    """Small vision LLM for the support stage: layout pre-scans plus OCR
    text correction WITHIN spans (never across them, never into markdown)."""

    def __init__(
        self,
        model_ref: str = DEFAULT_SUPPORT_MODEL,
        prompts: PromptRegistry | None = None,
    ):
        if prompts is None or not prompts.loaded:
            raise ValueError(
                "SupportEngine requires a loaded PromptRegistry "
                "(server startup loads it; see ocr_server.prompts)"
            )
        self.model_ref = model_ref
        self.model: Any = None
        self.processor: Any = None
        self._prompts = prompts

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def load(self) -> None:  # pragma: no cover - downloads/loads MLX weights
        # pragma: no mutate block - requires MLX weights
        if self.loaded:
            return
        from mlx_vlm import load

        self.model, self.processor = load(self.model_ref)

    def _generate(self, prompt: str, max_tokens: int) -> tuple[str, int, bool]:  # pragma: no cover - runs the MLX model
        # pragma: no mutate block - requires MLX weights
        """stream_generate + loop-break; returns (text, n_tokens, early_stop)."""
        import time as _time

        from mlx_vlm.generate.dispatch import stream_generate
        from mlx_vlm.prompt_utils import apply_chat_template

        formatted = apply_chat_template(self.processor, self.model.config, prompt)
        ids: list[int] = []
        early_stop = False
        for resp in stream_generate(
            self.model,
            self.processor,
            formatted,
            max_tokens=max_tokens,
            temperature=0.0,
            enable_thinking=False,
        ):
            if resp.is_draft:
                continue
            if resp.token is not None:
                ids.append(int(resp.token))
                if len(ids) % 32 == 0 and _loop_period(ids) is not None:
                    early_stop = True
                    break
        text = self.processor.tokenizer.decode(
            ids, skip_special_tokens=True
        ).strip()
        text = _dedupe_long_lines(text)
        return text, len(ids), early_stop

    def _generate_vision(  # pragma: no cover - runs the MLX model
        self, prompt: str, image_path: str, max_tokens: int
    ) -> tuple[str, int, bool]:
        # pragma: no mutate block - requires MLX weights
        """Vision generate for the layout pre-scan (thumbnail in, JSON out)."""
        import time as _time

        from mlx_vlm.generate.dispatch import stream_generate
        from mlx_vlm.prompt_utils import apply_chat_template

        formatted = apply_chat_template(self.processor, self.model.config, prompt)
        ids: list[int] = []
        early_stop = False
        for resp in stream_generate(
            self.model,
            self.processor,
            formatted,
            image=image_path,
            max_tokens=max_tokens,
            temperature=0.0,
            enable_thinking=False,
        ):
            if resp.is_draft:
                continue
            if resp.token is not None:
                ids.append(int(resp.token))
                if len(ids) % 32 == 0 and _loop_period(ids) is not None:
                    early_stop = True
                    break
        text = self.processor.tokenizer.decode(
            ids, skip_special_tokens=True
        ).strip()
        return text, len(ids), early_stop

    def scan_layout(self, image_path: str, page: int, max_tokens: int = 384) -> LayoutProfile | None:
        """Coarse vision pre-scan of one page thumbnail.

        Total: never raises on model misbehavior — any failure (load,
        generate, unparsable output) logs and returns None, and the
        pipeline proceeds unhinted.
        """
        import time as _time

        t0 = _time.perf_counter()
        try:
            prompt = self._prompts.render("layout_scan", page=page)
            self.load()
            text, _, _ = self._generate_vision(prompt, image_path, max_tokens)
        except Exception as exc:
            log.warning("page %d: layout scan failed (%s) — proceeding unhinted", page, exc)
            return None
        profile = parse_layout_profile(text, page)
        if profile is None:
            log.warning("page %d: layout scan unparsable — proceeding unhinted", page)
            return None
        profile.elapsed_s = _time.perf_counter() - t0
        log.info(
            "page %d: layout columns=%s furniture=%s figures=%d conf=%.2f (%.1fs)",
            page,
            profile.columns,
            bool(profile.header or profile.footer),
            len(profile.figures),
            profile.confidence,
            profile.elapsed_s,
        )
        return profile

    def check_spans(
        self,
        spans: list[Span],
        text_layer: str | None,
        max_tokens: int = 6144,
    ) -> tuple[list[Span], SupportStats]:
        """Correct OCR text WITHIN each content span; returns (checked_spans,
        stats). Identity is preserved: labels, boxes, and span ids survive
        unchanged — only `text` may differ. Structural labels and empty
        fragments are never sent to the model.

        The server is journal-agnostic (per-document layout comes from the
        pre-scan), so the universal structural drop set always applies.

        Strict contract: the model must echo every fragment number exactly
        once. Any violation (or degenerate output) falls back to the
        original spans — content is never dropped on model misbehavior."""
        import time as _time

        t0 = _time.perf_counter()
        drop = STRUCTURAL_LABELS
        numbered: list[tuple[int, Span]] = [
            (idx, s)
            for idx, s in enumerate(spans)
            if s.label not in drop and s.text.strip()
        ]

        def originals() -> tuple[list[Span], SupportStats]:
            audit = CorrectionAudit()
            audit.formatting_only = True
            return list(spans), SupportStats(
                method=method,
                elapsed_s=_time.perf_counter() - t0,
                audit=audit,
            )

        page = spans[0].page if spans else 1
        has_text_layer = bool(text_layer) and len(text_layer.strip()) >= 200
        if has_text_layer:
            method = "support-spans-digital"
            prompt = self._prompts.render(
                "support_digital",
                fragments=format_fragments([s for _, s in numbered]),
                text_layer=(text_layer or "").strip(),
                page=page,
            )
        else:
            method = "support-spans-proofread"
            prompt = self._prompts.render(
                "support_scan",
                fragments=format_fragments([s for _, s in numbered]),
                page=page,
            )

        if not numbered:
            return originals()

        self.load()
        text, n_tokens, early_stop = self._generate(prompt, max_tokens)
        frags = parse_numbered_fragments(text, len(numbered))
        if frags is None:
            log.warning(
                "support output broke the numbered contract (%d fragments "
                "expected) — keeping original spans",
                len(numbered),
            )
            return originals()

        corrected = list(spans)
        audits: list[CorrectionAudit] = []
        total_in = sum(len(s.text) for _, s in numbered)
        total_out = 0
        for i, (idx, s) in enumerate(numbered):
            new_text = frags[i + 1]
            if not new_text:
                continue  # model emptied a fragment: keep the original
            total_out += len(new_text)
            if new_text == s.text:
                continue
            audits.append(
                audit_corrections(s.text, new_text, text_layer if has_text_layer else None)
            )
            corrected[idx] = replace(s, text=new_text)
        if total_out < 0.3 * max(1, total_in):
            log.warning(
                "support output degenerate (%d chars < 30%% of input) — "
                "keeping original spans",
                total_out,
            )
            return originals()

        audit = merge_audits(audits) if audits else CorrectionAudit(
            formatting_only=True
        )
        audit.log_summary(f"page {page}")
        return corrected, SupportStats(
            method=method,
            elapsed_s=_time.perf_counter() - t0,
            tokens=n_tokens,
            early_stop=early_stop,
            audit=audit,
        )

    def reflow_text(
        self,
        markdown: str,
        *,
        journal: str = "generic",
        prompt_override: str | None = None,
        text_layer: str | None = None,
        max_tokens: int = 6144,
    ) -> tuple[str, SupportStats]:
        """LLM reflow pass over client-rendered markdown.

        Unlike check_spans (which corrects WITHIN spans and never produces
        markdown), this starts from already-rendered markdown and applies a
        caller-supplied prompt — the seam Paperhub's reflow uses to reuse
        the resident support model with client-owned prompts.
        `journal` is an opaque label echoed back in stats; the server never
        interprets it. prompt_override supports plain {{markdown}} and
        {{journal}} substitution (deliberately not Jinja: the caller is
        trusted-but-remote, and simple replacement has no template footguns).
        Without an override a built-in proofread instruction applies.
        """
        import time as _time

        t0 = _time.perf_counter()
        source = markdown.strip()
        if prompt_override:
            prompt = prompt_override.replace("{{markdown}}", source).replace(
                "{{journal}}", journal
            )
            method = "reflow+journal-prompt"
        else:
            method = "reflow+proofread"
            prompt = (
                "Correct ONLY obvious OCR errors in the following markdown: "
                "misspellings, wrong or merged characters, broken words. "
                "Never paraphrase, never add or remove content; preserve "
                "every `<!-- ocr:page:N -->` anchor and all markdown/LaTeX "
                "formatting. Output ONLY the corrected markdown.\n\n"
                + source
            )

        self.load()
        text, n_tokens, early_stop = self._generate(prompt, max_tokens)
        audit = audit_corrections(source, text, None)

        # Degenerate output -> fall back to the input markdown.
        if len(text) < 0.3 * len(source):
            log.warning(
                "reflow output degenerate (%d chars < 30%% of input); "
                "falling back to input markdown",
                len(text),
            )
            text = source

        return text, SupportStats(
            method=method,
            elapsed_s=_time.perf_counter() - t0,
            tokens=n_tokens,
            early_stop=early_stop,
            audit=audit,
        )


#: Deprecated alias (pre-rename name).
CleanupEngine = SupportEngine
