"""Layout pre-scan: a cheap global page description from the support VLM.

Stage order per page: layout-scan (support VLM, low-res thumbnail) -> OCR
(with a one-sentence layout hint) -> support correction (span-wise pass).

The profile is intentionally coarse: body-column count, running
header/footer text, and large skip-figures as 0-1000 boxes. It drives two
consumers:

  1. a text hint appended to the OCR prompt (no geometry), and
  2. a deterministic span filter (relabel only, never renumber — the span
     identity from ocr_server.spans is preserved).

Any validation failure yields None: the pipeline proceeds exactly as if no
layout existed (gundam OCR + generic furniture + support correction).
Content is never dropped on model misbehavior.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from .furniture import _band, _fingerprint

log = logging.getLogger("ocr_server")

#: Column layouts the scanner may report. "mixed" covers pages whose column
#: structure changes mid-page (e.g. full-width title over two-column body).
COLUMNS_VALUES = ("1", "2", "3", "mixed")

_COLUMN_WORDS = {"1": "single-column", "2": "two-column", "3": "three-column", "mixed": "mixed multi-column"}

#: Minimum box dimension (0-1000 space) for a reported figure. Smaller boxes
#: are inline graphics, not layout furniture — ignoring them keeps the OCR
#: prompt focused on real skips.
MIN_FIGURE_SIZE = 60

#: Below this confidence the profile is usable as a prompt hint but never
#: for deterministic span filtering (hint-only mode).
FILTER_MIN_CONFIDENCE = 0.5

#: Figure filtering never relabels more than this share of a page's content
#: spans; beyond it the boxes are assumed wrong and the page is left alone.
MAX_FIGURE_DROP_SHARE = 0.5

#: Figure boxes are rough: shrink each edge by this margin before testing
#: containment so captions sitting on a figure's edge survive.
FIGURE_INSET = 10

#: Cap on figure boxes per page (pathological outputs truncated, not failed).
MAX_FIGURES = 8


@dataclass
class LayoutProfile:
    """Coarse per-page layout from the support VLM's pre-scan."""

    page: int
    columns: str = "1"
    header: str | None = None
    footer: str | None = None
    figures: list[list[int]] = field(default_factory=list)
    confidence: float = 0.5
    method: str = "support-scan"
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "columns": self.columns,
            "header": self.header,
            "footer": self.footer,
            "figures": [list(b) for b in self.figures],
            "confidence": self.confidence,
            "method": self.method,
            "elapsed_s": round(self.elapsed_s, 3),
        }


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text[:200]


def _clean_box(value: object) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        box = [int(v) for v in value]
    except (TypeError, ValueError):
        return None
    if any(not 0 <= v <= 1000 for v in box):
        return None
    x1, y1, x2, y2 = box
    # No separate inversion check: an inverted or zero-size axis gives a
    # non-positive dimension, which the size floor below always rejects.
    if min(x2 - x1, y2 - y1) < MIN_FIGURE_SIZE:
        return None
    return box


def parse_layout_profile(raw: str, page: int) -> LayoutProfile | None:
    """Parse the scanner's raw output into a LayoutProfile.

    Strict but total: returns None on any failure (no JSON, wrong types,
    unknown columns value) instead of raising — callers treat None as
    "no layout" and run the unhinted pipeline.
    """
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        data = json.loads(raw[start:end])
    except (ValueError, AttributeError):
        return None
    if not isinstance(data, dict):
        return None  # pragma: no cover - defensive: a brace-delimited slice parses to a dict or raises

    columns = data.get("columns", "1")
    if isinstance(columns, int) and columns in (1, 2, 3):
        columns = str(columns)
    if columns not in COLUMNS_VALUES:
        return None

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        return None
    confidence = min(1.0, max(0.0, confidence))

    figures: list[list[int]] = []
    raw_figs = data.get("figures", [])
    if isinstance(raw_figs, list):
        for item in raw_figs[:MAX_FIGURES]:
            box = item.get("box", item) if isinstance(item, dict) else item
            clean = _clean_box(box)
            if clean is not None:
                figures.append(clean)

    return LayoutProfile(
        page=page,
        columns=columns,
        header=_clean_text(data.get("header")),
        footer=_clean_text(data.get("footer")),
        figures=figures,
        confidence=confidence,
    )


def layout_hint(profile: LayoutProfile | None) -> str:
    """One-sentence OCR prompt hint for a profile ("" when None)."""
    if profile is None:
        return ""
    parts = [f"Layout: {_COLUMN_WORDS[profile.columns]}."]
    furniture = [t for t in (profile.header, profile.footer) if t]
    if furniture:
        quoted = "; ".join(f'"{t}"' for t in furniture)
        parts.append(f"Ignore running header/footer lines like {quoted}.")
    if profile.figures:
        parts.append(f"Skip {len(profile.figures)} large figure region(s) — do not transcribe text inside them.")
    parts.append("Read body columns top-to-bottom in reading order.")
    return " ".join(parts)


def _furniture_hit(span_text: str, furniture_text: str) -> bool:
    """True when a span looks like a reported running header/footer.

    Digit-normalized (page numbers collapse) with substring matching either
    way, so "Nature | www.nature.com 12" matches a reported "Nature |
    www.nature.com" footer.
    """
    span_fp = _fingerprint(span_text)
    furn_fp = _fingerprint(furniture_text)
    if not span_fp or not furn_fp:
        return False
    return furn_fp in span_fp or span_fp in furn_fp


def _inside_figure(span_box: list[int], fig: list[int]) -> bool:
    fx1, fy1, fx2, fy2 = fig
    x1, y1, x2, y2 = span_box
    return (
        x1 >= fx1 + FIGURE_INSET
        and y1 >= fy1 + FIGURE_INSET
        and x2 <= fx2 - FIGURE_INSET
        and y2 <= fy2 - FIGURE_INSET
    )


def apply_layout_filter(spans: list, profile: LayoutProfile | None) -> dict:
    """Relabel layout-identified spans in place; returns audit counts.

    - Running header/footer matches (top/bottom band + text match) become
      `furniture` — the same lossless label the generic pass uses.
    - Text spans fully inside a reported figure box become `furniture`
      (kept in spans_jsonl, excluded from the markdown render).

    Guards: hint-only below FILTER_MIN_CONFIDENCE; box-less, title, and
    already-furniture spans are never touched; figure drops are reverted
    when they would take more than MAX_FIGURE_DROP_SHARE of the page's
    content spans. Span ids, boxes, and order are never modified.
    """
    counts = {"figures_skipped": 0, "furniture_flagged": 0}
    if profile is None or profile.confidence < FILTER_MIN_CONFIDENCE:
        return counts

    furniture_texts = [t for t in (profile.header, profile.footer) if t]
    for span in spans:
        if span.label in ("furniture", "title") or span.box is None or not span.text.strip():
            continue
        if _band(span) is None:
            continue
        if any(_furniture_hit(span.text, t) for t in furniture_texts):
            span.label = "furniture"
            counts["furniture_flagged"] += 1

    if profile.figures:
        content = [
            s
            for s in spans
            if s.label not in ("furniture", "title", "image")
            and s.box is not None
            and s.text.strip()
        ]
        candidates = [
            s
            for s in content
            if any(_inside_figure(s.box, fig) for fig in profile.figures)
        ]
        # Degenerate guard: boxes covering most of the page are wrong.
        if candidates and len(candidates) <= MAX_FIGURE_DROP_SHARE * max(1, len(content)):
            for span in candidates:
                span.label = "furniture"
                counts["figures_skipped"] += 1
        elif candidates:
            log.warning(
                "page %d: layout figure boxes would drop %d/%d content spans — "
                "ignoring figure filter for this page",
                spans[0].page if spans else 0,
                len(candidates),
                len(content),
            )
    return counts
