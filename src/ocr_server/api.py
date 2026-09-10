"""HTTP API: multipart endpoints for digital-born PDF parsing.

Parsing is CPU-bound (pymupdf4llm + ONNX), so requests funnel through a
single-slot limiter and run in a worker thread; concurrent requests queue.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

import anyio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status

from .assistant_api import router as assistant_router
from .pipeline import DEFAULT_FIGURE_DPI, parse_pdf as run_parse_pdf
from .pp_layout import LayoutModel
from .schemas import DocumentParseResponse, HealthResponse, JobStatus

log = logging.getLogger("ocr_server")

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB
ALLOWED_PDF_TYPES = {"application/pdf", "application/octet-stream"}
TEMP_DIR = Path("/tmp/unlimited-ocr-server")

_layout_model: LayoutModel | None = None


def _get_layout_model() -> LayoutModel:
    """Lazy singleton for the bundled PP-DocLayout-S ONNX model."""
    global _layout_model
    if _layout_model is None:
        model = LayoutModel(os.environ.get("OCR_LAYOUT_MODEL") or None)
        model.load()
        log.info("layout model loaded: %s", model.name)
        _layout_model = model
    return _layout_model


#: Parsing is CPU-bound; one document at a time (concurrent requests queue).
parse_limiter = anyio.CapacityLimiter(1)

_jobs: dict[str, JobStatus] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast when the model asset is missing/corrupt.
    _get_layout_model()
    yield


app = FastAPI(
    title="Paperhub PDF Parser",
    description="Digital-born PDF -> structured spans (pymupdf4llm + PP-DocLayout-S)",
    version="0.4.0",
    lifespan=lifespan,
)

# Allow the desktop UI (Tauri) to call this server cross-origin. Extra origins
# can be added via OCR_CORS_ORIGINS (comma-separated), e.g. for `vite dev`.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_CORS_DEFAULT = [
    "tauri://localhost",  # Tauri v2 production (macOS/Linux)
    "http://tauri.localhost",  # Tauri v2 production (Windows)
    "http://localhost:1420",  # Tauri dev server default (other apps)
    "http://localhost:1431",  # Paperhub's Tauri dev server (vite default port)
    "http://localhost:5173",  # vite dev
]
_CORS_ORIGINS = _CORS_DEFAULT + [
    o.strip()
    for o in os.environ.get("OCR_CORS_ORIGINS", "").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    # Dev ports are assigned dynamically (each Tauri app probes a port block
    # upward from its base — Paperhub from 1430, see scripts/tauri-dev.ts in
    # the Paperhub repo), so match the whole loopback range instead of
    # enumerating ports. Production Tauri origins are exact above.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):14\d\d",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local assistant: model lifecycle + OpenAI-compatible chat surface. The
# runtime itself is optional (the parse server works without MLX installed).
app.include_router(assistant_router)


async def _save_upload(upload: UploadFile) -> Path:
    data = await upload.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )
    ok = upload.content_type in ALLOWED_PDF_TYPES or (
        upload.filename or ""
    ).lower().endswith(".pdf")
    if not ok:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"unsupported content type {upload.content_type!r} for a PDF upload",
        )
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMP_DIR / f"{uuid.uuid4().hex}.pdf"
    path.write_bytes(data)
    return path


async def _run_parse(
    path: Path, *, pages: str, dpi: int, job: JobStatus | None = None
) -> DocumentParseResponse:
    async with parse_limiter:
        return await anyio.to_thread.run_sync(
            partial(
                run_parse_pdf,
                path,
                pages=pages,
                dpi=dpi,
                layout_model=_get_layout_model(),
                job=job,
            )
        )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        parser="pymupdf4llm",
        layout_model=_get_layout_model().name,
    )


@app.post(
    "/parse/pdf",
    response_model=DocumentParseResponse,
    responses={400: {"description": "bad pages spec, no text layer, or too many pages"}},
)
async def parse_pdf(
    file: UploadFile = File(...),
    pages: str = Form("all"),
    dpi: int = Form(DEFAULT_FIGURE_DPI),
) -> DocumentParseResponse:
    """Parse a digital-born PDF. `pages` = "all" | "1-3,5"; `dpi` = figure render DPI."""
    path = await _save_upload(file)
    try:
        return await _run_parse(path, pages=pages, dpi=dpi)
    finally:
        path.unlink(missing_ok=True)


@app.post("/parse/jobs", response_model=JobStatus, status_code=status.HTTP_202_ACCEPTED)
async def parse_pdf_async(
    file: UploadFile = File(...),
    pages: str = Form("all"),
    dpi: int = Form(DEFAULT_FIGURE_DPI),
) -> JobStatus:
    """Submit a PDF parse as a background job (returns immediately with job_id)."""
    path = await _save_upload(file)
    job_id = uuid.uuid4().hex[:12]
    job = JobStatus(
        job_id=job_id,
        status="pending",
        kind="pdf",
        filename=file.filename,
        created_at=time.time(),
    )
    _jobs[job_id] = job

    async def _run() -> None:
        job.started_at = time.time()
        job.status = "running"
        try:
            job.result = await _run_parse(path, pages=pages, dpi=dpi, job=job)
            job.status = "done"
        except HTTPException as exc:
            job.status = "error"
            job.error = str(exc.detail)
        except Exception as exc:
            log.exception("job %s failed", job_id)
            job.status = "error"
            job.error = str(exc)
        finally:
            job.finished_at = time.time()
            path.unlink(missing_ok=True)

    asyncio.create_task(_run())
    return job


@app.get("/parse/jobs/{job_id}", response_model=JobStatus)
async def job_status(job_id: str) -> JobStatus:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown job {job_id}")
    return job


@app.get("/")
async def root() -> dict:
    return {
        "service": "paperhub-parser",
        "endpoints": [
            "/health",
            "/parse/pdf",
            "/parse/jobs",
            "/assistant/status",
            "/assistant/model/download",
            "/v1/chat/completions",
        ],
    }
