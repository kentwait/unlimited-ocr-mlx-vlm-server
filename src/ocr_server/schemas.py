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


class DocumentParseResponse(BaseModel):
    kind: str  # "pdf" | "image"
    n_pages: int
    results: list[PageResult]
    total_elapsed_s: float


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
