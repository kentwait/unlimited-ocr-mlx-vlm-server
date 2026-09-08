"""Benchmark OCR models against a PDF's embedded text layer.

Compares Unlimited-OCR quantization variants (or any mlx-vlm OCR model) on
identical page images. For each page it runs OCR, strips <|det|> layout
markers deterministically, and scores word 3-gram recall / contamination
against the PDF's own text layer (the ground truth for digital-born PDFs).

Prerequisites:
  - A digital-born (text-based) PDF to use as the test document.
  - The repo's environment:  uv sync   (run from the repo root)

Usage (from the repo root):
  uv run python scripts/compare_ocr.py <model_ref> <tag>
  uv run python scripts/compare_ocr.py sahilchachra/unlimited-ocr-mxfp8-mlx mxfp8
  uv run python scripts/compare_ocr.py bf16-repo-id bf16

Outputs (in WORK_DIR):
  page-000N.png          rendered page image (reused across runs)
  ocr-raw-<tag>-pN.txt   raw OCR text
  ocr-out-<tag>-pN.txt   marker-stripped OCR (scored)
  ocr-cmp-<tag>.json     metrics for this run

Run scripts/compare_cleanup.py afterwards to benchmark cleanup models on the
same pages (it reuses the cached OCR text).

----------------------------------------------------------------------------------------------------
CONFIGURATION — edit the values in the "USER CONFIG" block below before running.
----------------------------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

# ============================== USER CONFIG ==============================

# Path to the test PDF. It must have an embedded text layer (i.e. text you can
# select/copy in a PDF viewer), which is used as the scoring ground truth.
PDF_PATH = "/tmp/test-paper.pdf"  # <-- CHANGE: your test PDF

# Which pages to benchmark (1-indexed). Two or three pages is usually enough;
# include at least one dense page (e.g. two-column body text).
PAGE_NUMBERS = [1, 2]  # <-- CHANGE if you want different pages

# Render resolution for the page images (72-300; 200 is a good default).
DPI = 200  # <-- CHANGE only if you also benchmark at a different dpi

# Where page images, OCR caches, and result JSON/files are written.
WORK_DIR = Path("/tmp/ocr-compare")  # <-- CHANGE: any writable scratch dir

# =========================================================================

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

MODEL = sys.argv[1] if len(sys.argv) > 1 else "sahilchachra/unlimited-ocr-mxfp8-mlx"
TAG = sys.argv[2] if len(sys.argv) > 2 else "run"


def ngrams(text: str, n: int = 3) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def render_pages() -> dict[int, Path]:
    import pymupdf

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(PDF_PATH)
    paths = {}
    for page_num in PAGE_NUMBERS:
        p = WORK_DIR / f"page-{page_num:04d}.png"
        if not p.exists():
            pix = doc[page_num - 1].get_pixmap(
                matrix=pymupdf.Matrix(DPI / 72, DPI / 72), alpha=False
            )
            pix.save(str(p))
            print(f"rendered page {page_num} -> {p} ({pix.width}x{pix.height})")
        paths[page_num] = p
    doc.close()
    return paths


def main() -> None:
    import pymupdf

    if not Path(PDF_PATH).is_file():
        print(
            f"error: test PDF not found: {PDF_PATH}\n"
            "Edit the USER CONFIG block at the top of this script and set "
            "PDF_PATH (and PAGE_NUMBERS) to a text-layer PDF on your machine."
        )
        sys.exit(1)

    from ocr_server.cleanup import strip_det_markers
    from ocr_server.engine import OcrEngine

    page_images = render_pages()
    doc = pymupdf.open(PDF_PATH)
    eng = OcrEngine(MODEL)
    t0 = time.perf_counter()
    eng.load()
    load_s = time.perf_counter() - t0

    results = {"model": MODEL, "load_s": round(load_s, 1), "pages": {}}
    for page_num, img in page_images.items():
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
        (WORK_DIR / f"ocr-raw-{TAG}-p{page_num}.txt").write_text(raw)
        cleaned = strip_det_markers(raw)

        text_layer = doc[page_num - 1].get_text()
        g_ocr = ngrams(raw)
        g_truth = ngrams(text_layer)
        g_out = ngrams(cleaned)
        recall = len(g_out & g_truth) / max(1, len(g_out))
        contamination = len(g_out - g_truth - g_ocr) / max(1, len(g_out))
        results["pages"][page_num] = {
            "gen_tokens": stats.tokens,
            "gen_s": round(elapsed, 1),
            "tps": round(stats.tps or 0.0, 1),
            "early_stop": stats.early_stop,
            "out_chars": len(cleaned),
            "word3gram_recall_vs_textlayer": round(recall, 4),
            "contaminated_3gram_frac": round(contamination, 4),
        }
        (WORK_DIR / f"ocr-out-{TAG}-p{page_num}.txt").write_text(cleaned)
        print(
            f"page {page_num}: {stats.tokens} tok, {elapsed:.1f}s, {stats.tps:.0f} t/s, "
            f"early_stop={stats.early_stop}, recall={recall:.3f}, contam={contamination:.3f}",
            flush=True,
        )
    doc.close()
    out = WORK_DIR / f"ocr-cmp-{TAG}.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
