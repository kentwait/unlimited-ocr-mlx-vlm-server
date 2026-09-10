"""Native layout extraction: PDF internals via pymupdf4llm.

Digital-born PDFs only. The GNN layout model in pymupdf-layout labels text
blocks (text, list-item, section-header, caption, footnote,
page-header/footer, picture) with boxes in reading order. This module maps
those labels into the server's span vocabulary; the pipeline later merges
detected figure regions and relabels text that falls inside them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pymupdf4llm

#: pymupdf4llm/pymupdf-layout boxclass -> server span label.
#: Unknown classes map to "text" so no content is silently dropped.
LABEL_MAP: dict[str, str] = {
    "text": "text",
    "list-item": "list-item",
    "section-header": "title",
    "title": "title",
    "doc_title": "title",
    "caption": "caption",
    "footnote": "footnote",
    "page-header": "header",
    "page-footer": "footer",
    "page-number": "page_number",
    "picture": "picture",
}

#: Labels eligible to become `figure_text` when their box center falls
#: inside a detected figure region. Restricting to content labels keeps
#: captions, titles, and furniture out of the relabeling.
FIGURE_CONTAINABLE = frozenset({"text", "list-item"})

#: pymupdf4llm boxclasses that never render as their own span; the pipeline
#: either suppresses them (page rules/noise) or replaces them with figures.
PICTURE_CLASS = "picture"


@dataclass
class NativeBox:
    """One pymupdf4llm element, normalized into span vocabulary."""

    page: int
    label: str
    box: list[int]  # 0-1000 ints
    text: str
    order: int  # document reading order within the page


def normalize_box(
    box: list[float] | tuple[float, ...], width: float, height: float
) -> list[int]:
    """Normalize a PDF-points box into clamped 0-1000 ints.

    Degenerate pages (zero width/height) yield a zero box; x/y inversion is
    repaired by sorting each axis.
    """
    if width <= 0 or height <= 0:
        return [0, 0, 0, 0]
    x0, y0, x1, y1 = (float(v) for v in box)
    xs = sorted((x0 / width * 1000.0, x1 / width * 1000.0))
    ys = sorted((y0 / height * 1000.0, y1 / height * 1000.0))

    def clamp(value: float) -> int:
        return max(0, min(1000, int(round(value))))

    return [clamp(xs[0]), clamp(ys[0]), clamp(xs[1]), clamp(ys[1])]


def _box_text(box: dict) -> str:
    """Join the text spans of one pymupdf4llm box (empty when none)."""
    parts: list[str] = []
    for line in box.get("textlines") or []:
        for span in line.get("spans") or []:
            text = span.get("text")
            if text:
                parts.append(text)
    return " ".join(parts).strip()


def missing_text_pages(doc, page_nums: list[int]) -> list[int]:
    """Pages (1-indexed) with no extractable text layer.

    Digital-born PDFs only: a page without text is either a scan or blank,
    and the routing/OCR fallback for those is an explicit future cutover.
    """
    return [n for n in page_nums if not doc[n - 1].get_text().strip()]


def extract_boxes(doc, page_nums: list[int]) -> dict[int, list[NativeBox]]:
    """Run pymupdf4llm Layout over the requested pages (0-based handling).

    Returns {page: [NativeBox]} in reading order. Raises on pymupdf4llm
    failure — the pipeline maps that to a 400.
    """
    raw = pymupdf4llm.to_json(
        doc, pages=[n - 1 for n in page_nums], use_ocr=False
    )
    data = json.loads(raw) if isinstance(raw, str) else raw
    out: dict[int, list[NativeBox]] = {}
    for page_data in data.get("pages", []):
        page = int(page_data["page_number"])
        width = float(page_data.get("width") or 0.0)
        height = float(page_data.get("height") or 0.0)
        boxes: list[NativeBox] = []
        for box in page_data.get("boxes") or []:
            raw_class = str(box.get("boxclass") or "text")
            label = LABEL_MAP.get(raw_class, "text")
            text = _box_text(box)
            if label != PICTURE_CLASS and not text:
                # Pictures are merge-handled; empty elements render nothing.
                continue
            normalized = normalize_box(
                [box.get("x0", 0), box.get("y0", 0), box.get("x1", 0), box.get("y1", 0)],
                width,
                height,
            )
            boxes.append(
                NativeBox(
                    page=page,
                    label=label,
                    box=normalized,
                    text=text,
                    order=len(boxes),  # contiguous after empty-element skips
                )
            )
        out[page] = boxes
    return out
