"""Digital-only PDF parse pipeline.

Stage order per document:

1. text-layer check (digital-born PDFs only; scans error out),
2. pymupdf4llm Layout over PDF internals: text, headings, lists, captions,
   footnotes, running headers/footers, picture boxes, reading order,
3. one render per page, PP-DocLayout-S figure regions, cropped inline,
4. merge: picture boxes replaced by figure spans, content inside figures
   relabeled `figure_text` (lossless in JSONL, dropped by the renderer),
   ids assigned in final reading order.

There is no OCR and no LLM stage: text is exact from the text layer, and
anything the layout engines cannot see is out of scope.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

import pymupdf
from fastapi import HTTPException, status

from .figures import crop_data_uri
from .native_layout import (
    FIGURE_CONTAINABLE,
    NativeBox,
    extract_boxes,
    missing_text_pages,
)
from .pages import parse_pages_spec
from .pdfrender import render_pdf_pages
from .pp_layout import FigureRegion, LayoutModel
from .schemas import DocumentParseResponse, JobStatus, PageResult
from .spans import Span, assign_ids, spans_to_jsonl

log = logging.getLogger("ocr_server")

#: Render resolution for figure detection and crops.
DEFAULT_FIGURE_DPI = 150
#: Per-request page cap (uploads can be larger; subsets are explicit).
MAX_PAGES = 50

#: A PP-DocLayout-S region becomes a figure only when it corroborates a
#: native picture box (IoU). The detector can misclassify dense text regions
#: as figures — observed whole-page "image" boxes on reference pages — while
#: genuine figures overlap pymupdf4llm's picture boxes (IoU 0.49-0.98 on the
#: fixture vs 0.02 for the false positives).
FIGURE_MIN_IOU = 0.4


def select_figures(
    regions: list[FigureRegion], native: list[NativeBox]
) -> list[FigureRegion]:
    """Keep detected regions that overlap a native picture box."""
    picture_boxes = [box.box for box in native if box.label == "picture"]
    return [
        region
        for region in regions
        if any(_iou(region.box, picture) > FIGURE_MIN_IOU for picture in picture_boxes)
    ]


def _iou(a: list[int], b: list[int]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def _center_inside(inner: list[int], outer: list[int]) -> bool:
    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _picture_matches(picture_box: list[int], region_box: list[int]) -> bool:
    """True when a native picture box corresponds to a detected figure."""
    return (
        _iou(picture_box, region_box) > 0.3
        or _center_inside(picture_box, region_box)
        or _center_inside(region_box, picture_box)
    )


def _figure_span(page: int, region: FigureRegion, image: str | None) -> Span:
    return Span(page=page, label="image", box=list(region.box), text="", image=image)


def merge_page(
    native: list[NativeBox],
    figures: list[tuple[FigureRegion, str | None]],
    page: int,
) -> tuple[list[Span], list[str]]:
    """Merge native boxes and figure regions into ordered spans.

    - Native picture boxes are suppressed; the figure span that matches one
      is emitted at that position (reading order preserved).
    - Content boxes (`text`, `list-item`) whose center falls inside a figure
      region are relabeled `figure_text` (kept in JSONL, dropped by render).
    - Figures with no native picture box are appended in reading order.
    """
    warnings: list[str] = []
    matched: dict[int, list[int]] = {}
    for figure_index, (region, _image) in enumerate(figures):
        for box_index, box in enumerate(native):
            if box.label == "picture" and _picture_matches(box.box, region.box):
                matched.setdefault(box_index, []).append(figure_index)

    emitted: set[int] = set()
    spans: list[Span] = []
    for box_index, box in enumerate(native):
        if box.label == "picture":
            for figure_index in matched.get(box_index, []):
                if figure_index in emitted:
                    # One region can match several rule/strip picture boxes;
                    # emit it once, at the first match in reading order.
                    continue
                region, image = figures[figure_index]
                spans.append(_figure_span(page, region, image))
                emitted.add(figure_index)
                if image is None:
                    warnings.append(f"figure crop failed on page {page}")
            continue
        label = box.label
        if label in FIGURE_CONTAINABLE and any(
            _center_inside(box.box, region.box) for region, _ in figures
        ):
            label = "figure_text"
        spans.append(Span(page=page, label=label, box=box.box, text=box.text))

    trailing = [
        (region, image)
        for figure_index, (region, image) in enumerate(figures)
        if figure_index not in emitted
    ]
    trailing.sort(key=lambda pair: (pair[0].box[1], pair[0].box[0]))
    for region, image in trailing:
        spans.append(_figure_span(page, region, image))
        if image is None:
            warnings.append(f"figure crop failed on page {page}")
    return spans, warnings


def parse_pdf(
    path: Path,
    *,
    pages: str = "all",
    dpi: int = DEFAULT_FIGURE_DPI,
    layout_model: LayoutModel,
    job: JobStatus | None = None,
) -> DocumentParseResponse:
    """Parse a digital-born PDF into per-page span JSONL.

    Caller owns deletion of `path`. When `job` is given, per-page progress is
    written to it for client polling.
    """
    if not 72 <= dpi <= 300:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "dpi must be 72-300")

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"cannot open PDF: {exc}"
        ) from exc

    render_dir = Path(f"{path}-render")
    total0 = time.perf_counter()
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
        if job is not None:
            job.pages_total = len(page_nums)

        missing = missing_text_pages(doc, page_nums)
        if missing:
            listed = ", ".join(str(n) for n in missing[:10])
            suffix = ", ..." if len(missing) > 10 else ""
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"no text layer on page(s) {listed}{suffix} — scanned PDFs "
                "are not supported yet (digital-born PDFs only)",
            )

        try:
            native = extract_boxes(doc, page_nums)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"cannot extract text layout: {exc}"
            ) from exc
        try:
            rendered = render_pdf_pages(doc, page_nums, dpi, render_dir)
        except Exception as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"render failed: {exc}"
            ) from exc

        results: list[PageResult] = []
        for index, (page_num, image_path) in enumerate(zip(page_nums, rendered)):
            page0 = time.perf_counter()
            page_native = native.get(page_num, [])
            regions = select_figures(layout_model.detect(image_path, page_num), page_native)
            figures = [(region, crop_data_uri(image_path, region.box)) for region in regions]
            spans, warnings = merge_page(page_native, figures, page_num)
            assign_ids(spans)
            results.append(
                PageResult(
                    page=page_num,
                    elapsed_s=round(time.perf_counter() - page0, 3),
                    spans_jsonl=spans_to_jsonl(spans),
                    warnings=warnings,
                )
            )
            if job is not None:
                job.phase = "parse"
                job.pages_done = index + 1
            log.info(
                "page %d/%d parsed: %d spans, %d figures, %.2fs",
                index + 1,
                len(page_nums),
                len(spans),
                len(figures),
                time.perf_counter() - page0,
            )
        total_elapsed = time.perf_counter() - total0
        log.info(
            "request summary: %d pages in %.2fs (%.2f s/page avg)",
            len(results),
            total_elapsed,
            total_elapsed / max(1, len(results)),
        )
        return DocumentParseResponse(
            kind="pdf",
            n_pages=len(results),
            results=results,
            total_elapsed_s=round(total_elapsed, 3),
        )
    finally:
        doc.close()
        shutil.rmtree(render_dir, ignore_errors=True)
