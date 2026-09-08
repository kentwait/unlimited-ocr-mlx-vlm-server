"""Optional post-OCR cleanup stage.

Pipeline per page:
  1. deterministic pre-clean of OCR markdown (strip <|det|> markers/coords,
     drop empty det-only lines, dedupe loop-remnant lines)
  2. if the PDF page has a usable text layer (digital-born page), a small LLM
     (Qwen3.5-0.8B MLX 4-bit via mlx_vlm) reconciles OCR structure with the
     publisher text layer and emits clean Markdown
  3. token-level loop-break (same detector as OCR stage) + long-line dedupe

The LLM only runs when a text layer exists — it is the ground truth for
wording; without it (scanned pages) the LLM would be free to "correct" real
OCR text into plausible hallucinations, so those pages get step 1 only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .engine import _dedupe_long_lines, _loop_period

DEFAULT_CLEANUP_MODEL = "mlx-community/Qwen3.5-0.8B-MLX-8bit"

_DET_RE = re.compile(r"<\|det\|>[^<]*<\|/det\|>")
_LEFTOVER_BRACKET_RE = re.compile(r"^\s*\[?\d+,\s*\d+(,\s*\d+)*\]?\s*$")
_MULTIBLANK_RE = re.compile(r"\n{3,}")


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


@dataclass
class CleanupStats:
    method: str  # "ocr+pymupdf+llm" | "ocr-only"
    elapsed_s: float
    tokens: int | None = None
    early_stop: bool = False


class CleanupEngine:
    """Lazy-loaded small LLM that merges OCR structure with the text layer."""

    def __init__(self, model_ref: str = DEFAULT_CLEANUP_MODEL):
        self.model_ref = model_ref
        self.model: Any = None
        self.processor: Any = None

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def load(self) -> None:
        if self.loaded:
            return
        from mlx_vlm import load

        self.model, self.processor = load(self.model_ref)

    def _generate(self, prompt: str, max_tokens: int) -> tuple[str, int, bool]:
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
        self, ocr_text: str, text_layer: str | None, max_tokens: int = 6144
    ) -> tuple[str, CleanupStats]:
        import time as _time

        t0 = _time.perf_counter()
        pre = strip_det_markers(ocr_text)
        if not text_layer or len(text_layer.strip()) < 200:
            return pre, CleanupStats(method="ocr-only", elapsed_s=_time.perf_counter() - t0)

        self.load()
        prompt = f"""You are cleaning OCR output of one page of an academic paper.

OCR MARKDOWN (structure hints; may contain garbled or repeated fragments):
<<<OCR
{pre}
OCR>>>

PDF TEXT LAYER (exact words from the publisher, ground truth for wording and numbers; reading order may differ):
<<<TEXT
{text_layer.strip()}
TEXT>>>

TASK: Produce clean Markdown of the page. The PDF text layer is the source of truth for wording and numbers; use the OCR for structure (headings, figure placement) and for anything missing from the text layer. Keep section headings as Markdown headings. Do not invent content. Output ONLY the Markdown."""
        text, n_tokens, early_stop = self._generate(prompt, max_tokens)
        # Guard against empty/degenerate output: fall back to pre-cleaned OCR.
        if len(text) < 0.3 * len(pre):
            return pre, CleanupStats(
                method="ocr+pymupdf+llm",
                elapsed_s=_time.perf_counter() - t0,
                tokens=n_tokens,
                early_stop=early_stop,
            )
        return text, CleanupStats(
            method="ocr+pymupdf+llm",
            elapsed_s=_time.perf_counter() - t0,
            tokens=n_tokens,
            early_stop=early_stop,
        )
