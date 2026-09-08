"""HTTP API: multipart endpoints for image and PDF parsing.

Requests are queued through anyio.CapacityLimiter(1) so the MLX model gets
serial access to unified memory.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status

from .engine import DEFAULT_MODEL_REF, OcrEngine
from .fake import FakeEngine
from .pages import parse_pages_spec
from .pdfrender import render_pdf_pages
from .schemas import (
    DocumentParseResponse,
    HealthResponse,
    InferenceParams,
    JobStatus,
    PageResult,
)
from .cleanup import CleanupEngine, DEFAULT_CLEANUP_MODEL

log = logging.getLogger("ocr_server")

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB
MAX_PAGES = 50
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_PDF_TYPES = {"application/pdf", "application/octet-stream"}
TEMP_DIR = Path("/tmp/unlimited-ocr-server")

_cleanup_engine: CleanupEngine | None = None


def _get_cleanup_engine() -> CleanupEngine | None:
    """Lazy singleton; None when disabled via env or in fake-engine mode."""
    global _cleanup_engine
    if holder.is_fake:
        return None
    enabled = os.environ.get("OCR_CLEANUP", "1").strip().lower() not in ("0", "false", "no")
    if not enabled:
        return None
    if _cleanup_engine is None:
        model = os.environ.get("OCR_CLEANUP_MODEL", DEFAULT_CLEANUP_MODEL)
        _cleanup_engine = CleanupEngine(model)
        log.info("cleanup model configured: %s (loads on first use)", model)
    return _cleanup_engine


DEFAULT_MODEL_BF16 = "mlx-community/Unlimited-OCR-bf16"


class EngineHolder:
    def __init__(self) -> None:
        self.engine: OcrEngine | FakeEngine | None = None
        self.is_fake = False
        self.model_ref: str | None = None
        # Alternate OCR engine (lazy): e.g. bf16 for loop-free dense pages.
        self.alt_engine: OcrEngine | None = None

    def load(self) -> None:
        # Read env here (not __init__) so tests/CLIs can set it after import.
        model_ref = os.environ.get("OCR_MODEL_REF", DEFAULT_MODEL_REF)
        fake = os.environ.get("OCR_FAKE_ENGINE", "").strip().lower() in ("1", "true", "yes")
        self.model_ref = model_ref
        if fake:
            self.engine = FakeEngine()
            self.is_fake = True
            self.engine.load()
            log.warning("OCR_FAKE_ENGINE set — using stub engine (dev only)")
            return
        eng = OcrEngine(model_ref)
        eng.load()
        self.engine = eng
        self.is_fake = False
        log.info("mlx-vlm model loaded: %s", model_ref)

    def get_ocr_engine(self, ocr_model: str | None) -> OcrEngine | FakeEngine:
        """Return the engine for the requested OCR model, loading on demand.

        `ocr_model` may be an HF repo id/local path, or a shortcut:
        "bf16" -> DEFAULT_MODEL_BF16. The default engine is preloaded at
        startup; alternates load lazily and stay resident.
        """
        if self.is_fake or ocr_model in (None, "", "default"):
            return self.engine
        ref = DEFAULT_MODEL_BF16 if ocr_model == "bf16" else ocr_model
        if ref == self.model_ref:
            return self.engine
        if self.alt_engine is None or self.alt_engine.model_ref != ref:
            eng = OcrEngine(ref)
            eng.load()
            self.alt_engine = eng
            log.info("alternate OCR model loaded: %s", ref)
        return self.alt_engine


holder = EngineHolder()
# Serializes GPU/model access; also acts as a 1-slot queue for concurrent requests.
infer_limiter = anyio.CapacityLimiter(1)

_jobs: dict[str, JobStatus] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    holder.load()
    yield
    holder.engine = None


app = FastAPI(
    title="Unlimited-OCR MLX Server",
    description="LAN OCR: PDF/image -> markdown via baidu/Unlimited-OCR (MLX, Apple Silicon)",
    version="0.2.0",
    lifespan=lifespan,
)


async def _save_upload(upload: UploadFile, suffix: str) -> Path:
    data = await upload.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )
    if suffix == ".pdf":
        ok = upload.content_type in ALLOWED_PDF_TYPES or (upload.filename or "").lower().endswith(".pdf")
    else:
        ok = upload.content_type in ALLOWED_IMAGE_TYPES
    if not ok:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"unsupported content type {upload.content_type!r} for {suffix} upload",
        )
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMP_DIR / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(data)
    return path


def _run_inference_sync(path: Path, params: InferenceParams, engine):
    """Blocking call into the engine (engine already loaded)."""
    t0 = time.perf_counter()
    text, stats = engine.infer_image_file(
        str(path),
        prompt=params.prompt,
        max_tokens=params.max_tokens,
        temperature=params.temperature,
        base_size=params.base_size,
        image_size=params.image_size,
        cropping=params.cropping,
    )
    return text, stats, time.perf_counter() - t0


async def _infer_image_path(
    path: Path, params: InferenceParams, engine=None
) -> tuple[str, object, float]:
    if engine is None:
        engine = holder.engine
    async with infer_limiter:
        return await anyio.to_thread.run_sync(_run_inference_sync, path, params, engine)


def _run_cleanup_sync(cleanup: "CleanupEngine", ocr_text: str, text_layer: str | None):
    return cleanup.cleanup_page(ocr_text, text_layer)


async def _run_cleanup(cleanup: "CleanupEngine", ocr_text: str, text_layer: str | None):
    async with infer_limiter:
        return await anyio.to_thread.run_sync(_run_cleanup_sync, cleanup, ocr_text, text_layer)


def _params_from_form(
    prompt: str,
    max_tokens: int,
    temperature: float,
    base_size: int,
    image_size: int,
    cropping: bool,
) -> InferenceParams:
    try:
        return InferenceParams(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            base_size=base_size,
            image_size=image_size,
            cropping=cropping,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


async def _parse_pdf_path(
    path: Path,
    *,
    pages: str,
    dpi: int,
    params: InferenceParams,
    ocr_model: str | None = None,
) -> DocumentParseResponse:
    """Open, render, and OCR a PDF file. Caller owns cleanup of `path`."""
    import pymupdf

    if not 72 <= dpi <= 300:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "dpi must be 72-300")

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"cannot open PDF: {exc}") from exc

    render_dir = TEMP_DIR / f"pages-{path.stem}"
    try:
        try:
            page_nums = parse_pages_spec(pages, doc.page_count)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        if len(page_nums) > MAX_PAGES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{len(page_nums)} pages requested, max {MAX_PAGES} per request",
            )

        try:
            rendered = render_pdf_pages(doc, page_nums, dpi, render_dir)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"render failed: {exc}") from exc
    finally:
        pass  # doc kept open: text layers are pulled per page during cleanup

    cleanup = _get_cleanup_engine()
    engine = holder.get_ocr_engine(ocr_model)
    results: list[PageResult] = []
    total0 = time.perf_counter()
    try:
        for page_num, img_path in zip(page_nums, rendered):
            text, stats, elapsed = await _infer_image_path(img_path, params, engine)
            page_res = PageResult(
                page=page_num,
                markdown=text,
                elapsed_s=round(elapsed, 3),
                tokens=getattr(stats, "tokens", None),
                tps=round(getattr(stats, "tps", 0.0) or 0.0, 1) or None,
                peak_memory_gb=round(getattr(stats, "peak_memory_gb", 0.0) or 0.0, 2) or None,
                early_stop=bool(getattr(stats, "early_stop", False)),
            )
            if cleanup is not None:
                # Text layer of THIS page (doc still open); None -> ocr-only path.
                text_layer = doc[page_num - 1].get_text()
                cleaned, cstats = await _run_cleanup(cleanup, text, text_layer)
                page_res.markdown = cleaned
                page_res.cleanup_method = cstats.method
                page_res.cleanup_elapsed_s = round(cstats.elapsed_s, 3)
                page_res.cleanup_early_stop = cstats.early_stop
            results.append(page_res)
    finally:
        doc.close()
        shutil.rmtree(render_dir, ignore_errors=True)

    total_elapsed = time.perf_counter() - total0
    return DocumentParseResponse(
        kind="pdf",
        n_pages=len(results),
        results=results,
        total_elapsed_s=round(total_elapsed, 3),
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok" if holder.engine is not None else "loading",
        engine="fake" if holder.is_fake else "real",
        model_loaded=holder.engine is not None and holder.engine.loaded,
        model_ref=holder.model_ref,
        device=f"apple-silicon ({platform.machine()})",
    )


@app.post(
    "/parse/image",
    response_model=DocumentParseResponse,
    responses={415: {"description": "unsupported media type"}},
)
async def parse_image(
    file: UploadFile = File(...),
    prompt: str = Form("document parsing."),
    max_tokens: int = Form(8192),
    temperature: float = Form(0.0),
    base_size: int = Form(1024),
    image_size: int = Form(640),
    cropping: bool = Form(True),
    ocr_model: str = Form("default"),
) -> DocumentParseResponse:
    """Parse one image (JPEG/PNG/WebP) to markdown/text (gundam mode default)."""
    params = _params_from_form(prompt, max_tokens, temperature, base_size, image_size, cropping)
    suffix = Path(file.filename or "x.jpg").suffix.lower() or ".png"
    path = await _save_upload(file, suffix)
    try:
        engine = holder.get_ocr_engine(ocr_model)
        text, stats, elapsed = await _infer_image_path(path, params, engine)
        from .cleanup import strip_det_markers
        text = strip_det_markers(text)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("inference failed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"inference failed: {exc}"
        ) from exc
    finally:
        path.unlink(missing_ok=True)

    return DocumentParseResponse(
        kind="image",
        n_pages=1,
        results=[
            PageResult(
                page=1,
                markdown=text,
                elapsed_s=round(elapsed, 3),
                tokens=getattr(stats, "tokens", None),
                tps=round(getattr(stats, "tps", 0.0) or 0.0, 1) or None,
                peak_memory_gb=round(getattr(stats, "peak_memory_gb", 0.0) or 0.0, 2) or None,
                early_stop=bool(getattr(stats, "early_stop", False)),
            )
        ],
        total_elapsed_s=round(elapsed, 3),
    )


@app.post(
    "/parse/pdf",
    response_model=DocumentParseResponse,
    responses={400: {"description": "bad pages spec or too many pages"}},
)
async def parse_pdf(
    file: UploadFile = File(...),
    pages: str = Form("all"),
    dpi: int = Form(150),
    prompt: str = Form("document parsing."),
    max_tokens: int = Form(8192),
    temperature: float = Form(0.0),
    base_size: int = Form(1024),
    image_size: int = Form(640),
    cropping: bool = Form(True),
    ocr_model: str = Form("default"),
) -> DocumentParseResponse:
    """Parse a PDF to markdown. `pages` = "all" | "1-3,5". One OCR call per page.

    PDF pages default to base mode (cropping=false) per upstream guidance for
    multi-page workflows; pass cropping=true for dense single pages.
    """
    params = _params_from_form(prompt, max_tokens, temperature, base_size, image_size, cropping)
    path = await _save_upload(file, ".pdf")
    try:
        return await _parse_pdf_path(path, pages=pages, dpi=dpi, params=params, ocr_model=ocr_model)
    finally:
        path.unlink(missing_ok=True)


@app.post("/parse/jobs", response_model=JobStatus, status_code=status.HTTP_202_ACCEPTED)
async def parse_pdf_async(
    file: UploadFile = File(...),
    pages: str = Form("all"),
    dpi: int = Form(150),
    prompt: str = Form("document parsing."),
    max_tokens: int = Form(8192),
    temperature: float = Form(0.0),
    base_size: int = Form(1024),
    image_size: int = Form(640),
    cropping: bool = Form(True),
    ocr_model: str = Form("default"),
) -> JobStatus:
    """Submit a PDF parse as a background job (returns immediately with job_id)."""
    params = _params_from_form(prompt, max_tokens, temperature, base_size, image_size, cropping)
    path = await _save_upload(file, ".pdf")
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
            resp = await _parse_pdf_path(path, pages=pages, dpi=dpi, params=params, ocr_model=ocr_model)
            job.status = "done"
            job.result = resp
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
        "service": "unlimited-ocr-server",
        "endpoints": ["/health", "/parse/image", "/parse/pdf", "/parse/jobs"],
    }
