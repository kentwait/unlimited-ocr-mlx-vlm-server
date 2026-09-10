"""Request/response schemas and validation bounds shared by the API."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

ALLOWED_PROMPT_RE = re.compile(
    r"^[\w\s.,:;!?()\[\]{}'\"<>|/\\@#%&+=~`^-]+$", re.UNICODE
)


class InferenceParams(BaseModel):
    """OCR parameters accepted by every endpoint (passed to mlx_vlm.generate)."""

    model_config = {"protected_namespaces": ()}

    prompt: str = "document parsing."
    max_tokens: int = Field(default=4096, ge=16, le=32768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    base_size: int = Field(default=1024, ge=256, le=2048)
    image_size: int = Field(default=640, ge=256, le=2048)
    cropping: bool = True

    @field_validator("prompt")
    @classmethod
    def _sane_prompt(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("prompt must not be empty")
        if len(v) > 200:
            raise ValueError("prompt too long (max 200 chars)")
        if not ALLOWED_PROMPT_RE.match(v):
            raise ValueError("prompt contains unsupported characters")
        return v


class PageResult(BaseModel):
    page: int
    markdown: str
    elapsed_s: float
    tokens: int | None = None
    tps: float | None = None
    peak_memory_gb: float | None = None
    early_stop: bool = False  # generation loop detected and truncated
    # Support stage (renamed from cleanup/*; the old fields are dual-written
    # for one release so older clients keep working, then removed).
    support_method: str | None = None  # "support-spans-digital" | "support-spans-proofread"
    support_elapsed_s: float | None = None
    support_early_stop: bool | None = None
    cleanup_method: str | None = None  # deprecated alias of support_method
    cleanup_elapsed_s: float | None = None  # deprecated alias
    cleanup_early_stop: bool | None = None  # deprecated alias
    corrections: dict | None = None  # support-model edit counts + samples (see audit_corrections)
    layout: dict | None = None  # coarse pre-scan profile (see LayoutProfile.to_dict); None when skipped/failed
    spans_jsonl: str | None = None  # structured OCR spans: {"page", "label", "box", "text"} per line


class DocumentParseResponse(BaseModel):
    kind: str  # "pdf" | "image"
    n_pages: int
    results: list[PageResult]
    total_elapsed_s: float
    furniture: dict | None = None  # {template, removed_total, removed_by_page, samples}
    journal: str = "generic"  # deprecated: always "generic"; per-document layout now comes from the pre-scan


class HealthResponse(BaseModel):
    status: str
    engine: str  # "real" | "fake"
    model_loaded: bool
    model_ref: str | None = None
    device: str


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
    # Client-facing progress (UI polls this): current pipeline phase and
    # per-page counts. pages_total is None until the pages spec is parsed.
    # The layout pre-scan runs inside the "ocr" phase (it is fast and page
    # local); the support correction pass reports phase "support".
    phase: str | None = None  # "ocr" | "support"
    pages_done: int = 0
    pages_total: int | None = None


REFLOW_CONTRACT_VERSION = 1


class ReflowRequest(BaseModel):
    """Internal reflow call: client-rendered markdown + caller-owned prompt.

    Served by POST /internal/reflow (undocumented, token + loopback guarded).
    `journal` is opaque to the server — echoed back, never interpreted.
    """

    contract_version: int = REFLOW_CONTRACT_VERSION
    journal: str = Field(default="generic", max_length=64)
    markdown: str = Field(min_length=1, max_length=100_000)
    prompt_override: str | None = Field(default=None, max_length=20_000)
    text_layer: str | None = Field(default=None, max_length=100_000)
    max_tokens: int = Field(default=6144, ge=16, le=16384)

    @field_validator("markdown")
    @classmethod
    def _nonblank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("markdown must not be blank")
        return v


class ReflowResponse(BaseModel):
    contract_version: int = REFLOW_CONTRACT_VERSION
    journal: str
    markdown: str
    method: str
    elapsed_s: float
    model: str | None = None
    corrections: dict | None = None  # same audit shape as PageResult.corrections
