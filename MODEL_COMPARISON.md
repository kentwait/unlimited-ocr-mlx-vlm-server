# Model comparison — OCR & cleanup stages

All numbers measured on this machine (Apple M4 Max, 36 GB unified memory) with
the harnesses in `scripts/compare_ocr.py` and `scripts/compare_cleanup.py`.
Test pages: **gao2026.pdf** (Nature, two-column publisher PDF) — page 1
(title/metadata page, ~5.5k chars) and page 2 (dense two-column body text,
~8.4k chars). Rendered at 200 dpi; gundam mode; temperature 0.

Metrics:
- **recall** = share of the output's word 3-grams found in the pymupdf text
  layer (fidelity to ground truth wording)
- **contam** = share of output 3-grams found in *neither* the text layer nor
  the raw OCR (invented/reformatted content)
- **loop** = generation hit the degenerate-repetition early-stop or the token
  cap (wasted tokens, truncated content)

## OCR stage (Unlimited-OCR variants)

Input: rendered page image → markdown. Scored after deterministic marker strip.

| model | quant | disk | peak mem | p1 recall/contam | p2 recall/contam | p2 loop? | t/s |
|---|---|---|---|---|---|---|---|
| `sahilchachra/unlimited-ocr-mxfp8-mlx` | MXFP8 (9.2 bpw) | 3.7 GB | ~4.6 GB | .788 / .018 | **.901 / .006** | yes, 6652 tok | ~330 |
| `sahilchachra/unlimited-ocr-8bit-mlx` | int8 (7.8 bpw) | 3.7 GB | ~4.6 GB | .794 / .019 | .856 / .011 | **yes, worse** (812 tok) | ~335 |
| `mlx-community/Unlimited-OCR-bf16` | bf16 (16 bpw) | 6.5 GB | ~7.6 GB | **.802 / .016** | .896 / .003 | **no — natural finish** (2215 tok) | ~230 |
| `baidu/Unlimited-OCR` (official) | bf16 | 6.5 GB | ~7.6 GB | = bf16 (identical outputs) | = | = | ~230 |

Findings:
1. **Quantization hurts dense-page robustness.** Both 8-bit-ish variants
   repetition-loop on the dense page; bf16 completes it naturally. This
   matches the model author's own CER ordering (MXFP8 1.456 < Int8 1.572 on
   FUNSD), though their FP16-vs-MXFP8 CER ordering did not reproduce here —
   on real two-column pages bf16 wins on stability, mxfp8 on raw recall.
2. **mxfp8 vs bf16 is a speed/stability trade, not a quality trade**: mxfp8 is
   ~40% faster per token and 3 GB lighter, but on dense pages it can burn
   thousands of tokens into loops before the early-stop; bf16 costs ~1.4×
   wall-clock in the worst case and ~2× in the loop case it avoids.
3. mlx-community bf16 ≡ official `baidu/Unlimited-OCR` (byte-identical
   behavior) — either is fine; prefer the community one for smaller download.

## Cleanup stage (Qwen3.5 sizes × quants)

Task: merge pre-cleaned OCR markdown with the pymupdf text layer into clean
Markdown (text layer = wording ground truth).

| model | quant | disk | peak mem | p1 recall/contam | p1 behavior | p2 recall/contam | p2 time |
|---|---|---|---|---|---|---|---|
| Qwen3.5-0.8B | 4-bit | ~0.7 GB | ~1.5 GB | .874 / .110 | hit 8k cap, rambled | .927 / .023 | 7 s |
| **Qwen3.5-0.8B** | **8-bit** | ~1 GB | ~1.7 GB | **.891 / .093** | clean stop | **.932 / .005** | 8 s |
| Qwen3.5-0.8B | bf16 | 1.6 GB | ~2.3 GB | .891 / .093 | = q8 exactly | .932 / .005 | 12 s |
| Qwen3.5-2B | 4-bit | ~1.4 GB | ~2.5 GB | .761 / .194 | looped | .909 / .018 | 11 s |
| Qwen3.5-2B | 8-bit | ~2.4 GB | ~3.5 GB | .663 / .250 | rambled 3k tok | .900 / .033 | 17 s |
| Qwen3.5-2B | bf16 | ~4.3 GB | ~5 GB | .670 / .245 | rambled 2.7k tok | .900 / .033 | 27 s |

Findings:
1. **Quantization hypothesis confirmed for the 0.8B**: 4-bit caused the
   cap-hitting ramble; 8-bit fixed it and is byte-identical to bf16 (8-bit is
   effectively lossless at this scale). Use ≥8-bit for small cleanup models.
2. **Bigger is worse here**: 2B drifts into summarizing/reformatting at every
   precision (up to 25% invented 3-grams on p1). Faithful reconciliation is a
   precision task, not a capability task. Don't upsize past 0.8B without
   re-validating.
3. Net quality order: **0.8B-q8 ≈ 0.8B-bf16 > 0.8B-q4 > 2B (all quants)**.
   The cleanup stage lifts final fidelity ~10 points over raw OCR recall
   (0.79 → 0.89 on p1) by pulling wording from the text layer.

## Recommendations by memory budget

Resident set = OCR engine + cleanup engine (+ alternate OCR if enabled).

| budget | OCR | cleanup | notes |
|---|---|---|---|
| ≥ 16 GB free | bf16 (6.5 GB) + Qwen3.5-0.8B-q8 (1 GB) ≈ **9 GB** | — | most stable: no OCR loops, best cleanup; ~1.4× slower than mxfp8 |
| ≥ 12 GB free | mxfp8 (3.7 GB) + 0.8B-q8 (1 GB) ≈ **5 GB** | — | **current default**; fast, occasionally loop-truncated dense pages (mitigated by early-stop; retry at dpi 250) |
| 8–12 GB | mxfp8 + Qwen3.5-0.8B-4bit ≈ 4.5 GB | — | accept q4 cleanup ramble risk, or disable cleanup (`OCR_CLEANUP=0`) |
| < 8 GB | mxfp8 only (3.7 GB) | disabled | pre-clean only; skip LLM cleanup |

Switching knobs: `OCR_MODEL_REF` (server default), `ocr_model` form field
(`bf16` shortcut or any HF repo/local path — loads lazily and stays resident),
`OCR_CLEANUP_MODEL`, `OCR_CLEANUP=0`.

## Chosen defaults

- OCR: `sahilchachra/unlimited-ocr-mxfp8-mlx` (speed + memory; loop risk
  bounded by token-tail early-stop; `ocr_model=bf16` per-request for
  loop-sensitive dense batches)
- Cleanup: `mlx-community/Qwen3.5-0.8B-MLX-8bit` (best fidelity, 1 GB, q8 ≡ bf16)
