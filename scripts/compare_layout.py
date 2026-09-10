"""Benchmark pymupdf4llm vs PP-DocLayout-S on a PDF.

Both layout engines disagree in complementary ways; this harness reports
what each one sees per page (furniture labels, picture/figure regions,
timing) so a new fixture or a model bump can be evaluated quickly. It is a
dev tool, not a test.

Usage (from the repo root):
  uv run python scripts/compare_layout.py [pdf]

The PDF defaults to the committed fixture; override with OCR_CMP_PDF, and
restrict pages with OCR_CMP_PAGES ("1,2" or "1-3").
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pymupdf

from ocr_server.native_layout import extract_boxes
from ocr_server.pdfrender import render_pdf_pages
from ocr_server.pp_layout import LayoutModel
from ocr_server.pipeline import select_figures

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "assets" / "altemose2022.pdf"
PDF_PATH = Path(os.environ.get("OCR_CMP_PDF", str(FIXTURE)))
DPI = int(os.environ.get("OCR_CMP_DPI", "150"))


def parse_pages(spec: str, total: int) -> list[int]:
    if spec in ("", "all"):
        return list(range(1, total + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
            pages.update(range(a, b + 1))
        else:
            pages.add(int(part))
    return sorted(p for p in pages if 1 <= p <= total)


def main() -> None:
    if not PDF_PATH.is_file():
        sys.exit(f"error: PDF not found: {PDF_PATH}")
    doc = pymupdf.open(PDF_PATH)
    page_nums = parse_pages(os.environ.get("OCR_CMP_PAGES", "all"), doc.page_count)
    print(f"{PDF_PATH.name}: {len(page_nums)} page(s), {DPI} dpi")

    t0 = time.perf_counter()
    native = extract_boxes(doc, page_nums)
    native_s = time.perf_counter() - t0

    model = LayoutModel().load()
    render_dir = Path(tempfile.mkdtemp())
    rendered = render_pdf_pages(doc, page_nums, DPI, render_dir)

    pp_s = 0.0
    for page, image in zip(page_nums, rendered):
        t0 = time.perf_counter()
        regions = model.detect(image, page)
        pp_s += time.perf_counter() - t0
        boxes = native.get(page, [])
        furniture = [b for b in boxes if b.label in ("header", "footer", "page_number")]
        pictures = [b for b in boxes if b.label == "picture"]
        figures = select_figures(regions, boxes)
        print(
            f"  p{page}: native={len(boxes)} boxes "
            f"({len(pictures)} pictures, {len(furniture)} furniture) | "
            f"pp={len(regions)} regions -> {len(figures)} figures"
        )
        for figure in figures:
            print(f"      figure {figure.kind} score={figure.score:.2f} box={figure.box}")

    print(
        f"timing: native {native_s:.2f}s total ({native_s / len(page_nums):.2f}s/page), "
        f"pp {pp_s:.2f}s total ({1000 * pp_s / len(page_nums):.0f}ms/page)"
    )
    doc.close()
    for image in rendered:
        image.unlink(missing_ok=True)
    render_dir.rmdir()


if __name__ == "__main__":
    main()
