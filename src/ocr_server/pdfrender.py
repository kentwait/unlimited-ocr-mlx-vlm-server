"""Render PDF pages to PNG files for OCR inference."""

from __future__ import annotations

from pathlib import Path

import pymupdf


def render_pdf_pages(
    doc: pymupdf.Document, page_nums: list[int], dpi: int, outdir: Path
) -> list[Path]:
    """Render the given 1-indexed pages to PNGs named page-NNNN.png.

    `doc` must remain open for the lifetime of the returned paths.
    """
    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)
    paths: list[Path] = []
    outdir.mkdir(parents=True, exist_ok=True)
    for n in page_nums:
        pix = doc[n - 1].get_pixmap(matrix=mat, alpha=False)
        p = outdir / f"page-{n:04d}.png"
        pix.save(str(p))
        paths.append(p)
    return paths
