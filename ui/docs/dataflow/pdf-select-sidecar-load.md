<!-- pair-contract: urn:data-flow-graph:schema:3 -->
# pdf-select-sidecar-load. PDF Selection & Sidecar Load

When the user opens a library root and clicks a PDF, the app lists the
annotated tree, loads the PDF's markdown and spans sidecars, previews the
page with span overlays, and scroll-syncs the markdown pane to the current
page — degrading gracefully when sidecars or anchors are absent.

- **Status:** Initialize — everything here exists in code today (the Tauri
  rewrite), authored from the agreed UI plan before full implementation.
- **Entry point:** `LibraryPage` (Tauri window, `/` route,
  `ui/src/routes/index.tsx`)
- **Trigger:** User click on a PDF leaf in the library tree.
- **Termination:** return-to-initiator (markdown/spans state set in
  `LIBRARY_UI`); `FS_ROOT` is the server-side sink for file reads.
- **Response:**
  - **Success:** markdown string + `Map<page, Span[]>` in state; pdf.js
    canvas render; markdown chunks scroll-synced to `currentPage`.
  - **Failure:** missing sidecars resolve to `null` state (`setSpans(null)`
    catch in `selectNode`) — handled; panes show empty-state hints.
  - **Exception:** tree command failure surfaces as an `Err(String)` from
    the Rust command, rejected promise in `LibraryPage` — currently only
    logged by the invoke rejection; unhandled escape for the user.

## Participants

| Node ID | Group | Role | Evidence | Symbol | What | Source |
| --- | --- | --- | --- | --- | --- | --- |
| `LIBRARY_UI` | 1 | initiator | code | `LibraryPage` | Three-pane shell; owns markdown/spans/page state | `ui/src/features/library/pages/library-page.tsx:LibraryPage` |
| `RUST_TREE_CMD` | 2 | intermediary | code | `list_tree` | Walks root, annotates hasMd/hasSpans | `ui/src-tauri/src/lib.rs:list_tree` |
| `RUST_READ_CMD` | 2 | intermediary | code | `read_text_file` | Reads sidecars inside root | `ui/src-tauri/src/lib.rs:read_text_file` |
| `LIBRARY_FUNCTIONS` | 3 | intermediary | code | `selectNode` | Invoke wrappers + span map parse | `ui/src/features/library/pages/library-page.tsx:selectNode` |
| `PDF_PANE` | 1 | intermediary | code | `PdfPane` | Canvas render + span overlay | `ui/src/features/library/components/pdf-pane.tsx:PdfPane` |
| `MD_PANE` | 1 | intermediary | code | `MarkdownPane` | Anchor chunking + scroll sync | `ui/src/features/library/components/markdown-pane.tsx:MarkdownPane` |
| `FS_ROOT` | 8 | sink | code | `-` | Files under the chosen root | `ui/src-tauri/src/lib.rs:set_root` |

## Sequence

1. (seq 1–3) `listTree()` → `list_tree` walks the root and returns
   `TreeNode[]`; PDF leaves carry `hasMd`/`hasSpans` from sibling stat
   (`lib.rs:classify`).
2. (seq 4–10) `selectNode` clears state, then `readTextFile(<stem>.md)` and
   `readTextFile(<stem>.spans.jsonl)`; spans parsed per line via
   `SpanSchema.parse` into `Map<page, Span[]>`.
3. (seq 11–13) `PdfPane` fetches bytes via `convertFileSrc` (fs scope
   granted in `set_root`) and renders the page to canvas; span rects
   overlay from the 0–1000 boxes.
4. (seq 14–16) Arrow keys / buttons fire `onPageChange`; `MarkdownPane`
   scrolls the page's anchor chunk into view (`splitByAnchors`); without
   anchors the header shows "no page anchors — page sync off".

## Error paths

### Missing sidecar files

_Covers:_ seq 5–10, `LIBRARY_FUNCTIONS` → `LIBRARY_UI` (outcome: error)

`readTextFile` rejects (Rust returns `Err`), the `.catch(() => setSpans(null))`
branch runs, markdown stays `null`, and the markdown pane shows the
"no sidecar — run OCR" hint. Promised by the UI plan (graceful degradation)
and implemented in `library-page.tsx:selectNode`.

## Anomalies

### Unhandled promise rejection on tree command failure

_Covers:_ seq 1–3, `LIBRARY_UI` → `RUST_TREE_CMD` (outcome: anomaly)

If `list_tree` fails (unreadable root, permission error), `listTree()`
rejects and `loadTree`'s promise rejection is unhandled — the UI keeps the
old tree with no user-visible error. Verified in
`library-page.tsx:loadTree` (no `.catch`). Disposition: test candidate
(add an error toast + keep-old-tree state).

### Markdown loaded but spans file corrupt

_Covers:_ seq 8–10, `LIBRARY_FUNCTIONS` → `LIBRARY_UI` (outcome: anomaly)

A malformed JSONL line throws inside `selectNode`'s then-chain **after**
`setMarkdown` already ran — the catch sets `setSpans(null)` but markdown
remains displayed with no overlay, silently. Disposition: test candidate
(validate spans before setMarkdown, or surface a partial-load warning).

## Verification

- `ui/src/features/library/pages/library-page.tsx:selectNode` — sidecar
  load chain, span map parse, null fallback confirmed.
- `ui/src-tauri/src/lib.rs:classify` — sibling-stat hasMd/hasSpans badges.
- `ui/src/features/library/components/pdf-pane.tsx:PdfPane` —
  convertFileSrc fetch + canvas render + overlay mapping.
- `ui/src/features/library/components/markdown-pane.tsx:splitByAnchors` —
  anchor split + no-anchor degradation hint.

## Serialization notes

- `FS_ROOT` declared `sink` (server-side file reads terminate there);
  `LIBRARY_UI` stays initiator-only per initiator-wins.
- seq 14 modeled `event` (not return): page changes are user-driven
  emissions, not responses to a call.

## References

### Spec and decisions

- Conversation plan (this session): three-pane library, invisible page
  anchors, sidecar files, graceful degradation — agreed before build.

### Related lifecycles

- [pdf-ocr-save](pdf-ocr-save.md) — produces the sidecars this flow loads.

### Code

- `ui/src/features/library/pages/library-page.tsx` — orchestration.
- `ui/src-tauri/src/lib.rs` — scoped fs commands.
- `ui/src/features/library/components/*.tsx` — panes.
