"""Furniture removal pass: repeated headers/footers/page stamps.

Runs on the span intermediate BEFORE markdown rendering and the checker LLM —
this is a layout-transformation pass, separate from content correction.

Generic repetition fingerprinting only (deliberately journal-agnostic): any
span in the top 6% / bottom 5% of the page whose digit-normalized text
repeats on >= max(2, 50%) of pages is furniture. Journal-specific templates
used to live here; they moved to Paperhub's client-side reflow layer, which
owns all academic-paper rules on top of the `spans_jsonl` contract.

Furniture spans are RELABELED `furniture` and kept in `spans_jsonl`
(lossless — consumers can recover them); they are excluded from the markdown
render. All decisions are logged at INFO with samples.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .spans import Span

log = logging.getLogger("ocr_server")

# Positional bands in the model's 0-1000 page space (box = [x1, y1, x2, y2]).
TOP_BAND = 60  # span top edge above this -> top band
BOTTOM_BAND = 950  # span bottom edge below this -> bottom band
# Generic fingerprinting only trusts SHORT band spans; long ones (titles,
# abstracts) near the top are content even when they repeat (e.g. continued
# abstract pages).
MAX_GENERIC_CHARS = 120
# PMC stamps sit slightly higher; the generic bottom band still catches them
# through repetition (they repeat on every page by definition).

# Digit-normalized text -> fingerprint (page numbers, dates, volumes collapse).
_DIGITS_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


def _fingerprint(text: str) -> str:
    return _WS_RE.sub(" ", _DIGITS_RE.sub("#", text)).strip().lower()


def _band(span: "Span") -> str | None:
    if span.box is None:
        return None
    y1, y2 = span.box[1], span.box[3]
    if y1 < TOP_BAND:
        return "top"
    if y2 > BOTTOM_BAND:
        return "bottom"
    return None


def _apply_generic(pages_spans) -> int:
    """Repetition fingerprinting in top/bottom bands across >=2 pages."""
    n = len(pages_spans)
    if n < 2:
        return 0
    need = max(2, -(-n // 2))  # ceil(n/2), at least 2
    removed = 0
    for want_band in ("top", "bottom"):
        per_page: list[set[str]] = []
        for spans in pages_spans:
            fps = {
                _fingerprint(s.text)
                for s in spans
                if s.label not in ("furniture", "title")
                and s.box is not None
                and s.text
                and len(s.text) <= MAX_GENERIC_CHARS
                and _band(s) == want_band
            }
            per_page.append(fps)
        counts: Counter = Counter()
        for fps in per_page:
            counts.update(fps)
        repeated = {fp for fp, c in counts.items() if c >= need}
        if not repeated:
            continue
        for spans, fps in zip(pages_spans, per_page):
            for s in spans:
                if s.label == "furniture" or s.box is None or not s.text:
                    continue
                if _band(s) == want_band and _fingerprint(s.text) in repeated:
                    s.label = "furniture"
                    removed += 1
    return removed


def apply_furniture(
    pages_spans: list[list["Span"]], template: str = "auto"
) -> dict:
    """Relabel furniture spans in place. Returns an info dict for logging.

    template: "auto" (generic fingerprinting) | "none" (disabled).
    Anything else raises ValueError — journal templates live in Paperhub now.
    The info dict keeps its shape ({template, removed_total, removed_by_page,
    samples}) with template always None: generic detection has no name.
    """
    if template not in ("auto", "none"):
        raise ValueError(
            f"unknown furniture mode {template!r}: expected 'auto' or 'none' "
            "(journal templates moved to Paperhub's reflow layer)"
        )
    n_pages = len(pages_spans)

    generic_removed = _apply_generic(pages_spans) if template == "auto" else 0

    per_page_counts = [sum(1 for s in spans if s.label == "furniture") for spans in pages_spans]
    samples = [
        next(s.text for s in spans if s.label == "furniture")[:70]
        for spans in pages_spans
        if any(s.label == "furniture" for s in spans)
    ][:3]
    log.info(
        "furniture pass: removed=%d (generic %d) "
        "across %d pages | per-page: %s | samples: %s",
        sum(per_page_counts),
        generic_removed,
        n_pages,
        per_page_counts,
        samples or "none",
    )
    return {
        "template": None,
        "removed_total": sum(per_page_counts),
        "removed_by_page": per_page_counts,
        "samples": samples,
    }
