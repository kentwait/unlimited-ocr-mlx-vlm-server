"""Structured span representation (JSONL intermediate) and identity contract.

One JSON record per span:

    {"id": "p1-1", "page": 1, "label": "text", "box": [64, 56, 945, 131], "text": "..."}

Figure spans additionally carry an inline PNG data URI:

    {"id": "p1-14", "page": 1, "label": "image", "box": [...], "text": "",
     "image": "data:image/png;base64,..."}

Boxes are 0-1000 ints (the model coordinate space used across the app).
Span ids (`p{page}-{index}`, 1-based within the page, reading order) are the
identity contract downstream: Paperhub renders markdown from spans and
highlights by id, so ids are assigned once and never renumbered.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass
class Span:
    page: int
    label: str
    box: list[int] | None  # [x1, y1, x2, y2] in 0-1000 space; None if unknown
    text: str
    id: str = ""
    image: str | None = None  # PNG data URI for figure spans

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.image is None:
            # Keep the JSONL lean: only figure spans carry the payload.
            data.pop("image")
        return data


def assign_ids(spans: list[Span]) -> None:
    """Assign stable ids in list order, per page (`p{page}-{n}`). Mutates."""
    counters: dict[int, int] = {}
    for span in spans:
        n = counters.get(span.page, 0) + 1
        counters[span.page] = n
        span.id = f"p{span.page}-{n}"


def spans_to_jsonl(spans: list[Span]) -> str:
    """Serialize spans as JSONL (one JSON object per line)."""
    return "\n".join(json.dumps(s.to_dict(), ensure_ascii=False) for s in spans)
