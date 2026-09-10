"""Request/response schemas shared by the API.

The server parses digital-born PDFs only: pymupdf4llm supplies text and
structure from the PDF internals, PP-DocLayout-S supplies figure regions.
There is no OCR and no LLM stage, so page results carry only timing, the
span JSONL contract, and warnings.
"""

from __future__ import annotations

from pydantic import BaseModel


class PageResult(BaseModel):
    page: int
    elapsed_s: float
    spans_jsonl: str  # one JSON object per span; see spans.py
    warnings: list[str] = []


class DocumentParseResponse(BaseModel):
    kind: str  # "pdf"
    n_pages: int
    results: list[PageResult]
    total_elapsed_s: float


class HealthResponse(BaseModel):
    status: str  # "ok"
    parser: str  # pymupdf4llm
    layout_model: str  # bundled ONNX model name


class JobStatus(BaseModel):
    job_id: str
    status: str  # pending | running | done | error
    kind: str | None = None
    filename: str | None = None
    error: str | None = None
    result: DocumentParseResponse | None = None
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    # Client-facing progress (UI polls this).
    phase: str | None = None  # "parse"
    pages_done: int = 0
    pages_total: int | None = None


class AssistantStatus(BaseModel):
    """Local assistant model lifecycle, polled by the chat panel."""

    available: bool  # the optional model runtime is installed in this build
    state: str  # not_downloaded | downloading | loading | ready | failed
    model: str  # pinned model reference
    loaded: bool = False  # weights resident in memory
    progress: float | None = None  # 0..1 while downloading
    detail: str | None = None  # failure explanation
