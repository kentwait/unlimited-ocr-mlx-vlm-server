"""Compare cleanup models on identical inputs.

Run:  uv run python /tmp/compare_cleanup.py <model_ref> <tag>

For each cached page (raw OCR + text layer), run the cleanup LLM, then score:
  - word 3-gram recall vs the pymupdf text layer (fidelity to ground truth)
  - contamination: fraction of output 3-grams NOT present in OCR or text layer
  - tokens generated, wall time, loop/early-stop
Outputs JSON to /tmp/cleanup-cmp-<tag>.json and prints a summary.
"""

from __future__ import annotations

import json
import re
import sys
import time

MODEL = sys.argv[1]
TAG = sys.argv[2]

PAGES = {
    1: ("/tmp/gao-p1-ocr.txt", "/tmp/gao-p1.png"),
    2: ("/tmp/gao-p2-ocr.txt", "/tmp/gao-p2.png"),
}
PDF = "/Users/kent/.hermes/attachments/gao2026.pdf"


def ngrams(text: str, n: int = 3) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def main() -> None:
    import pymupdf

    from ocr_server.cleanup import CleanupEngine

    doc = pymupdf.open(PDF)
    eng = CleanupEngine(MODEL)
    t0 = time.perf_counter()
    eng.load()
    load_s = time.perf_counter() - t0

    results = {"model": MODEL, "load_s": round(load_s, 1), "pages": {}}
    for page_num, (ocr_path, _img) in PAGES.items():
        ocr = open(ocr_path).read()
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
        with open(f"/tmp/cleanup-out-{TAG}-p{page_num}.md", "w") as f:
            f.write(cleaned)
        print(
            f"page {page_num}: {stats.tokens} tok, {stats.elapsed_s:.1f}s, "
            f"early_stop={stats.early_stop}, recall={recall:.3f}, "
            f"contam={contamination:.3f}",
            flush=True,
        )
    doc.close()
    with open(f"/tmp/cleanup-cmp-{TAG}.json", "w") as f:
        json.dump(results, f, indent=1)
    print("saved /tmp/cleanup-cmp-" + TAG + ".json")


if __name__ == "__main__":
    main()
