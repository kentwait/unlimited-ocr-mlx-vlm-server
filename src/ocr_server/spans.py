"""Structured span representation of Unlimited-OCR output (JSONL intermediate).

The OCR model emits plain text with inline layout markers:

    <|det|>title [64, 56, 945, 131]<|/det|>A global view of human centromere...
    <|det|>text [64, 183, 341, 197]<|/det|>https://doi.org/10.1038/...
    <|det|>image [48, 58, 930, 660]<|/det|>

This module parses those into an explicit intermediate representation — one
JSON record per detected span:

    {"id": "p1-1", "page": 1, "label": "title", "box": [64, 56, 945, 131], "text": "A global view..."}

Pipeline: OCR text -> spans (JSONL) -> optional span-wise checking ->
markdown. Boxes are in the model's 0-1000 normalized coordinate space. Span
ids are the identity contract downstream (Paperhub renders markdown from
spans and highlights by id), so they are assigned here and preserved through
checking. Markdown rendering on the server is a frozen deterministic
convenience; Paperhub renders its own from the JSONL.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

_DET_SPAN_RE = re.compile(
    r"(?:<\|det\|>\s*)?(?P<label>[\w ]*?)\s*\[(?P<box>[\d,\s]*)\]\s*"
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
    id: str = ""  # identity contract downstream; assigned by parse_spans

    def to_dict(self) -> dict:
        return asdict(self)


#: Journals known to the render policy. Mirrors Paperhub's shared
#: journal-formats table — bump together, fail loudly on skew.
JOURNALS: tuple[str, ...] = ("generic", "nature", "science", "pmc")

#: Span labels structural in every journal: never rendered, never drawn.
STRUCTURAL_LABELS: frozenset[str] = frozenset(
    {
        "furniture",
        "page",
        "header",
        "footer",
        "page_number",
        "aside_text",
        "page_footnote",
    }
)

#: Per-journal drop sets. Entries override wholesale (full copies, not
#: merges) so each journal reads explicitly; all four match today, and
#: real per-journal differences land here — never in ad-hoc conditionals.
JOURNAL_DROP_LABELS: dict[str, frozenset[str]] = {
    journal: STRUCTURAL_LABELS for journal in JOURNALS
}


def drop_labels_for(journal: str) -> frozenset[str]:
    """Drop set for a journal (unknown journals get the universal set —
    the API boundary rejects them with 400 first)."""
    return JOURNAL_DROP_LABELS.get(journal, STRUCTURAL_LABELS)


def parse_spans(ocr_text: str, page: int = 1) -> list[Span]:
    """Parse OCR text into spans; unmatched non-marker text becomes plain
    text records so no content is silently dropped. Spans get stable ids
    (`p{page}-{index}`, 1-based within the page) — the identity contract
    downstream."""
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
        if body:  # pragma: no cover - unreachable: any non-blank text yields a span above
            spans.append(Span(page=page, label="text", box=None, text=body))
    for i, s in enumerate(spans):
        s.id = f"p{page}-{i + 1}"
    return spans


def spans_to_jsonl(spans: list[Span]) -> str:
    """Serialize spans as JSONL (one JSON object per line)."""
    return "\n".join(json.dumps(s.to_dict(), ensure_ascii=False) for s in spans)


def render_markdown(spans: list["Span"], journal: str = "generic") -> str:
    """Deterministic markdown rendering of spans (the formatting step).

    Skips the journal's structural spans (see JOURNAL_DROP_LABELS);
    titles become headings; image spans and empty text become figure
    markers; everything else renders as plain paragraphs. When a page
    carries ONLY droppable spans but some are page spans (the model
    emitted no finer structure), the page spans render as text so no
    content is silently dropped.
    """
    drop = drop_labels_for(journal)
    renderable = [s for s in spans if s.label not in drop]
    if not renderable:
        renderable = [s for s in spans if s.label == "page"]
    parts: list[str] = []
    for s in renderable:
        if s.label == "image" or not s.text:
            parts.append("*[figure]*")
        elif s.label == "title":
            parts.append(f"# {s.text}")
        else:
            parts.append(s.text)
    return "\n\n".join(p for p in parts if p.strip()).strip()
