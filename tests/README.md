# Server tests: unit, integration, property, mutation

| File | What | Needs |
| --- | --- | --- |
| `test_units.py` | Pure helpers: spans, pages, rendering, boxes, crops, region filtering, merge, CLI | Python only |
| `test_native.py` | pymupdf4llm extraction: labels, normalization, page subsets, mapping | Fixture PDF |
| `test_pp.py` | PP-DocLayout-S: vendored model pin, lazy loading, real detection on rendered pages | Fixture PDF + ONNX |
| `test_pipeline.py` | End-to-end `parse_pdf` on the fixture: figure pages, ids, labels, errors, progress | Fixture PDF + ONNX |
| `test_properties.py` | Hypothesis invariants: box normalization, id assignment, JSONL round-trip, region filtering, page specs | Python only |
| `test_api.py` | HTTP endpoints over the real pipeline (no fake engines exist) | Fixture PDF + ONNX |

`assets/altemose2022.pdf` — committed test PDF (Altemose et al. 2022, 13
digital-born pages, text layer intact). Used by the integration/API tests and
as an acceptance fixture: six pages carry real figures (1, 3, 5, 6, 8, 9).

Everything is deterministic and weight-free: pymupdf4llm runs on the CPU and
the 4.7 MB PP-DocLayout-S ONNX export is vendored under
`src/ocr_server/models/` (SHA pinned by `test_pp.py`). The suite runs on any
platform, including CI.

## Coverage

`make coverage` enforces **95%** (`--cov-fail-under=95`; currently 100%).
Weight/model paths do not need pragmas: the ONNX session loads in tests.

## Property tests

Hypothesis pins invariants: normalized boxes are always in-bounds and
axis-sorted, span ids are unique and contiguous per page, JSONL round-trips
with `image` present iff a figure payload exists, region filtering never
returns undersized/oversized/overlapping boxes, and page specs stay sorted
and in-range. JSONL notes: records are separated by `\n` only — `json.dumps`
escapes `\n`/`\r`, but consumers must not use `str.splitlines()` (it also
splits on NEL/Unicode boundaries found in extracted text).

## Mutation testing (manual)

`make mutate` (`mutmut run`) — never CI. Config in `pyproject.toml`
(`[tool.mutmut]`): log-call lines are excluded (no test asserts log text).

**Do not trust parallel verdicts.** `--max-children N` runs misreport
survivors: a large share of parallel "survivors" die on isolated serial
re-runs (e.g. `max(None, b[0])`-class mutants inside `_iou` that every
covering test kills). Parallel runs are useful as a triage queue only; the
backstop oracle is serial re-run by name (`mutmut run <name...>`).

Baseline 2026-09-10 (digital-only rewrite), parallel full run: **918 killed
/ 265 survived / 1183** (~78% kill). Serial re-verification of the 265
survivors was run after the suite was hardened with exact-value pins (crop
pixels, IoU arithmetic, threshold boundaries, CLI/env wiring, upload-size
boundary); during that pass the serial verdicts flipped a large fraction of
the parallel survivors to killed, confirming the caveat above. A complete
serial baseline remains a follow-up.

Survivor classes to expect (triaged, not chased to zero):

- `__main__.main` (~43): logging/argparse/uvicorn plumbing strings and
  defaults; only the env wiring is asserted.
- math helpers (`_iou`, `_center_inside`, `_clamp_box`, ~45): equivalent
  mutants (comparison/min/max swaps that preserve outcomes on all asserted
  inputs) and unreachable guards.
- `figures.crop_data_uri` (~20): coordinate rounding/clamping arithmetic
  beyond the exact-pixel pins.
- `api._save_upload` (~18): status-message cosmetics and content-type
  fallbacks.
- `merge_page`/misc (~15): warning/log strings and defensive branches.

Triage policy: sample survivors per file, close cheap assertion gaps
(observable behavior only), record the new baseline here, and document
equivalent/noise classes. Re-run from a clean cache after changing tests
(`rm -rf .mutmut-cache mutants`), and re-run suspect mutants by name before
recording verdicts.
