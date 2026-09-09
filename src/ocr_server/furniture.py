"""Furniture removal pass: journal headers/footers/side stamps.

Runs on the span intermediate BEFORE markdown rendering and the checker LLM —
this is a layout-transformation pass, separate from content correction.

Two layers:

1. **Journal templates** (nature / science / pmc): position-band + regex rules
   encoding each publisher's furniture placement. Auto-detected per document
   by scoring rule hits across pages; can be forced via the `furniture` form
   field ("none" disables everything).

2. **Generic repetition fingerprinting** (always on for multi-page docs): any
   span in the top 6% / bottom 5% of the page whose digit-normalized text
   repeats on >= max(2, 50%) of pages is furniture — catches unknown journals
   without a template.

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
# PMC stamps sit slightly higher; the pmc template overrides its bottom band.

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


# ---------------------------------------------------------------------------
# Journal templates: (band, regex) rules. Case-insensitive substring match.
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict] = {
    "nature": {
        "top_band": (0, 45),
        "top_rules": [r"^article$"],
        "bottom_band": (935, 1000),
        "bottom_rules": [r"nature", r"www\.nature\.com"],
        "anywhere_rules": [],
    },
    "science": {
        "top_band": (0, 60),
        "top_rules": [r"^research\b", r"completing the human genome"],
        "bottom_band": (945, 1000),
        "bottom_rules": [r"science\s+\d+", r"\bof \d+\b"],
        "anywhere_rules": [],
    },
    "pmc": {
        "top_band": (0, 80),
        "top_rules": [r"^page \d+"],
        "bottom_band": (870, 1000),
        "bottom_rules": [r"author manuscript", r"available in pmc", r"^graphical abstract$"],
        "anywhere_rules": [r"^author manuscript$"],
    },
}

_NORM_STRIP_RE = re.compile(r"[^a-z0-9 ]")


def _matches(span_text: str, rules: list[str]) -> bool:
    t = _NORM_STRIP_RE.sub(" ", span_text.lower())
    t = _WS_RE.sub(" ", t).strip()
    return any(re.search(rx, t) for rx in rules)


def _in_band(span: "Span", band: tuple[int, int]) -> bool:
    """True when the span STARTS inside the band (top edge in [lo, hi])."""
    if span.box is None:
        return False
    y1 = span.box[1]
    return band[0] <= y1 <= band[1]


def _rule_hits(pages_spans: list[list["Span"]], tpl: dict) -> int:
    """Pages on which at least one template rule fires."""
    hits = 0
    for spans in pages_spans:
        fired = False
        for s in spans:
            if not s.text:
                continue
            if (
                _in_band(s, tpl["top_band"])
                and _matches(s.text, tpl["top_rules"])
            ) or (
                _in_band(s, tpl["bottom_band"])
                and _matches(s.text, tpl["bottom_rules"])
            ) or (
                tpl["anywhere_rules"] and _matches(s.text, tpl["anywhere_rules"])
            ):
                fired = True
                break
        if fired:
            hits += 1
    return hits


def detect_template(pages_spans: list[list["Span"]]) -> str | None:
    """Pick the template whose rules fire on enough pages; None if none does."""
    n = len(pages_spans)
    need = max(1, int(0.4 * n + 0.999))  # >=40% of pages, at least 1
    best, best_hits = None, 0
    for name, tpl in TEMPLATES.items():
        hits = _rule_hits(pages_spans, tpl)
        if hits >= need and hits > best_hits:
            best, best_hits = name, hits
    return best


def _apply_template(pages_spans, tpl: dict) -> int:
    removed = 0
    for spans in pages_spans:
        for s in spans:
            if s.label == "furniture" or not s.text:
                continue
            if (
                (_in_band(s, tpl["top_band"]) and _matches(s.text, tpl["top_rules"]))
                or (_in_band(s, tpl["bottom_band"]) and _matches(s.text, tpl["bottom_rules"]))
                or (tpl["anywhere_rules"] and _matches(s.text, tpl["anywhere_rules"]))
            ):
                s.label = "furniture"
                removed += 1
    return removed


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

    template: "auto" | "none" | a TEMPLATES key.
    """
    n_pages = len(pages_spans)
    tpl_name = None
    if template != "none":
        if template in TEMPLATES:
            tpl_name = template
        else:  # auto
            tpl_name = detect_template(pages_spans)

    tpl_removed = 0
    if tpl_name is not None:
        tpl_removed = _apply_template(pages_spans, TEMPLATES[tpl_name])
    generic_removed = _apply_generic(pages_spans) if tpl_name is not None or template == "auto" else 0

    per_page_counts = [sum(1 for s in spans if s.label == "furniture") for spans in pages_spans]
    samples = [
        next(s.text for s in spans if s.label == "furniture")[:70]
        for spans in pages_spans
        if any(s.label == "furniture" for s in spans)
    ][:3]
    log.info(
        "furniture pass: template=%s removed=%d (template %d, generic %d) "
        "across %d pages | per-page: %s | samples: %s",
        tpl_name or "none",
        sum(per_page_counts),
        tpl_removed,
        generic_removed,
        n_pages,
        per_page_counts,
        samples or "none",
    )
    return {
        "template": tpl_name,
        "removed_total": sum(per_page_counts),
        "removed_by_page": per_page_counts,
        "samples": samples,
    }
