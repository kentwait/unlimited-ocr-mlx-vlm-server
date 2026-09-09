# Data-Flow Lifecycles — OCR Library UI

Planned lifecycles for the Tauri library UI, authored with the
`plan-data-flow` skill (contract `urn:data-flow-graph:schema:3`) from the
UI plan agreed in conversation. Each pair = one node-link JSON graph + one
markdown narration; all views (sequence, data-flow, initiation/termination,
paths) filter the JSON, never join across files.

## Legend

Groups: 1 = UI panes/components (webview), 2 = Rust command layer
(src-tauri), 3 = feature client-safe modules, 7 = OCR server (FastAPI,
external process), 8 = filesystem under the library root.

Outcomes: `success` happy path · `error` handled failure surfaced to the
user · `anomaly` design-level finding (verified-absent path, lost work,
missing guard).

Kinds: `call` synchronous request · `return` response flows back ·
`event` fire-and-forget emission.

## Lifecycles

| Pair | Entry point | Status | Mode |
| --- | --- | --- | --- |
| [pdf-select-sidecar-load](pdf-select-sidecar-load.md) | `LibraryPage` tree select | exists in code (Tauri rewrite) | Initialize |
| [pdf-ocr-save](pdf-ocr-save.md) | `POST /parse/jobs` → sidecar writes | exists in code (Tauri rewrite) | Initialize |

## Anomaly & spec-gap digest

| Finding | Pair | Disposition |
| --- | --- | --- |
| Unhandled rejection when `list_tree` fails (old tree kept, no user-visible error) | pdf-select-sidecar-load | test candidate |
| Corrupt spans JSONL leaves markdown displayed with no overlay, silently | pdf-select-sidecar-load | test candidate |
| Server restart orphans running jobs (`_jobs` is in-memory); poll 404s raw | pdf-ocr-save | scope cut (v1), test candidate for "job lost — server restarted?" |
| No concurrent-job guard / upload-size feedback before submit | pdf-ocr-save | test candidate |

## Reproducing / validating

```bash
python3 ~/.hermes/skills/plan-data-flow/scripts/check_graphs.py ui/docs/dataflow
```
