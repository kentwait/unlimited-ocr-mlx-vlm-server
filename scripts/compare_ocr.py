"""Compare OCR models (mxfp8 vs int8) on identical page images.

Run:  uv run python /tmp/compare_ocr.py <model_ref> <tag>

For each cached page image: run gundam OCR, strip <|det|> markers
deterministically, score word 3-gram recall/contamination vs the pymupdf text
layer. Saves JSON to /tmp/ocr-cmp-<tag>.json and cleaned text to
/tmp/ocr-out-<tag>-p<page>.txt.
"""

from __future__ import annotations

import json
import re
import sys
import time

MODEL = sys.argv[1]
TAG = sys.argv[2]
PAGES = {1: "/tmp/gao-p1.png", 2: "/tmp/gao-p2.png"}
PDF = "/Users/kent/.hermes/attachments/gao2026.pdf"


def ngrams(text: str, n: int = 3) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def main() -> None:
    import pymupdf

    from ocr_server.cleanup import strip_det_markers
    from ocr_server.engine import OcrEngine

    doc = pymupdf.open(PDF)
    eng = OcrEngine(MODEL)
    t0 = time.perf_counter()
    eng.load()
    load_s = time.perf_counter() - t0

    results = {"model": MODEL, "load_s": round(load_s, 1), "pages": {}}
    for page_num, img in PAGES.items():
        t1 = time.perf_counter()
        raw, stats = eng.infer_image_file(
            img,
            prompt="document parsing.",
            max_tokens=16384,
            temperature=0.0,
            base_size=1024,
            image_size=640,
            cropping=True,
        )
        elapsed = time.perf_counter() - t1
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
        with open(f"/tmp/ocr-out-{TAG}-p{page_num}.txt", "w") as f:
            f.write(cleaned)
        print(
            f"page {page_num}: {stats.tokens} tok, {elapsed:.1f}s, {stats.tps:.0f} t/s, "
            f"early_stop={stats.early_stop}, recall={recall:.3f}, contam={contamination:.3f}",
            flush=True,
        )
    doc.close()
    with open(f"/tmp/ocr-cmp-{TAG}.json", "w") as f:
        json.dump(results, f, indent=1)
    print("saved /tmp/ocr-cmp-" + TAG + ".json")


if __name__ == "__main__":
    main()
