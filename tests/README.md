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
(`[tool.mutmut]`): the vendored model directory is excluded (data, not
code), log-call lines are excluded (no test asserts log text).

Baseline 2026-09-10 (digital-only rewrite): recorded after the first triage
pass below. Triage policy: sample survivors, close cheap assertion gaps,
record the baseline here. Equivalent mutants and logging noise are
documented, not chased.
