"""Optional post-OCR cleanup stage.

Pipeline per page:
  1. deterministic pre-clean of OCR markdown (strip <|det|> markers/coords,
     drop empty det-only lines, dedupe loop-remnant lines)
  2. LLM stage (Qwen3.5-0.8B MLX 8-bit via mlx_vlm):
     - digital pages (text layer >= 200 chars): reconcile OCR structure with
       the publisher text layer AND proofread (misspellings etc.)
     - scanned pages: proofread-only prompt — fix obvious OCR misspellings
       from context; never paraphrase; preserve names/numbers/units
  3. token-level loop-break (same detector as OCR stage) + long-line dedupe

Every LLM edit is audited: the checker's input is word-diffed against its
output, and each changed word is attributed as
  - text-layer-backed: the replacement exists in the page's text layer
  - ocr-vocab-backed:  replacement appears elsewhere in the page's own OCR
  - invented:          replacement exists in neither (model "intuition") —
                       the hallucination-risk category, surfaced in logs
Corrections are logged at INFO per page and summarized in CleanupStats.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .engine import _dedupe_long_lines, _loop_period
from .prompts import PromptRegistry
from .spans import parse_spans, render_markdown, spans_to_jsonl

log = logging.getLogger("ocr_server")

DEFAULT_CLEANUP_MODEL = "mlx-community/Qwen3.5-0.8B-MLX-8bit"

_DET_RE = re.compile(r"<\|det\|>[^<]*<\|/det\|>")
_LEFTOVER_BRACKET_RE = re.compile(r"^\s*\[?\d+,\s*\d+(,\s*\d+)*\]?\s*$")
_MULTIBLANK_RE = re.compile(r"\n{3,}")
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_MARKDOWN_RE = re.compile(r"[#*_>`\[\]()\\|⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]")


def strip_det_markers(ocr_text: str) -> str:
    """Deterministic pre-clean: remove layout markers and coordinate noise."""
    out = _DET_RE.sub("", ocr_text)
    lines = []
    for line in out.splitlines():
        s = line.strip()
        if not s or _LEFTOVER_BRACKET_RE.match(s):
            continue
        if s.startswith("<|") and s.endswith("|>"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = _MULTIBLANK_RE.sub("\n\n", cleaned)
    return _dedupe_long_lines(cleaned).strip()


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
    """Diff between the checker's input and output, split into:

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
                "%s: checker formatting-only (%d -> %d content words, "
                "+%d/-%d markdown-structure words) — no content edits",
                page_label,
                self.n_words_in,
                self.n_words_out,
                self.format_added_words,
                self.format_removed_words,
            )
            return
        if self.n_edits == 0:
            log.info("%s: checker made no content edits", page_label)
            return
        samples = lambda xs: ", ".join(repr(x) for x in xs[:6]) + (
            f" …(+{len(xs) - 6})" if len(xs) > 6 else ""
        )
        log.info(
            "%s: checker CONTENT edits — %d | text-layer-backed: %s | "
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
    """Content-edit diff between checker input and output.

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

    removed = Counter(b) - Counter(a)  # words dropped by the checker
    added = Counter(a) - Counter(b)  # words introduced by the checker
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


# ---------------------------------------------------------------------------
# Cleanup engine
# ---------------------------------------------------------------------------

@dataclass
class CleanupStats:
    method: str  # "ocr+pymupdf+llm" | "ocr-llm-proofread" | "ocr-only"
    elapsed_s: float
    tokens: int | None = None
    early_stop: bool = False
    audit: CorrectionAudit | None = None
    spans_jsonl: str | None = None  # structured span intermediate (JSONL)


class CleanupEngine:
    """Lazy-loaded small LLM that merges OCR structure with the text layer
    and proofreads the result."""

    def __init__(
        self,
        model_ref: str = DEFAULT_CLEANUP_MODEL,
        prompts: PromptRegistry | None = None,
    ):
        if prompts is None or not prompts.loaded:
            raise ValueError(
                "CleanupEngine requires a loaded PromptRegistry "
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

    def cleanup_page(
        self,
        ocr_text: str,
        text_layer: str | None,
        max_tokens: int = 6144,
        page: int = 1,
    ) -> tuple[str, CleanupStats]:
        """Check/clean one page. Returns (markdown, stats); stats.spans_jsonl
        carries the structured span intermediate (see ocr_server.spans)."""
        import time as _time

        t0 = _time.perf_counter()
        spans = parse_spans(ocr_text, page=page)
        spans_jsonl = spans_to_jsonl(spans)
        pre = render_markdown(spans)

        has_text_layer = bool(text_layer) and len(text_layer.strip()) >= 200
        if has_text_layer:
            method = "ocr+pymupdf+llm"
            prompt = self._prompts.render(
                "checker_digital", ocr=pre, text_layer=(text_layer or "").strip(), page=page
            )
        else:
            method = "ocr-llm-proofread"
            prompt = self._prompts.render("checker_scan", ocr=pre, page=page)

        self.load()
        text, n_tokens, early_stop = self._generate(prompt, max_tokens)
        audit = audit_corrections(pre, text, text_layer if has_text_layer else None)

        # Degenerate output -> fall back to the deterministic markdown render.
        if len(text) < 0.3 * len(pre):
            log.warning(
                "checker output degenerate (%d chars < 30%% of input); "
                "falling back to deterministic markdown",
                len(text),
            )
            text = pre

        return text, CleanupStats(
            method=method,
            elapsed_s=_time.perf_counter() - t0,
            tokens=n_tokens,
            early_stop=early_stop,
            audit=audit,
            spans_jsonl=spans_jsonl,
        )

    def reflow_text(
        self,
        markdown: str,
        *,
        journal: str = "generic",
        prompt_override: str | None = None,
        text_layer: str | None = None,
        max_tokens: int = 6144,
    ) -> tuple[str, CleanupStats]:
        """LLM reflow pass over client-rendered markdown.

        Unlike cleanup_page (which starts from raw OCR text and the server's
        own checker prompts), this starts from already-rendered markdown and
        applies a caller-supplied prompt — the seam Paperhub's journal reflow
        uses to reuse the resident checker model with client-owned prompts.
        `journal` is an opaque label echoed back in stats; the server never
        interprets it. prompt_override supports plain {{markdown}} and
        {{journal}} substitution (deliberately not Jinja: the caller is
        trusted-but-remote, and simple replacement has no template footguns).
        Without an override the server's proofread prompt applies.
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
            has_text_layer = bool(text_layer) and len(text_layer.strip()) >= 200
            if has_text_layer:
                method = "reflow+checker-digital"
                prompt = self._prompts.render(
                    "checker_digital",
                    ocr=source,
                    text_layer=(text_layer or "").strip(),
                    page=1,
                )
            else:
                method = "reflow+checker-proofread"
                prompt = self._prompts.render("checker_scan", ocr=source, page=1)

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

        return text, CleanupStats(
            method=method,
            elapsed_s=_time.perf_counter() - t0,
            tokens=n_tokens,
            early_stop=early_stop,
            audit=audit,
        )
