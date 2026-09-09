# Server tests: unit, property, mutation

| File | What | Needs |
| --- | --- | --- |
| `test_api.py` | Endpoint behavior (fake engine) | Python only |
| `test_units.py` | Pure helpers: spans, pages, schemas, prompts, audit, engine helpers, furniture, CLI | Python only |
| `test_pipeline.py` | Full pipeline with stubbed LLM (`CleanupEngine._generate` canned) | Python only |
| `test_properties.py` | Hypothesis invariants + API fuzzing (fake engine) | Python only |

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
Triage policy: sample survivors per file, fix cheap assertion gaps
(unasserted defaults, exact-output checks, load-once behavior), record the
new baseline here. Do not chase zero — equivalent mutants and
argparse/logging noise are documented, not fixed.

Workflow: `make mutate` (resumable via `.mutmut-cache/`), then
`mutmut results` and `mutmut show <name>` per file; re-run from a clean
cache after changing tests (`rm -rf .mutmut-cache mutants`), since results
are keyed on sources.
