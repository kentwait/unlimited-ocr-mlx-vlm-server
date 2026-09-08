"""Benchmark OCR models against a PDF's embedded text layer.

Compares Unlimited-OCR quantization variants (or any mlx-vlm OCR model) on
identical page images. For each page and DPI it runs OCR, strips <|det|> layout
markers deterministically, and scores word 3-gram recall / contamination
against the PDF's own text layer (the ground truth for digital-born PDFs).

Prerequisites:
  - A digital-born (text-based) PDF to use as the test document.
  - The repo's environment:  uv sync   (run from the repo root)

Usage (from the repo root):
  uv run python scripts/compare_ocr.py <model_ref> <tag>
  uv run python scripts/compare_ocr.py sahilchachra/unlimited-ocr-mxfp8-mlx mxfp8

Every USER CONFIG value can also be overridden via environment variable
(useful for sweep scripts that don't want to edit this file):
  OCR_CMP_PDF, OCR_CMP_PAGES (comma-separated), OCR_CMP_DPIS (comma-separated),
  OCR_CMP_WORKDIR

Outputs (in WORK_DIR):
  page-<dpi>-pNNNN.png     rendered page image, one per (dpi, page)
  ocr-raw-<tag>-pN-dD.txt  raw OCR text
  ocr-out-<tag>-pN-dD.txt  marker-stripped OCR (scored)
  ocr-cmp-<tag>.json       metrics for this run (all pages, all DPIs)

Run scripts/compare_cleanup.py afterwards to benchmark cleanup models on the
same pages (it reuses the cached OCR text).

----------------------------------------------------------------------------------------------------
CONFIGURATION — edit the "USER CONFIG" block below, or set the env overrides.
----------------------------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# ============================== USER CONFIG ==============================

# Path to the test PDF. It must have an embedded text layer (i.e. text you can
# select/copy in a PDF viewer), which is used as the scoring ground truth.
PDF_PATH = "/tmp/test-paper.pdf"  # <-- CHANGE: your test PDF   [env: OCR_CMP_PDF]

# Which pages to benchmark (1-indexed). Two or three pages is usually enough;
# include at least one dense page (e.g. two-column body text).
PAGE_NUMBERS = [1, 2]  # <-- CHANGE if you want different pages   [env: OCR_CMP_PAGES]

# Render resolution(s) for the page images, 72-300. Multiple DPIs are swept in
# one run (one model load). 72 = low / 150 = typical / 300 = high detail.
DPIS = [150]  # <-- CHANGE: e.g. [72, 150, 300]   [env: OCR_CMP_DPIS]

# Where page images, OCR caches, and result JSON/files are written.
WORK_DIR = Path("/tmp/ocr-compare")  # <-- CHANGE: writable scratch dir   [env: OCR_CMP_WORKDIR]

# =========================================================================

PDF_PATH = os.environ.get("OCR_CMP_PDF", PDF_PATH)
PAGE_NUMBERS = [int(x) for x in os.environ.get("OCR_CMP_PAGES", ",".join(map(str, PAGE_NUMBERS))).split(",")]
DPIS = [int(x) for x in os.environ.get("OCR_CMP_DPIS", ",".join(map(str, DPIS))).split(",")]
WORK_DIR = Path(os.environ.get("OCR_CMP_WORKDIR", str(WORK_DIR)))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

MODEL = sys.argv[1] if len(sys.argv) > 1 else "sahilchachra/unlimited-ocr-mxfp8-mlx"
TAG = sys.argv[2] if len(sys.argv) > 2 else "run"


def ngrams(text: str, n: int = 3) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def render_pages() -> dict[tuple[int, int], Path]:
    """Render (dpi, page) -> png path, cached per (dpi, page)."""
    import pymupdf

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(PDF_PATH)
    paths = {}
    for dpi in DPIS:
        if not 72 <= dpi <= 300:
            sys.exit(f"error: dpi {dpi} outside supported 72-300")
        for page_num in PAGE_NUMBERS:
            p = WORK_DIR / f"page-{dpi:03d}-p{page_num:04d}.png"
            if not p.exists():
                pix = doc[page_num - 1].get_pixmap(
                    matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False
                )
                pix.save(str(p))
                print(f"rendered page {page_num} @ {dpi}dpi -> {p} ({pix.width}x{pix.height})")
            paths[(dpi, page_num)] = p
    doc.close()
    return paths


def main() -> None:
    import pymupdf

    from ocr_server.cleanup import strip_det_markers
    from ocr_server.engine import OcrEngine

    if not Path(PDF_PATH).is_file():
        print(
            f"error: test PDF not found: {PDF_PATH}\n"
            "Set PDF_PATH in the USER CONFIG block (or OCR_CMP_PDF) to a "
            "text-layer PDF on your machine."
        )
        sys.exit(1)

    page_images = render_pages()
    doc = pymupdf.open(PDF_PATH)
    eng = OcrEngine(MODEL)
    t0 = time.perf_counter()
    eng.load()
    load_s = time.perf_counter() - t0

    results = {"model": MODEL, "load_s": round(load_s, 1), "pages": {}}
    for (dpi, page_num), img in sorted(page_images.items()):
        t1 = time.perf_counter()
        raw, stats = eng.infer_image_file(
            str(img),
            prompt="document parsing.",
            max_tokens=16384,
            temperature=0.0,
            base_size=1024,
            image_size=640,
            cropping=True,
        )
        elapsed = time.perf_counter() - t1
        (WORK_DIR / f"ocr-raw-{TAG}-p{page_num}-d{dpi}.txt").write_text(raw)
        cleaned = strip_det_markers(raw)

        text_layer = doc[page_num - 1].get_text()
        g_ocr = ngrams(raw)
        g_truth = ngrams(text_layer)
        g_out = ngrams(cleaned)
        recall = len(g_out & g_truth) / max(1, len(g_out))
        contamination = len(g_out - g_truth - g_ocr) / max(1, len(g_out))
        results["pages"][f"p{page_num}-d{dpi}"] = {
            "gen_tokens": stats.tokens,
            "gen_s": round(elapsed, 1),
            "tps": round(stats.tps or 0.0, 1),
            "early_stop": stats.early_stop,
            "out_chars": len(cleaned),
            "word3gram_recall_vs_textlayer": round(recall, 4),
            "contaminated_3gram_frac": round(contamination, 4),
        }
        (WORK_DIR / f"ocr-out-{TAG}-p{page_num}-d{dpi}.txt").write_text(cleaned)
        print(
            f"page {page_num} @ {dpi}dpi: {stats.tokens} tok, {elapsed:.1f}s, "
            f"{stats.tps:.0f} t/s, early_stop={stats.early_stop}, "
            f"recall={recall:.3f}, contam={contamination:.3f}",
            flush=True,
        )
    doc.close()
    out = WORK_DIR / f"ocr-cmp-{TAG}.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
