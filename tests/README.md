# Server tests: unit, property, mutation

| File | What | Needs |
| --- | --- | --- |
| `test_api.py` | Endpoint behavior (fake engine) | Python only |
| `test_units.py` | Pure helpers: spans, pages, schemas, prompts, audit, engine helpers, furniture, CLI | Python only |
| `test_pipeline.py` | Full pipeline with stubbed LLM (`CleanupEngine._generate` canned) | Python only |
| `test_properties.py` | Hypothesis invariants + API fuzzing (fake engine) | Python only |

`assets/altemose2022.pdf` — committed test PDF (Altemose et al. 2022, 13
digital-born pages, text layer intact). Default `PDF_PATH` for
`scripts/compare_ocr.py` / `compare_cleanup.py` (override with
`OCR_CMP_PDF`); `test_altemose.py` runs the real file through the
layout-first pipeline with stubbed LLM calls (no weights).

## Coverage

`make coverage` enforces **95%** (`--cov-fail-under=95`; currently 100%).
MLX weight paths carry `# pragma: no cover` with a justification comment
— pragmas are for weights/hardware only, never for logic.

## Property tests

Hypothesis properties pin invariants (fingerprint normalization, span
preservation, render rules, audit attribution, page-spec totality) and API
robustness (fuzzed form fields never 500; reflow fails closed without a
token). API fuzz uses small example counts with `deadline=None` — server
timing under load is not the property under test. Documented findings live
as comments at the assertion (empty-form default fallback, `lower()`-based
matching, blank-page anchor drops on the client).

## Mutation testing (manual)

`make mutate` (`mutmut run`) — never CI. Config in `pyproject.toml`
(`[tool.mutmut]`): `fake.py` excluded (dev-only test double),
log-call lines excluded (no test asserts log text), weight functions
carry `# pragma: no mutate block`.

Baseline 2026-09-09: ~1057 killed / 500 survived / 12 suspicious of 1569.
Baseline 2026-09-10 (layout-support work): 1427 killed / 417 survived /
13 suspicious of 1857. `layout.py` contributes only 6 survivors, all
proven-equivalent by direct application (listed above); `scan_layout`
survivors from the triage pass were killed by prompt/budget/timing pins
(serial re-runs confirm — parallel verdicts for single mutants have
flaked before, see the caveat below).
Triage policy: sample survivors per file, fix cheap assertion gaps
(unasserted defaults, exact-output checks, load-once behavior), record the
new baseline here. Do not chase zero — equivalent mutants and
argparse/logging noise are documented, not fixed.

Layout-support triage 2026-09-10 (`layout.py`, `SupportEngine.scan_layout`):
two simplifications fell out directly — the `_clean_box` inversion check
(subsumed by the size floor) and strict type/branch coverage became exact
profile assertions, boundary tests (inset edges, confidence/size
thresholds), count assertions (no `= 1` vs `+= 1` slips), idempotence
(pre-labeled spans never recounted), and vision-plumbing pins (prompt
carries the page, 384-token budget, elapsed timing). Proven-equivalent,
kept as documentation: brace-slice non-dict guard (unreachable —
`# pragma: no cover`), `figures` default and dict-without-box defaults
(same outcome downstream), int-column `and`/`or` (both paths reject),
`check_spans` empty-spans page default (unused on that path), and the
`or`→`and` precedence guard (the band check subsumes it). The vestigial
`check_spans(journal=)` parameter was deleted outright after mutation
showed the argument no longer affects the drop set.

Caveat (observed 2026-09-10): parallel `--max-children` runs can
misreport verdicts — a layout mutant reported as survived died on an
isolated serial re-run. Backstop: re-run suspect mutants by name
(`mutmut run <name>`) before chasing them; record serial-confirmed
baselines only.

Workflow: `make mutate` (resumable via `.mutmut-cache/`), then
`mutmut results` and `mutmut show <name>` per file; re-run from a clean
cache after changing tests (`rm -rf .mutmut-cache mutants`), since results
are keyed on sources.
