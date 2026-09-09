<!-- pair-contract: urn:data-flow-graph:schema:3 -->
# pdf-ocr-save. PDF OCR Job & Sidecar Save

When the user runs OCR on a PDF, the app uploads it to the OCR server's
async job endpoint, polls job progress (phase + per-page counts), and on
success writes the anchored markdown and spans JSONL sidecars next to the
PDF, refreshing the tree badges.

- **Status:** Initialize — server endpoints and the UI orchestration exist
  in code today; the sidecar-write contract comes from the agreed UI plan.
- **Entry point:** `POST /parse/jobs`
  (`src/ocr_server/api.py:parse_pdf_async`)
- **Trigger:** User click on "OCR this PDF" (or "Re-run OCR") for a
  selected PDF.
- **Termination:** return-to-initiator with sidecars written (`FS_ROOT`
  as sink); on job error, return-to-initiator with an error message and no
  writes.
- **Response:**
  - **Success:** `job.status = done` with `result.results[]` (per-page
    markdown, spans_jsonl, corrections); UI saves both sidecars and
    refreshes the tree.
  - **Failure:** `job.status = error` with `error` detail → toolbar alert;
    also HTTP-level failures (server down → fetch catch; unknown job →
    404 text).
  - **Exception:** server restart mid-job loses the in-memory job → poll
    404s; surfaced as a handled-looking error but semantically an anomaly
    (work is lost, no retry artifact exists).

## Participants

| Node ID | Group | Role | Evidence | Symbol | What | Source |
| --- | --- | --- | --- | --- | --- | --- |
| `LIBRARY_UI` | 1 | initiator | code | `startOcr` | Reads PDF bytes, submits job, polls, saves sidecars | `ui/src/features/library/pages/library-page.tsx:startOcr` |
| `FS_ROOT` | 8 | sink | code | `-` | PDF read; sidecar writes | `ui/src-tauri/src/lib.rs:write_text_file` |
| `OCR_SERVER` | 7 | intermediary | code | `parse_pdf_async` | Submits background parse job | `src/ocr_server/api.py:parse_pdf_async` |
| `OCR_JOB_POLL` | 7 | intermediary | code | `job_status` | Progress + result endpoint | `src/ocr_server/api.py:job_status` |
| `RUST_WRITE_CMD` | 2 | intermediary | code | `write_text_file` | Root-scoped UTF-8 file writes | `ui/src-tauri/src/lib.rs:write_text_file` |

## Sequence

1. (seq 1–2) `startOcr` fetches the PDF via `convertFileSrc`, builds a
   `File`, and POSTs multipart to `/parse/jobs` (defaults: `pages=all`,
   `dpi=300`, `furniture=auto`, `ocr_model=default`).
2. (seq 3–4) Server returns 202 `ParseJobStatus{job_id}`; a background
   task runs `_parse_pdf_path` writing `phase`/`pages_done`/`pages_total`
   progress onto the job (`api.py:_parse_pdf_path`).
3. (seq 5–6) `pollJobUntilDone` polls every 1.5 s; each response is
   Zod-validated (`ParseJobStatusSchema`).
4. (seq 7–11) On done: markdown assembled with `<!-- ocr:page:N -->`
   anchors per page; both sidecars written via `write_text_file` inside
   the root; `refreshTree()` flips the tree badge; markdown pane shows the
   result.
5. (seq 12–14) Error paths below.

## Error paths

### Job completes with error status

_Covers:_ seq 12, `OCR_SERVER` → `LIBRARY_UI` (outcome: error)

`_parse_pdf_path` raises `HTTPException` (bad pages spec, unreadable PDF)
or an unexpected error; `_run` sets `job.status = "error"`, `job.error =
detail`. UI: `onJobSettled` shows the message in the toolbar alert; no
sidecars written. Promised by `api.py` job contract.

### Unknown job id on poll

_Covers:_ seq 13, `OCR_JOB_POLL` → `LIBRARY_UI` (outcome: error)

`GET /parse/jobs/{id}` raises 404 for unknown ids (`api.py:job_status`);
the fetch wrapper turns non-OK into `Error("OCR server 404: ...")`,
surfaced via `setJobError`. Promised by the server API.

## Anomalies

### Server restart loses running jobs

_Covers:_ seq 14, `OCR_SERVER` → `LIBRARY_UI` (outcome: anomaly)

`_jobs` is a module-level dict (`api.py`); a server restart during a long
job orphans it — the next poll 404s and the user sees a raw "OCR server
404" with no explanation that the work is lost, and no artifact to retry
from. Disposition: scope cut for v1; test candidate for a friendlier
"job lost — server restarted?" message keyed on 404-during-running.

### No upload-size or concurrent-job guard in the UI

_Covers:_ seq 2, `LIBRARY_UI` → `OCR_SERVER` (outcome: anomaly)

The UI does not disable "OCR this PDF" for a second PDF while a job runs
(`startOcr` has no busy guard beyond the toolbar spinner keyed to one
job), and the server caps uploads at 200 MB but the UI gives no
pre-submit size feedback. Disposition: test candidate.

## Verification

- `src/ocr_server/api.py:parse_pdf_async` — 202 + background task +
  progress fields (`phase`, `pages_done`, `pages_total`) confirmed.
- `src/ocr_server/api.py:job_status` — 404 on unknown id confirmed.
- `src/ocr_server/api.py:MAX_UPLOAD_BYTES` — 200 MB cap confirmed.
- `ui/src/features/library/pages/library-page.tsx:startOcr` — upload
  build, poll, save, refresh confirmed.
- `ui/src/features/library/library.ocr.ts:pollJobUntilDone` — interval +
  timeout + error propagation confirmed.

## Serialization notes

### Server nodes share group 7

- `OCR_SERVER` and `OCR_JOB_POLL` grouped together (external process) to
  keep the swimlane count small; they remain distinct nodes because the
  submit and poll paths are separately addressable endpoints.

### Poll loop as repeated seq 5–6

- `pollJobUntilDone` loops; the graph shows one iteration (multigraph
  true permits repeats at the same seq if needed later).

## References

### Spec and decisions

- Conversation plan (this session): client-side orchestration — the client
  saves `stem.md` + `stem.spans.jsonl` alongside the PDF; server returns
  JSONL + markdown in the job result.

### Related lifecycles

- [pdf-select-sidecar-load](pdf-select-sidecar-load.md) — loads what this
  lifecycle saves.

### Code

- `src/ocr_server/api.py` — job lifecycle + progress.
- `ui/src/features/library/library.ocr.ts` — submit/poll client.
- `ui/src/features/library/pages/library-page.tsx` — orchestration.
- `ui/src-tauri/src/lib.rs` — scoped sidecar writes.
