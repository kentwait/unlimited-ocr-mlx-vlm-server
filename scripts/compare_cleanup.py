"""Benchmark cleanup models (OCR + text-layer -> clean Markdown).

Runs the repo's cleanup stage (small LLM reconciling OCR markdown with the
PDF's embedded text layer) over the same pages used by scripts/compare_ocr.py,
and scores word 3-gram recall / contamination against the text layer.

Prerequisites:
  - Run scripts/compare_ocr.py first (once, with any OCR model): it renders
    the page images and caches the raw OCR text this script consumes.
  - The repo's environment:  uv sync   (run from the repo root)

Usage (from the repo root):
  uv run python scripts/compare_cleanup.py <model_ref> <tag>
  uv run python scripts/compare_cleanup.py mlx-community/Qwen3.5-0.8B-MLX-8bit q8

Outputs (in WORK_DIR):
  cleanup-out-<tag>-pN.md   cleaned Markdown (scored)
  cleanup-cmp-<tag>.json    metrics for this run

----------------------------------------------------------------------------------------------------
CONFIGURATION — edit the values in the "USER CONFIG" block below before running.
They must match the values you used in scripts/compare_ocr.py.
----------------------------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

# ============================== USER CONFIG ==============================

# Must be the SAME PDF / pages / work dir you used for scripts/compare_ocr.py.
PDF_PATH = "/tmp/test-paper.pdf"  # <-- CHANGE: your test PDF
PAGE_NUMBERS = [1, 2]  # <-- CHANGE: same pages as compare_ocr.py
WORK_DIR = Path("/tmp/ocr-compare")  # <-- CHANGE: same dir as compare_ocr.py

# =========================================================================

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

MODEL = sys.argv[1] if len(sys.argv) > 1 else "mlx-community/Qwen3.5-0.8B-MLX-8bit"
TAG = sys.argv[2] if len(sys.argv) > 2 else "run"


def ngrams(text: str, n: int = 3) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def main() -> None:
    import pymupdf

    if not Path(PDF_PATH).is_file():
        print(
            f"error: test PDF not found: {PDF_PATH}\n"
            "Edit the USER CONFIG block at the top of this script and set "
            "PDF_PATH (and PAGE_NUMBERS) to a text-layer PDF on your machine."
        )
        sys.exit(1)

    from ocr_server.cleanup import CleanupEngine

    doc = pymupdf.open(PDF_PATH)
    eng = CleanupEngine(MODEL)
    t0 = time.perf_counter()
    eng.load()
    load_s = time.perf_counter() - t0

    results = {"model": MODEL, "load_s": round(load_s, 1), "pages": {}}
    for page_num in PAGE_NUMBERS:
        ocr_path = WORK_DIR / f"ocr-raw-{TAG}-p{page_num}.txt"
        # The raw OCR cache is written by compare_ocr.py with ITS tag; look for
        # any tag's cache for this page rather than failing outright.
        if not ocr_path.exists():
            candidates = sorted(WORK_DIR.glob(f"ocr-raw-*-p{page_num}.txt"))
            if not candidates:
                print(
                    f"error: no cached OCR for page {page_num} in {WORK_DIR}.\n"
                    "Run scripts/compare_ocr.py first (it renders pages and "
                    "caches raw OCR text)."
                )
                sys.exit(1)
            ocr_path = candidates[0]
        ocr = ocr_path.read_text()
        text_layer = doc[page_num - 1].get_text()

        cleaned, stats = eng.cleanup_page(ocr, text_layer, max_tokens=8192)
        g_ocr = ngrams(ocr)
        g_truth = ngrams(text_layer)
        g_out = ngrams(cleaned)
        recall = len(g_out & g_truth) / max(1, len(g_out))
        contamination = len(g_out - g_truth - g_ocr) / max(1, len(g_out))
        results["pages"][page_num] = {
            "method": stats.method,
            "gen_tokens": stats.tokens,
            "gen_s": round(stats.elapsed_s, 1),
            "early_stop": stats.early_stop,
            "out_chars": len(cleaned),
            "word3gram_recall_vs_textlayer": round(recall, 4),
            "contaminated_3gram_frac": round(contamination, 4),
        }
        (WORK_DIR / f"cleanup-out-{TAG}-p{page_num}.md").write_text(cleaned)
        print(
            f"page {page_num}: {stats.tokens} tok, {stats.elapsed_s:.1f}s, "
            f"early_stop={stats.early_stop}, recall={recall:.3f}, "
            f"contam={contamination:.3f}",
            flush=True,
        )
    doc.close()
    out = WORK_DIR / f"cleanup-cmp-{TAG}.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
