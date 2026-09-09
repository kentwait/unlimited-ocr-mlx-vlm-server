"""HTTP API: multipart endpoints for image and PDF parsing.

Requests are queued through anyio.CapacityLimiter(1) so the MLX model gets
serial access to unified memory.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import platform
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status

from .engine import DEFAULT_MODEL_REF, OcrEngine
from .fake import FakeEngine
from .furniture import apply_furniture
from .pages import parse_pages_spec
from .pdfrender import render_pdf_pages
from .prompts import PROMPTS_DIR as PROMPTS_DIR_DEFAULT, PromptRegistry
from .spans import JOURNALS, parse_spans, render_markdown, spans_to_jsonl
from .schemas import (
    REFLOW_CONTRACT_VERSION,
    DocumentParseResponse,
    HealthResponse,
    InferenceParams,
    JobStatus,
    PageResult,
    ReflowRequest,
    ReflowResponse,
)
from .cleanup import CleanupEngine, DEFAULT_CLEANUP_MODEL

log = logging.getLogger("ocr_server")

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB
MAX_PAGES = 50
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_PDF_TYPES = {"application/pdf", "application/octet-stream"}
TEMP_DIR = Path("/tmp/unlimited-ocr-server")

_cleanup_engine: CleanupEngine | None = None
_prompt_registry: PromptRegistry | None = None


def _get_prompt_registry() -> PromptRegistry:
    """Startup-loaded prompt registry singleton (fail-fast at first use)."""
    global _prompt_registry
    if _prompt_registry is None:
        reg = PromptRegistry(os.environ.get("OCR_PROMPTS_DIR", PROMPTS_DIR_DEFAULT))
        reg.load()
        _prompt_registry = reg
    return _prompt_registry


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
        _cleanup_engine = CleanupEngine(model, prompts=_get_prompt_registry())
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
    # Load prompts first: a broken template fails startup before models load.
    _get_prompt_registry()
    holder.load()
    yield
    holder.engine = None


app = FastAPI(
    title="Unlimited-OCR MLX Server",
    description="LAN OCR: PDF/image -> markdown via baidu/Unlimited-OCR (MLX, Apple Silicon)",
    version="0.3.0",
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


def _run_span_check_sync(
    cleanup: "CleanupEngine",
    spans: list,
    text_layer: str | None,
    journal: str = "generic",
):
    return cleanup.check_spans(spans, text_layer, journal=journal)


async def _run_span_check(
    cleanup: "CleanupEngine",
    spans: list,
    text_layer: str | None,
    journal: str = "generic",
):
    async with infer_limiter:
        return await anyio.to_thread.run_sync(
            _run_span_check_sync, cleanup, spans, text_layer, journal
        )


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


def _furniture_from_form(furniture: str) -> str:
    """Eager `furniture` field validation: fail fast with 400, including
    before a background job is created (job errors are poll-only)."""
    if furniture not in ("auto", "none"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown furniture mode {furniture!r}: expected 'auto' or 'none' "
            "(journal templates moved to Paperhub's reflow layer)",
        )
    return furniture


def _journal_from_form(journal: str) -> str:
    """Eager `journal` field validation: fail fast with 400, including
    before a background job is created (job errors are poll-only)."""
    if journal not in JOURNALS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown journal {journal!r}: expected one of {', '.join(JOURNALS)}",
        )
    return journal


async def _parse_pdf_path(
    path: Path,
    *,
    pages: str,
    dpi: int,
    params: InferenceParams,
    ocr_model: str | None = None,
    furniture: str = "auto",
    journal: str = "generic",
    job: JobStatus | None = None,
) -> DocumentParseResponse:
    """Open, render, and OCR a PDF file. Caller owns cleanup of `path`.

    When `job` is given, per-stage progress (phase/pages_done/pages_total) is
    written to it for client polling.
    """
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
        if job is not None:
            job.pages_total = len(page_nums)
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

    # Furniture pass needs the whole document's OCR first (cross-page
    # fingerprints), so run OCR for all pages, then process.
    page_ocr: list[tuple[int, Path, str, object, float]] = []
    total0 = time.perf_counter()
    try:
        for page_num, img_path in zip(page_nums, rendered):
            text, stats, elapsed = await _infer_image_path(img_path, params, engine)
            page_ocr.append((page_num, img_path, text, stats, elapsed))
            if job is not None:
                job.phase = "ocr"
                job.pages_done = len(page_ocr)

        # Furniture removal on the span intermediate (generic repetition
        # fingerprinting; "none" disables). Journal-specific templates live
        # in Paperhub's reflow layer — this server stays journal-agnostic.
        all_spans = [parse_spans(t, page=n) for n, _, t, _, _ in page_ocr]
        try:
            finfo = apply_furniture(all_spans, template=furniture)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        doc_furniture = {
            "template": finfo["template"],
            "removed_total": finfo["removed_total"],
            "removed_by_page": {
                n: c for (n, _, _, _, _), c in zip(page_ocr, finfo["removed_by_page"])
            },
            "samples": finfo["samples"],
        }
        page_markdowns = [render_markdown(spans, journal) for spans in all_spans]

        results: list[PageResult] = []
        if job is not None and cleanup is not None:
            # Fresh count for the checking stage: clients weight OCR and
            # checking evenly, so pages_done restarts here (same total).
            job.pages_done = 0
        for i, ((page_num, img_path, text, stats, elapsed), spans, md) in enumerate(
            zip(page_ocr, all_spans, page_markdowns)
        ):
            page_res = PageResult(
                page=page_num,
                markdown=md,
                elapsed_s=round(elapsed, 3),
                tokens=getattr(stats, "tokens", None),
                tps=round(getattr(stats, "tps", 0.0) or 0.0, 1) or None,
                peak_memory_gb=round(getattr(stats, "peak_memory_gb", 0.0) or 0.0, 2) or None,
                early_stop=bool(getattr(stats, "early_stop", False)),
                spans_jsonl=spans_to_jsonl(spans),
            )
            if cleanup is not None:
                # Text layer of THIS page (doc still open); None -> proofread path.
                text_layer = doc[page_num - 1].get_text()
                if job is not None:
                    job.phase = "cleanup"
                checked, cstats = await _run_span_check(
                    cleanup, spans, text_layer, journal=journal
                )
                if job is not None:
                    job.pages_done = i + 1
                # Checked spans are authoritative: markdown is derived from
                # them so the two can never disagree.
                page_res.markdown = render_markdown(checked, journal)
                page_res.spans_jsonl = spans_to_jsonl(checked)
                page_res.cleanup_method = cstats.method
                page_res.cleanup_elapsed_s = round(cstats.elapsed_s, 3)
                page_res.cleanup_early_stop = cstats.early_stop
                audit = cstats.audit
                if audit is not None:
                    audit.log_summary(f"page {page_num}")
                    page_res.corrections = {
                        "text_layer_backed": len(audit.text_layer_backed),
                        "ocr_vocab_backed": len(audit.ocr_vocab_backed),
                        "invented": len(audit.invented),
                        "formatting_only": audit.formatting_only,
                        "format_added_words": audit.format_added_words,
                        "format_removed_words": audit.format_removed_words,
                        "samples_invented": audit.invented[:8],
                        "samples_text_layer_backed": audit.text_layer_backed[:8],
                    }
            log.info(
                "page %d/%d done: ocr %.1fs (%d tok%s), furniture %d, cleanup %s %.1fs, %d chars",
                page_num,
                len(page_nums),
                elapsed,
                getattr(stats, "tokens", 0) or 0,
                ", early-stop" if getattr(stats, "early_stop", False) else "",
                doc_furniture["removed_by_page"].get(page_num, 0),
                page_res.cleanup_method or "off",
                page_res.cleanup_elapsed_s or 0.0,
                len(page_res.markdown),
            )
            results.append(page_res)
    finally:
        doc.close()
        shutil.rmtree(render_dir, ignore_errors=True)

    total_elapsed = time.perf_counter() - total0
    resp = DocumentParseResponse(
        kind="pdf",
        n_pages=len(results),
        results=results,
        total_elapsed_s=round(total_elapsed, 3),
        furniture=doc_furniture,
        journal=journal,
    )
    # Response summary: aggregate correction stats across pages.
    tot_edits = sum(
        (r.corrections or {}).get("text_layer_backed", 0)
        + (r.corrections or {}).get("ocr_vocab_backed", 0)
        + (r.corrections or {}).get("invented", 0)
        for r in results
    )
    tot_inv = sum((r.corrections or {}).get("invented", 0) for r in results)
    log.info(
        "request summary: %d pages in %.1fs (%.1f s/page avg) | checker edits: %d "
        "total, %d invented | furniture removed=%d | ocr_model=%s dpi=%d",
        len(results),
        total_elapsed,
        total_elapsed / max(1, len(results)),
        tot_edits,
        tot_inv,
        doc_furniture["removed_total"],
        ocr_model or "default",
        dpi,
    )
    return resp


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
    journal: str = Form("generic"),
) -> DocumentParseResponse:
    """Parse one image (JPEG/PNG/WebP) to markdown/text (gundam mode default)."""
    params = _params_from_form(prompt, max_tokens, temperature, base_size, image_size, cropping)
    journal = _journal_from_form(journal)
    suffix = Path(file.filename or "x.jpg").suffix.lower() or ".png"
    path = await _save_upload(file, suffix)
    try:
        engine = holder.get_ocr_engine(ocr_model)
        text, stats, elapsed = await _infer_image_path(path, params, engine)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("inference failed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"inference failed: {exc}"
        ) from exc
    finally:
        path.unlink(missing_ok=True)

    cleanup = _get_cleanup_engine()
    cleanup_method = None
    cleanup_elapsed = None
    corrections = None
    # Spans are the authoritative output; markdown is derived from them.
    spans = parse_spans(text, page=1)
    if cleanup is not None:
        checked, cstats = await _run_span_check(cleanup, spans, None, journal=journal)
        spans = checked
        cleanup_method = cstats.method
        cleanup_elapsed = round(cstats.elapsed_s, 3)
        if cstats.audit is not None:
            cstats.audit.log_summary("image")
            corrections = {
                "text_layer_backed": len(cstats.audit.text_layer_backed),
                "ocr_vocab_backed": len(cstats.audit.ocr_vocab_backed),
                "invented": len(cstats.audit.invented),
                "formatting_only": cstats.audit.formatting_only,
                "format_added_words": cstats.audit.format_added_words,
                "format_removed_words": cstats.audit.format_removed_words,
                "samples_invented": cstats.audit.invented[:8],
                "samples_text_layer_backed": cstats.audit.text_layer_backed[:8],
            }
    spans_jsonl = spans_to_jsonl(spans)
    text = render_markdown(spans, journal)
    log.info(
        "image done: ocr %.1fs (%d tok%s), cleanup %s %.1fs, %d chars",
        elapsed,
        getattr(stats, "tokens", 0) or 0,
        ", early-stop" if getattr(stats, "early_stop", False) else "",
        cleanup_method or "off",
        cleanup_elapsed or 0.0,
        len(text),
    )

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
                cleanup_method=cleanup_method,
                cleanup_elapsed_s=cleanup_elapsed,
                corrections=corrections,
                spans_jsonl=spans_jsonl,
            )
        ],
        total_elapsed_s=round(elapsed, 3),
        journal=journal,
    )


@app.post(
    "/parse/pdf",
    response_model=DocumentParseResponse,
    responses={400: {"description": "bad pages spec or too many pages"}},
)
async def parse_pdf(
    file: UploadFile = File(...),
    pages: str = Form("all"),
    dpi: int = Form(300),
    prompt: str = Form("document parsing."),
    max_tokens: int = Form(8192),
    temperature: float = Form(0.0),
    base_size: int = Form(1024),
    image_size: int = Form(640),
    cropping: bool = Form(True),
    ocr_model: str = Form("default"),
    furniture: str = Form("auto"),
    journal: str = Form("generic"),
) -> DocumentParseResponse:
    """Parse a PDF to markdown. `pages` = "all" | "1-3,5". One OCR call per page.

    PDF pages default to base mode (cropping=false) per upstream guidance for
    multi-page workflows; pass cropping=true for dense single pages.
    """
    params = _params_from_form(prompt, max_tokens, temperature, base_size, image_size, cropping)
    furniture = _furniture_from_form(furniture)
    journal = _journal_from_form(journal)
    path = await _save_upload(file, ".pdf")
    try:
        return await _parse_pdf_path(
            path, pages=pages, dpi=dpi, params=params, ocr_model=ocr_model,
            furniture=furniture, journal=journal,
        )
    finally:
        path.unlink(missing_ok=True)


@app.post("/parse/jobs", response_model=JobStatus, status_code=status.HTTP_202_ACCEPTED)
async def parse_pdf_async(
    file: UploadFile = File(...),
    pages: str = Form("all"),
    dpi: int = Form(300),
    prompt: str = Form("document parsing."),
    max_tokens: int = Form(8192),
    temperature: float = Form(0.0),
    base_size: int = Form(1024),
    image_size: int = Form(640),
    cropping: bool = Form(True),
    ocr_model: str = Form("default"),
    furniture: str = Form("auto"),
    journal: str = Form("generic"),
) -> JobStatus:
    """Submit a PDF parse as a background job (returns immediately with job_id)."""
    params = _params_from_form(prompt, max_tokens, temperature, base_size, image_size, cropping)
    furniture = _furniture_from_form(furniture)
    journal = _journal_from_form(journal)
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
            resp = await _parse_pdf_path(
                path, pages=pages, dpi=dpi, params=params, ocr_model=ocr_model,
                furniture=furniture, journal=journal, job=job,
            )
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


# ---------------------------------------------------------------------------
# Internal reflow endpoint (Paperhub's journal pass over the checker LLM).
#
# Deliberately NOT public: excluded from the OpenAPI schema and the README.
# Guarded by BOTH a per-launch bearer token (OCR_INTERNAL_TOKEN, generated
# by the Tauri sidecar launcher) and a loopback-only check, so it cannot be
# reached from the LAN even when the server binds 0.0.0.0 for /parse/*.
# Reflow jobs share infer_limiter with OCR/cleanup: one MLX user at a time.
# ---------------------------------------------------------------------------

# "testclient" is Starlette's in-process TestClient harness identity.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _require_internal_access(request: Request) -> None:
    token = os.environ.get("OCR_INTERNAL_TOKEN", "").strip()
    if not token:
        # Fail closed: with no token configured the endpoint doesn't exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    host = request.client.host if request.client is not None else ""
    if host not in _LOOPBACK_HOSTS:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "internal endpoint is loopback-only"
        )
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(presented, token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal token")


def _audit_to_corrections(audit) -> dict | None:
    if audit is None:
        return None
    return {
        "text_layer_backed": len(audit.text_layer_backed),
        "ocr_vocab_backed": len(audit.ocr_vocab_backed),
        "invented": len(audit.invented),
        "formatting_only": audit.formatting_only,
        "format_added_words": audit.format_added_words,
        "format_removed_words": audit.format_removed_words,
        "samples_invented": audit.invented[:8],
        "samples_text_layer_backed": audit.text_layer_backed[:8],
    }


@app.post("/internal/reflow", response_model=ReflowResponse, include_in_schema=False)
async def internal_reflow(body: ReflowRequest, request: Request) -> ReflowResponse:
    """LLM reflow over client-rendered markdown with a caller-owned prompt."""
    _require_internal_access(request)
    if body.contract_version != REFLOW_CONTRACT_VERSION:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unsupported reflow contract_version {body.contract_version} "
            f"(server speaks {REFLOW_CONTRACT_VERSION}) — bump the pinned "
            "server or the Paperhub client",
        )
    if holder.is_fake or _get_cleanup_engine() is None:
        # Dev contract path: deterministic echo so Paperhub can exercise the
        # full reflow round-trip (auth, version, journal echo) without weights.
        return ReflowResponse(
            journal=body.journal,
            markdown=body.markdown.strip(),
            method="fake-echo",
            elapsed_s=0.0,
            model="fake",
            corrections=None,
        )
    from functools import partial

    cleanup = _get_cleanup_engine()
    assert cleanup is not None  # narrowed above; keeps type-checkers honest
    t0 = time.perf_counter()
    async with infer_limiter:
        text, stats = await anyio.to_thread.run_sync(
            partial(
                cleanup.reflow_text,
                body.markdown,
                journal=body.journal,
                prompt_override=body.prompt_override,
                text_layer=body.text_layer,
                max_tokens=body.max_tokens,
            )
        )
    log.info(
        "internal reflow: journal=%s method=%s %.1fs, %d chars -> %d chars",
        body.journal,
        stats.method,
        time.perf_counter() - t0,
        len(body.markdown),
        len(text),
    )
    return ReflowResponse(
        journal=body.journal,
        markdown=text,
        method=stats.method,
        elapsed_s=round(time.perf_counter() - t0, 3),
        model=cleanup.model_ref,
        corrections=_audit_to_corrections(stats.audit),
    )


@app.get("/")
async def root() -> dict:
    return {
        "service": "unlimited-ocr-server",
        "endpoints": ["/health", "/parse/image", "/parse/pdf", "/parse/jobs"],
    }
