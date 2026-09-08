"""Structured span representation of Unlimited-OCR output (JSONL intermediate).

The OCR model emits plain text with inline layout markers:

    <|det|>title [64, 56, 945, 131]<|/det|>A global view of human centromere...
    <|det|>text [64, 183, 341, 197]<|/det|>https://doi.org/10.1038/...
    <|det|>image [48, 58, 930, 660]<|/det|>

This module parses those into an explicit intermediate representation — one
JSON record per detected span:

    {"page": 1, "label": "title", "box": [64, 56, 945, 131], "text": "A global view..."}

Pipeline: OCR text -> spans (JSONL) -> markdown. Boxes are in the model's
0-1000 normalized coordinate space; JSONL preserves layout structure
losslessly while markdown rendering is a separate deterministic step, so
formatting churn and content edits can be audited independently. The API can
expose this JSONL alongside markdown in the future.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

_DET_SPAN_RE = re.compile(
    r"<\|det\|>\s*(?P<label>[\w ]*?)\s*\[(?P<box>[\d,\s]*)\]\s*"
    r"<\|/det\|>(?P<text>.*?)(?=<\|det\|>|\Z)",
    re.DOTALL,
)
_PAGE_RE = re.compile(r"<PAGE>")


@dataclass
class Span:
    page: int
    label: str
    box: list[int] | None  # [x1, y1, x2, y2] in 0-1000 space; None if unknown
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_spans(ocr_text: str, page: int = 1) -> list[Span]:
    """Parse OCR text into spans; unmatched non-marker text becomes plain
    text records so no content is silently dropped."""
    spans: list[Span] = []
    matched_end = 0
    for m in _DET_SPAN_RE.finditer(ocr_text):
        # text between spans that no marker claimed -> plain record
        gap = ocr_text[matched_end : m.start()].strip()
        if gap:
            spans.append(Span(page=page, label="text", box=None, text=gap))
        box_raw = [x for x in re.findall(r"\d+", m.group("box"))]
        box = [int(x) for x in box_raw[:4]] if len(box_raw) == 4 else None
        text = _PAGE_RE.sub("", m.group("text")).strip()
        spans.append(
            Span(page=page, label=m.group("label").strip() or "text", box=box, text=text)
        )
        matched_end = m.end()
    tail = ocr_text[matched_end:].strip()
    if tail:
        spans.append(Span(page=page, label="text", box=None, text=_PAGE_RE.sub("", tail).strip()))
    if not spans:
        body = _PAGE_RE.sub("", ocr_text).strip()
        if body:
            spans.append(Span(page=page, label="text", box=None, text=body))
    return spans


def spans_to_jsonl(spans: list[Span]) -> str:
    """Serialize spans as JSONL (one JSON object per line)."""
    return "\n".join(json.dumps(s.to_dict(), ensure_ascii=False) for s in spans)


def render_markdown(spans: list[Span]) -> str:
    """Deterministic markdown rendering of spans (the formatting step)."""
    parts: list[str] = []
    for i, s in enumerate(spans):
        if s.label == "image" or not s.text:
            parts.append("*[figure]*")
        elif s.label == "title":
            parts.append(f"# {s.text}")
        else:
            parts.append(s.text)
    return "\n\n".join(p for p in parts if p.strip()).strip()


def strip_det_markers(ocr_text: str, page: int = 1) -> str:
    """Render OCR text to markdown via the span intermediate (no markers)."""
    return render_markdown(parse_spans(ocr_text, page=page))
