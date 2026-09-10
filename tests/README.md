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

## Assistant tests

`test_assistant_parser.py` (XML tool-call extraction, streaming filter,
message conversion, Hypothesis properties) and `test_assistant_api.py`
(fake runtime lifecycle, guards, SSE shapes, cancellation) run without MLX;
weight-dependent paths carry `# pragma: no cover`. The `OCR_ASSISTANT_FAKE=1`
runtime is also what `scripts/contract-check.mjs` uses in the app repo.

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

Baseline 2026-09-10 (digital-only rewrite): **1183 mutants**. A parallel
full run (stable across two repeats) reported **918 killed / 265 survived**.
Every parallel survivor was then re-verified **serially**
(`mutmut run --max-children 1 <name...>`) with this hardened suite:
**252 confirmed survived, 13 killed** — i.e. parallel survivor verdicts held
~95% of the time. The flake is real but rare; serial re-run by name remains
the oracle, and recorded baselines come from serial runs. Harness note:
`mutmut run` defaults to parallel even without `--max-children`; pass
`--max-children 1` for a true serial pass.

Survivor classes to expect (triaged, not chased to zero):

- `__main__.main` (43): logging/argparse/uvicorn plumbing strings and
  defaults; only the env wiring is asserted.
- `pipeline.parse_pdf` (30): warning/log string arguments, message wording,
  and defensive branches around the happy path.
- math helpers (`pp_layout._iou`, `_center_inside`, `_clamp_box`,
  `pipeline._iou`/`_center_inside`/`_picture_matches`; ~54): equivalent
  mutants (comparison/min/max swaps that preserve outcomes on all asserted
  inputs) and unreachable guards.
- `figures.crop_data_uri` (23): coordinate rounding/clamping arithmetic
  beyond the exact-pixel pins.
- `native_layout.extract_boxes` (21) and `normalize_box` (6): missing-key
  fallbacks and clamping branches.
- `api._save_upload` (18): status-message cosmetics and content-type
  fallbacks.
- `pp_layout.clean_regions` (16), `pages.parse_pages_spec` (12): equivalent
  predicate swaps on the tested input space.
- `LayoutModel.load/detect`, `merge_page`, `spans_to_jsonl`,
  `render_pdf_pages` (~20): idempotence/equivalence and log arguments.

Triage policy: sample survivors per file, close cheap assertion gaps
(observable behavior only), record the new baseline here, and document
equivalent/noise classes. Re-run from a clean cache after changing tests
(`rm -rf .mutmut-cache mutants`).
